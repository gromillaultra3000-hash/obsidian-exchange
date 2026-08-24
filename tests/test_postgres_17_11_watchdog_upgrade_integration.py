"""Disposable 17.10 -> 17.11 -> 17.10 watchdog and journal-rebind rehearsal."""
from __future__ import annotations

import json
import datetime as dt
import os
import secrets
import subprocess
import sys
import time
from pathlib import Path

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo


ROOT = Path(__file__).resolve().parents[1]
POSTGRES = ROOT / "deploy/postgres"
sys.path.insert(0, str(POSTGRES))

import b64_snapshot_reader_runtime as lease_runtime
import b64_snapshot_reader_runtime_rebind as rebind
import b64_snapshot_reader_transition_gate as transition_gate
import b64_snapshot_reader_watchdog as watchdog
from migration_profile import selected_paths


OLD_REF = "postgres@" + rebind.POSTGRES_17_10_IMAGE_ID
NEW_REF = "postgres@" + rebind.POSTGRES_17_11_IMAGE_ID
ORIGINAL_HBA = Path(
    "/var/lib/docker/volumes/obsidian-postgres-data/_data/"
    ".obsidian-b64-hba-v1/original.pg_hba"
)


pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_B64_PG_UPGRADE_INTEGRATION") != "1",
    reason="set RUN_B64_PG_UPGRADE_INTEGRATION=1 for the Docker rehearsal",
)


def _run(args: list[str], *, check: bool = True, **kwargs):
    return subprocess.run(
        args,
        check=check,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        **kwargs,
    )


def _start(name: str, volume: str, image: str) -> dict:
    _run(
        [
            "/usr/bin/docker", "run", "--detach", "--name", name,
            # Compose selects by these labels. Contract containers must never
            # enter the production project or its foreground systemd unit.
            "--label", f"com.docker.compose.project={rebind.CONTRACT_COMPOSE_PROJECT}",
            "--label", f"com.docker.compose.service={rebind.CONTRACT_COMPOSE_SERVICE}",
            "--publish", "127.0.0.1::5432",
            "--mount", f"type=volume,src={volume},dst=/var/lib/postgresql/data",
            "--env", "POSTGRES_DB=obsidian_exchange",
            "--env", "POSTGRES_USER=postgres",
            "--env", "POSTGRES_HOST_AUTH_METHOD=trust",
            "--health-cmd", "pg_isready --quiet --username=postgres --dbname=obsidian_exchange",
            "--health-interval", "1s", "--health-timeout", "5s",
            "--health-retries", "60", "--health-start-period", "5s",
            image,
        ]
    )
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        value = json.loads(_run(["/usr/bin/docker", "inspect", name]).stdout)[0]
        if value["State"].get("Health", {}).get("Status") == "healthy":
            return value
        if value["State"].get("Running") is not True:
            raise AssertionError(value["State"])
        time.sleep(0.5)
    raise AssertionError("contract container health timeout")


def _production_tuple() -> dict | None:
    inspected = _run(["/usr/bin/docker", "inspect", rebind.PRODUCTION_CONTAINER], check=False)
    if inspected.returncode != 0:
        return None
    value = json.loads(inspected.stdout)[0]
    return {
        "id": value["Id"],
        "image": value["Image"],
        "pid": value["State"]["Pid"],
        "status": value["State"]["Status"],
        "health": value["State"].get("Health", {}).get("Status"),
        "startedAt": value["State"]["StartedAt"],
    }


def _systemd_contract_command(
    *, name: str, volume: str, script: Path, arguments: list[str]
) -> dict:
    state_path = (
        f"/var/lib/docker/volumes/{volume}/_data/"
        f"{rebind.STATE_DIRECTORY}"
    )
    unit = f"b64-upgrade-contract-{str(time.time_ns())[-12:]}"
    completed = _run(
        [
            "/usr/bin/systemd-run", "--wait", "--pipe", "--collect", "--quiet",
            f"--unit={unit}", "--property=Type=oneshot",
            "--property=NoNewPrivileges=yes", "--property=ProtectSystem=strict",
            "--property=ProtectHome=read-only",
            "--property=RestrictAddressFamilies=AF_UNIX",
            "--property=ReadWritePaths=/run/lock",
            f"--property=ReadWritePaths={state_path}",
            sys.executable, str(script),
            "--container", name,
            "--expected-volume-name", volume,
            *arguments,
        ],
    )
    receipts = [
        json.loads(line) for line in completed.stdout.splitlines()
        if line.strip().startswith("{")
    ]
    assert len(receipts) == 1, completed.stdout
    return receipts[0]


def _systemd_transition(
    *, name: str, volume: str, image_id: str, version: int, system_id: str
) -> dict:
    return _systemd_contract_command(
        name=name,
        volume=volume,
        script=POSTGRES / "b64_snapshot_reader_transition_gate.py",
        arguments=[
            "--expected-image-id", image_id,
            "--expected-server-version-num", str(version),
            "--expected-system-identifier", system_id,
            "--allow-contract-container", "--apply",
        ],
    )


def _systemd_watchdog(
    *, name: str, volume: str, image_id: str, version: int, system_id: str
) -> dict:
    return _systemd_contract_command(
        name=name,
        volume=volume,
        script=POSTGRES / "b64_snapshot_reader_watchdog.py",
        arguments=[
            "--expected-image-id", image_id,
            "--expected-server-version-num", str(version),
            "--expected-system-identifier", system_id,
            "--allow-contract-container", "--require-dormant",
        ],
    )


def _write_lifecycle_assets(
    *,
    directory: Path,
    suffix: str,
    name: str,
    volume: str,
    image_ref: str,
    image_id: str,
    version: int,
    system_id: str,
) -> tuple[str, str, Path]:
    compose = directory / "compose.yml"
    compose.write_text(
        f"""name: obsidian-postgres-contract
services:
  postgres-contract:
    image: {image_ref}
    pull_policy: never
    platform: linux/amd64
    container_name: {name}
    restart: \"no\"
    environment:
      POSTGRES_DB: obsidian_exchange
      POSTGRES_USER: postgres
      POSTGRES_HOST_AUTH_METHOD: trust
    volumes:
      - postgres_data:/var/lib/postgresql/data
    ports:
      - \"127.0.0.1::5432\"
    healthcheck:
      test: [\"CMD-SHELL\", \"pg_isready --quiet --username=postgres --dbname=obsidian_exchange\"]
      interval: 1s
      timeout: 5s
      retries: 60
      start_period: 5s
volumes:
  postgres_data:
    external: true
    name: {volume}
""",
        encoding="utf-8",
    )
    compose.chmod(0o600)
    main = f"b64-upgrade-lifecycle-{suffix}.service"
    watchdog_service = f"b64-upgrade-watchdog-{suffix}.service"
    timer = f"b64-upgrade-watchdog-{suffix}.timer"
    state_path = (
        f"/var/lib/docker/volumes/{volume}/_data/{rebind.STATE_DIRECTORY}"
    )
    python = sys.executable
    main_path = Path("/run/systemd/system") / main
    main_path.write_text(
        f"""[Unit]
Description=Disposable B64 PostgreSQL lifecycle contract
Requires=docker.service
After=docker.service
Wants={timer}

[Service]
Type=simple
ExecStartPre=/usr/bin/docker compose --project-name obsidian-postgres-contract --file {compose} config --quiet
ExecStart=/usr/bin/docker compose --project-name obsidian-postgres-contract --file {compose} up --no-color --no-log-prefix --abort-on-container-exit --exit-code-from postgres-contract
ExecStartPost=/bin/sh -ec 'i=0; while [ "$$i" -lt 60 ]; do status=$$(/usr/bin/docker inspect --format={{{{.State.Health.Status}}}} {name} 2>/dev/null || true); [ "$$status" = healthy ] && exit 0; i=$$((i + 1)); sleep 1; done; exit 1'
ExecStartPost={python} {POSTGRES / 'b64_snapshot_reader_transition_gate.py'} --container {name} --expected-image-id {image_id} --expected-volume-name {volume} --expected-server-version-num {version} --expected-system-identifier {system_id} --allow-contract-container --apply
ExecStartPost={python} {POSTGRES / 'b64_snapshot_reader_watchdog.py'} --container {name} --expected-image-id {image_id} --expected-volume-name {volume} --expected-server-version-num {version} --expected-system-identifier {system_id} --allow-contract-container --require-dormant
ExecStop={python} {POSTGRES / 'b64_postgres_shutdown.py'} --container {name} --expected-volume-name {volume} --expected-system-identifier {system_id} --compose-path {compose} --compose-project obsidian-postgres-contract --compose-service postgres-contract --allow-contract-container
TimeoutStartSec=120
TimeoutStopSec=210
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=/run/lock {state_path}
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
""",
        encoding="utf-8",
    )
    watchdog_path = Path("/run/systemd/system") / watchdog_service
    watchdog_path.write_text(
        f"""[Unit]
Description=Disposable B64 lifecycle dormant watchdog
Requires={main}
BindsTo={main}
After={main}

[Service]
Type=oneshot
ExecStart={python} {POSTGRES / 'b64_snapshot_reader_watchdog.py'} --container {name} --expected-image-id {image_id} --expected-volume-name {volume} --expected-server-version-num {version} --expected-system-identifier {system_id} --allow-contract-container --require-dormant
SuccessExitStatus=SIGTERM
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=/run/lock {state_path}
RestrictAddressFamilies=AF_UNIX
""",
        encoding="utf-8",
    )
    timer_path = Path("/run/systemd/system") / timer
    timer_path.write_text(
        f"""[Unit]
Description=Disposable B64 lifecycle timer
Requires={main}
BindsTo={main}
After={main}

[Timer]
OnActiveSec=1s
OnUnitInactiveSec=2s
AccuracySec=100ms
Unit={watchdog_service}
""",
        encoding="utf-8",
    )
    for path in (main_path, watchdog_path, timer_path):
        path.chmod(0o644)
    _run(["/usr/bin/systemctl", "daemon-reload"])
    return main, timer, compose


def _admin_dsn(container: dict) -> str:
    return make_conninfo(
        host=f"/proc/{container['State']['Pid']}/root/var/run/postgresql",
        dbname="obsidian_exchange", user="postgres", port=5432,
        connect_timeout=5, sslmode="disable", target_session_attrs="read-write",
    )


def _tcp_dsn(container: dict, passfile_fd: int | None = None) -> str:
    binding = container["NetworkSettings"]["Ports"]["5432/tcp"][0]
    values = {
        "host": "127.0.0.1", "port": binding["HostPort"],
        "dbname": "obsidian_exchange", "user": "postgres", "connect_timeout": 5,
    }
    if passfile_fd is not None:
        values["passfile"] = f"/proc/self/fd/{passfile_fd}"
    return make_conninfo(**values)


def _metadata(container: dict, expected_version: int) -> tuple[str, int]:
    dsn = _admin_dsn(container)
    with psycopg.connect(dsn) as conn:
        row = conn.execute(
            "SELECT system_identifier::text,current_setting('server_version_num')::int "
            "FROM pg_control_system()"
        ).fetchone()
        assert row[1] == expected_version
        role = conn.execute(
            "SELECT r.rolcanlogin,(a.rolpassword IS NULL),"
            "COALESCE(a.rolvaliduntil::text,''),"
            "(SELECT count(*) FROM pg_stat_activity WHERE usename=%s) "
            "FROM pg_roles r JOIN pg_authid a ON a.oid=r.oid WHERE r.rolname=%s",
            (rebind.ROLE, rebind.ROLE),
        ).fetchone()
        assert role in {
            (False, True, "", 0), (False, True, "infinity", 0)
        }
        hba = conn.execute(
            "SELECT encode(sha256(pg_read_binary_file(current_setting('hba_file'))),'hex')"
        ).fetchone()[0]
        assert hba == rebind.EXPECTED_DEPLOYED_HBA_SHA256
    return row


def test_minor_upgrade_watchdog_and_reverse_rebind():
    assert ORIGINAL_HBA.is_file()
    production_before = _production_tuple()
    suffix = str(time.time_ns())[-12:]
    name = f"b64-hba-contract-{suffix}"
    volume = "b64" + secrets.token_hex(31)[:61]
    lifecycle_directory = Path(f"/tmp/b64-systemd-contract-{suffix}")
    lifecycle_directory.mkdir(mode=0o700)
    _run(["/usr/bin/docker", "volume", "create", volume])
    container: dict | None = None
    observation_fd = -1
    password = secrets.token_urlsafe(48)
    first_id = second_id = None
    lifecycle_main = lifecycle_timer = None
    lifecycle_compose: Path | None = None
    try:
        container = _start(name, volume, OLD_REF)
        tcp_dsn = _tcp_dsn(container)
        admin_dsn = _admin_dsn(container)
        with psycopg.connect(tcp_dsn, autocommit=True) as conn:
            conn.execute((POSTGRES / "bootstrap_roles.sql").read_text("utf-8"))
        with psycopg.connect(tcp_dsn) as conn:
            conn.execute((POSTGRES / "prepare_database.sql").read_text("utf-8"))
        with psycopg.connect(tcp_dsn) as conn:
            conn.execute("SET ROLE obsidian_migrator")
            for migration in selected_paths(ROOT, "production-cutover"):
                conn.execute(migration.read_text("utf-8"))
        with psycopg.connect(tcp_dsn, autocommit=True) as conn:
            conn.execute((POSTGRES / "runtime_privileges.sql").read_text("utf-8"))
            conn.execute("SET obsidian.snapshot_reader_expected_database='obsidian_exchange'")
            conn.execute("SET obsidian.snapshot_reader_require_absent='on'")
            conn.execute(sql.SQL(
                "SET obsidian.snapshot_reader_deployment_nonce={}"
            ).format(sql.Literal("d" * 32)))
            conn.execute((POSTGRES / "provision_b64_snapshot_reader.sql").read_text("utf-8"))
            conn.execute(sql.SQL("ALTER ROLE postgres PASSWORD {}").format(sql.Literal(password)))

        _run(["/usr/bin/docker", "cp", str(ORIGINAL_HBA), f"{name}:/var/lib/postgresql/data/pg_hba.conf"])
        _run(["/usr/bin/docker", "exec", "-u", "0", name, "chown", "70:70", "/var/lib/postgresql/data/pg_hba.conf"])
        _run(["/usr/bin/docker", "exec", "-u", "0", name, "chmod", "0600", "/var/lib/postgresql/data/pg_hba.conf"])
        with psycopg.connect(tcp_dsn, autocommit=True) as conn:
            assert conn.execute("SELECT pg_reload_conf()").fetchone()[0] is True

        port = container["NetworkSettings"]["Ports"]["5432/tcp"][0]["HostPort"]
        observation_fd = lease_runtime._sealed_pgpass_memfd(
            f"127.0.0.1:{port}:obsidian_exchange:postgres:{password}\n".encode(),
            "b64-upgrade-observation",
        )
        observation_dsn = _tcp_dsn(container, observation_fd)
        environment = dict(os.environ)
        environment["EXCHANGE_DATABASE_URL"] = observation_dsn
        environment["B64_LOCAL_ADMIN_DSN"] = admin_dsn
        first_id = container["Id"].removeprefix("sha256:")
        hba = _run(
            [
                sys.executable, str(POSTGRES / "deploy_b64_snapshot_reader_hba.py"),
                "--postgres-env", "EXCHANGE_DATABASE_URL",
                "--admin-postgres-env", "B64_LOCAL_ADMIN_DSN",
                "--container", name, "--expected-container-id", first_id,
                "--expected-image-id", rebind.POSTGRES_17_10_IMAGE_ID,
                "--allow-contract-container", "--apply",
            ],
            env=environment,
            pass_fds=(observation_fd,),
        )
        assert json.loads(hba.stdout)["status"] == "HBA_DEPLOYED_PARSED_DORMANT"
        system_id, _ = _metadata(container, 170010)
        old_watchdog = watchdog.watchdog_once(
            container_name=name,
            expected_image_id=rebind.POSTGRES_17_10_IMAGE_ID,
            expected_volume_name=volume,
            expected_server_version_num=170010,
            expected_system_identifier=system_id,
            allow_contract_container=True,
            require_dormant=True,
        )
        assert old_watchdog["status"] == "DORMANT_VERIFIED"

        _run(["/usr/bin/docker", "stop", "--time", "120", name])
        _run(["/usr/bin/docker", "rm", name])
        lifecycle_main, lifecycle_timer, lifecycle_compose = _write_lifecycle_assets(
            directory=lifecycle_directory,
            suffix=suffix,
            name=name,
            volume=volume,
            image_ref=NEW_REF,
            image_id=rebind.POSTGRES_17_11_IMAGE_ID,
            version=170011,
            system_id=system_id,
        )
        _run(["/usr/bin/systemctl", "start", lifecycle_main])
        assert _run(["/usr/bin/systemctl", "is-active", lifecycle_main]).stdout.strip() == "active"
        assert _run(["/usr/bin/systemctl", "is-active", lifecycle_timer]).stdout.strip() == "active"
        container = json.loads(_run(["/usr/bin/docker", "inspect", name]).stdout)[0]
        second_id = container["Id"].removeprefix("sha256:")
        assert second_id != first_id
        state_metadata = os.stat(
            f"/var/lib/docker/volumes/{volume}/_data/.obsidian-b64-hba-v1"
        )
        assert state_metadata.st_mode & 0o777 == 0o700
        assert (state_metadata.st_uid, state_metadata.st_gid) == (0, 0)
        rebound_journal = json.loads(
            Path(
                f"/var/lib/docker/volumes/{volume}/_data/"
                f"{rebind.STATE_DIRECTORY}/{rebind.JOURNAL_NAME}"
            ).read_text("utf-8")
        )
        assert rebound_journal["containerId"] == second_id
        assert rebound_journal["containerImageId"] == rebind.POSTGRES_17_11_IMAGE_ID
        _metadata(container, 170011)

        old_pid = container["State"]["Pid"]
        _run(["/usr/bin/systemctl", "restart", lifecycle_main])
        assert _run(["/usr/bin/systemctl", "is-active", lifecycle_timer]).stdout.strip() == "active"
        container = json.loads(_run(["/usr/bin/docker", "inspect", name]).stdout)[0]
        deadline = time.monotonic() + 60
        while container["State"].get("Health", {}).get("Status") != "healthy":
            assert time.monotonic() < deadline
            time.sleep(0.5)
            container = json.loads(_run(["/usr/bin/docker", "inspect", name]).stdout)[0]
        assert container["State"]["Pid"] != old_pid
        _metadata(container, 170011)

        with psycopg.connect(_admin_dsn(container), autocommit=True) as conn:
            conn.execute(sql.SQL(
                "ALTER ROLE {} LOGIN PASSWORD {} VALID UNTIL {}"
            ).format(
                sql.Identifier(rebind.ROLE), sql.Literal("synthetic-orphan-only"),
                sql.Literal((dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=60)).isoformat()),
            ))
        time.sleep(4)
        _metadata(container, 170011)

        _run(["/usr/bin/systemctl", "stop", lifecycle_main])
        assert _run(
            ["/usr/bin/systemctl", "is-active", lifecycle_timer], check=False
        ).stdout.strip() == "inactive"
        lifecycle_main, lifecycle_timer, lifecycle_compose = _write_lifecycle_assets(
            directory=lifecycle_directory,
            suffix=suffix,
            name=name,
            volume=volume,
            image_ref=OLD_REF,
            image_id=rebind.POSTGRES_17_10_IMAGE_ID,
            version=170010,
            system_id=system_id,
        )
        _run(["/usr/bin/systemctl", "start", lifecycle_main])
        container = json.loads(_run(["/usr/bin/docker", "inspect", name]).stdout)[0]
        third_id = container["Id"].removeprefix("sha256:")
        assert _run(["/usr/bin/systemctl", "is-active", lifecycle_timer]).stdout.strip() == "active"
        assert third_id not in {first_id, second_id}
        _metadata(container, 170010)
        _run(["/usr/bin/systemctl", "stop", lifecycle_main])
        lifecycle_log = _run(
            [
                "/usr/bin/journalctl", "--unit", lifecycle_main,
                "--no-pager", "--output", "cat",
            ]
        ).stdout
        assert lifecycle_log.count('"status": "RECONCILED_AND_STOPPED"') >= 2
    finally:
        if observation_fd >= 0:
            os.close(observation_fd)
        if lifecycle_main is not None:
            _run(["/usr/bin/systemctl", "stop", lifecycle_main], check=False)
            _run(["/usr/bin/systemctl", "reset-failed", lifecycle_main], check=False)
            _run(
                [
                    "/usr/bin/systemctl", "reset-failed",
                    f"b64-upgrade-watchdog-{suffix}.service",
                ],
                check=False,
            )
        if lifecycle_compose is not None:
            _run(
                [
                    "/usr/bin/docker", "compose", "--project-name",
                    "obsidian-postgres-contract", "--file", str(lifecycle_compose),
                    "down", "--remove-orphans",
                ],
                check=False,
            )
        _run(["/usr/bin/docker", "rm", "--force", name], check=False)
        for unit_path in Path("/run/systemd/system").glob(
            f"b64-upgrade-*-{suffix}.*"
        ):
            unit_path.unlink(missing_ok=True)
        _run(["/usr/bin/systemctl", "daemon-reload"], check=False)
        _run(["/usr/bin/docker", "volume", "rm", volume], check=False)
        assert _run(["/usr/bin/docker", "inspect", name], check=False).returncode != 0
        assert _run(["/usr/bin/docker", "volume", "inspect", volume], check=False).returncode != 0
        for item in lifecycle_directory.iterdir():
            item.unlink()
        lifecycle_directory.rmdir()
        assert _production_tuple() == production_before
