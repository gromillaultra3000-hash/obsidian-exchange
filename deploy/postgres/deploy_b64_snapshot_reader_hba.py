#!/usr/bin/env python3
"""Deploy or roll back exact dormant B64 snapshot-reader HBA isolation."""
from __future__ import annotations

import argparse
import ctypes
import datetime as dt
import hashlib
import json
import os
import re
import secrets
import stat
import subprocess
import time
from pathlib import Path
from typing import Any

from deploy_b64_snapshot_reader import (
    DeploymentError,
    _admin_preflight,
    _bind_empty_memfd_passfile,
    _catalog_preflight,
    _inspect_container,
    _load_and_bind_plan,
    _validate_container_admin_dsn,
)
from verify_b64_snapshot_reader import inspect as inspect_role


ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = ROOT / "deploy/postgres/b64_snapshot_reader_hba.v1.json"
ROLE = "obsidian_b64_snapshot_reader"
DATA_DIRECTORY = "/var/lib/postgresql/data"
HBA_NAME = "pg_hba.conf"
STATE_DIRECTORY = ".obsidian-b64-hba-v1"
BACKUP_NAME = "original.pg_hba"
JOURNAL_NAME = "journal.json"
MAX_HBA_BYTES = 128 * 1024
RENAME_EXCHANGE = 2
STAGE_PATTERN = re.compile(r"[.]obsidian-b64-hba-stage-[0-9a-f]{24}")
JOURNAL_TEMP_PATTERN = re.compile(r"journal[.][0-9a-f]{16}[.]tmp")
RECOVERABLE_JOURNAL_PHASES = frozenset({
    "BACKUP_VERIFIED",
    "APPLY_ATTEMPTED",
    "CANDIDATE_INSTALLED",
    "DEPLOYED_VERIFIED",
    "ROLLBACK_ATTEMPTED",
})
MANAGED_BLOCK = (
    "# BEGIN OBSIDIAN_B64_SNAPSHOT_READER_HBA_V1\n"
    "# Managed by deploy/postgres/deploy_b64_snapshot_reader_hba.py\n"
    "local all obsidian_b64_snapshot_reader reject\n"
    "local replication obsidian_b64_snapshot_reader reject\n"
    "host obsidian_exchange obsidian_b64_snapshot_reader "
    "127.0.0.1/32 scram-sha-256\n"
    "host replication obsidian_b64_snapshot_reader 0.0.0.0/0 reject\n"
    "host replication obsidian_b64_snapshot_reader ::/0 reject\n"
    "host all obsidian_b64_snapshot_reader 0.0.0.0/0 reject\n"
    "host all obsidian_b64_snapshot_reader ::/0 reject\n"
    "# END OBSIDIAN_B64_SNAPSHOT_READER_HBA_V1\n\n"
).encode("ascii")


class HbaDeploymentError(RuntimeError):
    pass


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _safe_reason(exc: BaseException) -> str:
    value = str(exc)
    if isinstance(exc, (HbaDeploymentError, DeploymentError)) and re.fullmatch(
        r"[A-Z0-9_]+(?::[A-Za-z0-9_.-]+)?", value
    ):
        return value
    return "UNEXPECTED_HBA_DEPLOYMENT_FAILURE"


def _docker_inspect(name: str) -> dict[str, Any]:
    result = subprocess.run(
        ["docker", "inspect", name], capture_output=True, text=True,
        check=False, timeout=10,
        env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")},
    )
    if result.returncode != 0:
        raise HbaDeploymentError("CONTAINER_INSPECT_FAILED")
    try:
        return json.loads(result.stdout)[0]
    except (IndexError, TypeError, json.JSONDecodeError) as exc:
        raise HbaDeploymentError("INVALID_CONTAINER_INSPECTION") from exc


def _load_manifest() -> dict[str, Any]:
    try:
        value = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HbaDeploymentError("HBA_MANIFEST_INVALID") from exc
    exact = {
        "schemaVersion": "obsidian-b64-snapshot-reader-hba.v1",
        "role": ROLE,
        "database": "obsidian_exchange",
        "systemIdentifier": "7672203973020184609",
        "dataDirectory": DATA_DIRECTORY,
        "dataVolumeName": "obsidian-postgres-data",
        "hbaFile": f"{DATA_DIRECTORY}/{HBA_NAME}",
        "rollbackDirectory": f"{DATA_DIRECTORY}/{STATE_DIRECTORY}",
        "rollbackBackupFile": (
            f"{DATA_DIRECTORY}/{STATE_DIRECTORY}/{BACKUP_NAME}"
        ),
        "journalFile": f"{DATA_DIRECTORY}/{STATE_DIRECTORY}/{JOURNAL_NAME}",
        "expectedOriginalSha256": (
            "45b68cd420caab6d19725857c309871880a66a4c195bcd7e1604e7c334b6be82"
        ),
        "managedBlockSha256": (
            "a40eae525e810f9b1014e8b7e434ae5ddeead55feb9fc8c80d63804488a30ff3"
        ),
        "expectedDeployedSha256": (
            "08b049674e7593bc87c8e78744ba6b65b557750807c17e860920931aa1b3d3b6"
        ),
    }
    for key, expected in exact.items():
        if value.get(key) != expected:
            raise HbaDeploymentError(f"HBA_MANIFEST_MISMATCH:{key}")
    if _sha256(MANAGED_BLOCK) != value["managedBlockSha256"]:
        raise HbaDeploymentError("MANAGED_BLOCK_DIGEST_MISMATCH")
    return value


def _bind_mount(raw: dict[str, Any], manifest: dict[str, Any], *,
                allow_contract_container: bool = False) -> Path:
    matches = [
        item for item in raw.get("Mounts", [])
        if item.get("Destination") == manifest["dataDirectory"]
    ]
    if len(matches) != 1:
        raise HbaDeploymentError("PGDATA_MOUNT_NOT_EXACT")
    item = matches[0]
    volume_name_matches = (
        item.get("Name") == manifest["dataVolumeName"]
        or (allow_contract_container
            and isinstance(item.get("Name"), str)
            and bool(re.fullmatch(r"[0-9a-f]{64}", item["Name"])))
    )
    if (item.get("Type") != "volume" or item.get("RW") is not True
            or not volume_name_matches):
        raise HbaDeploymentError("PGDATA_VOLUME_IDENTITY_MISMATCH")
    source = item.get("Source")
    if not isinstance(source, str) or not source.startswith(
            "/var/lib/docker/volumes/"):
        raise HbaDeploymentError("PGDATA_SOURCE_PATH_INVALID")
    path = Path(source)
    if path.is_symlink() or not path.is_dir():
        raise HbaDeploymentError("PGDATA_SOURCE_NOT_REGULAR_DIRECTORY")
    return path


def _cluster_identity(dsn: str) -> dict[str, Any]:
    import psycopg

    with psycopg.connect(dsn, connect_timeout=5) as conn, conn.cursor() as cur:
        cur.execute("SET LOCAL statement_timeout='10s'")
        cur.execute(
            "SELECT current_database(),current_setting('server_version_num')::int,"
            "current_setting('data_directory'),current_setting('hba_file'),"
            "current_setting('ssl'),current_setting('listen_addresses'),"
            "current_setting('password_encryption'),system_identifier::text,"
            "pg_postmaster_start_time() FROM pg_control_system()"
        )
        row = cur.fetchone()
    return {
        "database": row[0], "serverVersionNum": row[1],
        "dataDirectory": row[2], "hbaFile": row[3], "ssl": row[4],
        "listenAddresses": row[5], "passwordEncryption": row[6],
        "systemIdentifier": row[7], "postmasterStartTime": row[8],
    }


def _verify_cluster(value: dict[str, Any], manifest: dict[str, Any], *,
                    allow_contract_container: bool = False) -> None:
    if (value["database"] != manifest["database"]
            or value["serverVersionNum"] // 10000 != 17
            or value["dataDirectory"] != manifest["dataDirectory"]
            or value["hbaFile"] != manifest["hbaFile"]
            or (not allow_contract_container
                and value["systemIdentifier"] != manifest["systemIdentifier"])
            or value["ssl"] != "off" or value["listenAddresses"] != "*"
            or value["passwordEncryption"] != "scram-sha-256"):
        raise HbaDeploymentError("CLUSTER_IDENTITY_OR_AUTH_CONFIG_MISMATCH")


def _open_pgdata(path: Path) -> int:
    return os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)


def _read_at(directory_fd: int, name: str) -> tuple[bytes, os.stat_result]:
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory_fd)
    try:
        metadata = os.fstat(fd)
        if not stat.S_ISREG(metadata.st_mode):
            raise HbaDeploymentError("HBA_TARGET_NOT_REGULAR_FILE")
        if metadata.st_size <= 0 or metadata.st_size > MAX_HBA_BYTES:
            raise HbaDeploymentError("HBA_TARGET_SIZE_INVALID")
        chunks = []
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks), metadata
    finally:
        os.close(fd)


def _validate_hba_metadata(metadata: os.stat_result) -> None:
    if (stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_uid != 70 or metadata.st_gid != 70):
        raise HbaDeploymentError("HBA_TARGET_METADATA_MISMATCH")


def _mkdir_state(directory_fd: int) -> int:
    try:
        os.mkdir(STATE_DIRECTORY, 0o700, dir_fd=directory_fd)
    except FileExistsError as exc:
        raise HbaDeploymentError("HBA_STATE_DIRECTORY_ALREADY_EXISTS") from exc
    os.fsync(directory_fd)
    state_fd = os.open(
        STATE_DIRECTORY, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
        dir_fd=directory_fd,
    )
    try:
        os.fchmod(state_fd, 0o700)
        os.fchown(state_fd, 0, 0)
        os.fsync(state_fd)
        os.fsync(directory_fd)
        metadata = os.fstat(state_fd)
    except BaseException:
        os.close(state_fd)
        try:
            os.rmdir(STATE_DIRECTORY, dir_fd=directory_fd)
            os.fsync(directory_fd)
        except OSError:
            pass
        raise
    if (stat.S_IMODE(metadata.st_mode) != 0o700 or metadata.st_uid != 0
            or metadata.st_gid != 0):
        os.close(state_fd)
        try:
            os.rmdir(STATE_DIRECTORY, dir_fd=directory_fd)
            os.fsync(directory_fd)
        except OSError:
            pass
        raise HbaDeploymentError("HBA_STATE_DIRECTORY_METADATA_MISMATCH")
    return state_fd


def _open_state(directory_fd: int) -> int:
    state_fd = os.open(
        STATE_DIRECTORY, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
        dir_fd=directory_fd,
    )
    metadata = os.fstat(state_fd)
    if (stat.S_IMODE(metadata.st_mode) != 0o700 or metadata.st_uid != 0
            or metadata.st_gid != 0):
        os.close(state_fd)
        raise HbaDeploymentError("HBA_STATE_DIRECTORY_METADATA_MISMATCH")
    return state_fd


def _read_journal(state_fd: int) -> dict[str, Any]:
    value, metadata = _read_at(state_fd, JOURNAL_NAME)
    if (stat.S_IMODE(metadata.st_mode) != 0o600 or metadata.st_uid != 0
            or metadata.st_gid != 0):
        raise HbaDeploymentError("HBA_JOURNAL_METADATA_MISMATCH")
    try:
        journal = json.loads(value)
    except json.JSONDecodeError as exc:
        raise HbaDeploymentError("HBA_JOURNAL_INVALID") from exc
    if not isinstance(journal, dict):
        raise HbaDeploymentError("HBA_JOURNAL_INVALID")
    return journal


def _validate_journal(
    journal: dict[str, Any], before_container: dict[str, Any],
    cluster_before: dict[str, Any], manifest: dict[str, Any],
    allowed_phases: frozenset[str], *, strict_pid: bool,
) -> None:
    expected = {
        "schemaVersion": "obsidian-b64-hba-journal.v1",
        "containerId": before_container["containerId"],
        "containerImageId": before_container["imageId"],
        "systemIdentifier": cluster_before["systemIdentifier"],
        "originalSha256": manifest["expectedOriginalSha256"],
        "deployedSha256": manifest["expectedDeployedSha256"],
    }
    if (not re.fullmatch(r"[0-9a-f]{32}", journal.get("nonce", ""))
            or journal.get("phase") not in allowed_phases
            or not isinstance(journal.get("containerPid"), int)
            or journal["containerPid"] <= 0
            or (strict_pid and journal["containerPid"]
                != before_container["containerPid"])
            or any(journal.get(key) != expected_value
                   for key, expected_value in expected.items())):
        raise HbaDeploymentError("ROLLBACK_JOURNAL_BINDING_MISMATCH")
    if (journal["phase"] == "DEPLOYED_VERIFIED"
            and not isinstance(journal.get("verifiedAt"), str)):
        raise HbaDeploymentError("ROLLBACK_JOURNAL_BINDING_MISMATCH")


def _read_recovery_at(
    directory_fd: int, name: str, *, mode: int, uid: int, gid: int,
) -> bytes:
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory_fd)
    try:
        metadata = os.fstat(fd)
        if (not stat.S_ISREG(metadata.st_mode)
                or stat.S_IMODE(metadata.st_mode) != mode
                or metadata.st_uid != uid or metadata.st_gid != gid
                or metadata.st_size > MAX_HBA_BYTES):
            raise HbaDeploymentError("HBA_RECOVERY_FILE_INVALID")
        chunks = []
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(fd)


def _inspect_recovery_entries(
    state_fd: int, before_container: dict[str, Any],
    cluster_before: dict[str, Any], manifest: dict[str, Any],
) -> tuple[set[str], list[str]]:
    entries = set(os.listdir(state_fd))
    unexpected = {
        name for name in entries
        if name not in {JOURNAL_NAME, BACKUP_NAME}
        and not JOURNAL_TEMP_PATTERN.fullmatch(name)
    }
    if unexpected:
        raise HbaDeploymentError("HBA_STATE_DIRECTORY_UNEXPECTED_ENTRY")
    temporary_journals = sorted(
        name for name in entries if JOURNAL_TEMP_PATTERN.fullmatch(name)
    )
    pending_phases = []
    for name in temporary_journals:
        rendered = _read_recovery_at(
            state_fd, name, mode=0o600, uid=0, gid=0
        )
        try:
            pending = json.loads(rendered)
        except json.JSONDecodeError:
            pending = None
        if isinstance(pending, dict):
            _validate_journal(
                pending, before_container, cluster_before, manifest,
                RECOVERABLE_JOURNAL_PHASES, strict_pid=False,
            )
            pending_phases.append(pending["phase"])
        else:
            pending_phases.append(
                f"INCOMPLETE:{len(rendered)}:{_sha256(rendered)}"
            )
    return entries, pending_phases


def _validate_recovery_bundle(
    state_fd: int, before_container: dict[str, Any],
    cluster_before: dict[str, Any], manifest: dict[str, Any],
    allowed_phases: frozenset[str], *, strict_pid: bool,
) -> tuple[dict[str, Any], bytes, list[str]]:
    entries, pending_phases = _inspect_recovery_entries(
        state_fd, before_container, cluster_before, manifest
    )
    if JOURNAL_NAME not in entries or BACKUP_NAME not in entries:
        raise HbaDeploymentError("HBA_RECOVERY_BUNDLE_INCOMPLETE")
    journal = _read_journal(state_fd)
    _validate_journal(
        journal, before_container, cluster_before, manifest,
        allowed_phases, strict_pid=strict_pid,
    )
    backup = _read_recovery_at(
        state_fd, BACKUP_NAME, mode=0o600, uid=70, gid=70
    )
    if _sha256(backup) != manifest["expectedOriginalSha256"]:
        raise HbaDeploymentError("ROLLBACK_BACKUP_SHA_MISMATCH")
    return journal, backup, pending_phases


def _validate_original_recovery_state(
    state_fd: int, original: bytes, before_container: dict[str, Any],
    cluster_before: dict[str, Any], manifest: dict[str, Any],
) -> str:
    entries, pending_phases = _inspect_recovery_entries(
        state_fd, before_container, cluster_before, manifest
    )
    if JOURNAL_NAME in entries:
        journal, backup, pending_phases = _validate_recovery_bundle(
            state_fd, before_container, cluster_before, manifest,
            RECOVERABLE_JOURNAL_PHASES, strict_pid=False,
        )
        suffix = "+PENDING" if pending_phases else ""
        return f"{journal['phase']}{suffix}"
    backup = None
    if BACKUP_NAME in entries:
        try:
            backup = _read_recovery_at(
                state_fd, BACKUP_NAME, mode=0o600, uid=70, gid=70
            )
        except HbaDeploymentError:
            backup = _read_recovery_at(
                state_fd, BACKUP_NAME, mode=0o600, uid=0, gid=0
            )
    if pending_phases:
        if (backup is None or _sha256(backup)
                != manifest["expectedOriginalSha256"]):
            raise HbaDeploymentError("ROLLBACK_BACKUP_SHA_MISMATCH")
        return f"PRE_JOURNAL_PENDING:{','.join(pending_phases)}"
    if backup is None:
        return "STATE_CREATED"
    if not original.startswith(backup):
        raise HbaDeploymentError("PRE_JOURNAL_BACKUP_NOT_ORIGINAL_PREFIX")
    if backup == original:
        return "PRE_JOURNAL_BACKUP_VERIFIED"
    return "PRE_JOURNAL_BACKUP_PARTIAL"


def _write_new(directory_fd: int, name: str, value: bytes, *,
               mode: int, uid: int, gid: int) -> None:
    fd = os.open(
        name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        mode, dir_fd=directory_fd,
    )
    try:
        offset = 0
        while offset < len(value):
            offset += os.write(fd, value[offset:])
        os.fchmod(fd, mode)
        os.fchown(fd, uid, gid)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.fsync(directory_fd)


def _replace_journal(state_fd: int, value: dict[str, Any]) -> None:
    rendered = (json.dumps(value, sort_keys=True, separators=(",", ":"))
                + "\n").encode("utf-8")
    temporary = f"journal.{secrets.token_hex(8)}.tmp"
    _write_new(state_fd, temporary, rendered, mode=0o600, uid=0, gid=0)
    os.rename(temporary, JOURNAL_NAME, src_dir_fd=state_fd,
              dst_dir_fd=state_fd)
    os.fsync(state_fd)


def _rename_exchange(directory_fd: int, first: str, second: str) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    renameat2 = getattr(libc, "renameat2", None)
    if renameat2 is None:
        raise HbaDeploymentError("RENAMEAT2_UNAVAILABLE")
    renameat2.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int,
                          ctypes.c_char_p, ctypes.c_uint]
    renameat2.restype = ctypes.c_int
    result = renameat2(
        directory_fd, first.encode("ascii"), directory_fd,
        second.encode("ascii"), RENAME_EXCHANGE,
    )
    if result != 0:
        error = ctypes.get_errno()
        raise HbaDeploymentError(f"RENAME_EXCHANGE_FAILED:{error}")


def _fsync_exchange_directory(directory_fd: int) -> None:
    os.fsync(directory_fd)


def _exchange_target(directory_fd: int, new_value: bytes,
                     target_metadata: os.stat_result,
                     expected_displaced_sha256: str) -> None:
    stage = f".obsidian-b64-hba-stage-{secrets.token_hex(12)}"
    _write_new(
        directory_fd, stage, new_value,
        mode=stat.S_IMODE(target_metadata.st_mode),
        uid=target_metadata.st_uid, gid=target_metadata.st_gid,
    )
    safe_to_unlink_stage = True
    try:
        _rename_exchange(directory_fd, stage, HBA_NAME)
        safe_to_unlink_stage = False
        try:
            _fsync_exchange_directory(directory_fd)
        except BaseException as fsync_exc:
            raise HbaDeploymentError(
                "POST_EXCHANGE_DIRECTORY_FSYNC_FAILED"
            ) from fsync_exc
        try:
            displaced, displaced_metadata = _read_at(directory_fd, stage)
            _validate_hba_metadata(displaced_metadata)
            displaced_matches = (
                _sha256(displaced) == expected_displaced_sha256
            )
        except BaseException:
            try:
                _rename_exchange(directory_fd, stage, HBA_NAME)
                _fsync_exchange_directory(directory_fd)
                safe_to_unlink_stage = True
            except BaseException as reverse_exc:
                safe_to_unlink_stage = False
                raise HbaDeploymentError(
                    "HBA_REVERSE_EXCHANGE_FAILED"
                ) from reverse_exc
            raise
        if not displaced_matches:
            try:
                _rename_exchange(directory_fd, stage, HBA_NAME)
                _fsync_exchange_directory(directory_fd)
                safe_to_unlink_stage = True
            except BaseException as reverse_exc:
                safe_to_unlink_stage = False
                raise HbaDeploymentError(
                    "CONCURRENT_HBA_EDIT_REVERSE_FAILED"
                ) from reverse_exc
            raise HbaDeploymentError("CONCURRENT_HBA_EDIT_PRESERVED")
        safe_to_unlink_stage = True
    finally:
        if safe_to_unlink_stage:
            try:
                os.unlink(stage, dir_fd=directory_fd)
                os.fsync(directory_fd)
            except FileNotFoundError:
                pass


def _stage_reports(directory_fd: int) -> list[dict[str, Any]]:
    reports = []
    for name in sorted(os.listdir(directory_fd)):
        if not STAGE_PATTERN.fullmatch(name):
            continue
        value, metadata = _read_at(directory_fd, name)
        _validate_hba_metadata(metadata)
        reports.append({"name": name, "sha256": _sha256(value)})
    return reports


def _remove_known_stages(
    directory_fd: int, reports: list[dict[str, Any]],
    manifest: dict[str, Any],
) -> None:
    known = {
        manifest["expectedOriginalSha256"],
        manifest["expectedDeployedSha256"],
    }
    if any(report["sha256"] not in known for report in reports):
        raise HbaDeploymentError("FOREIGN_HBA_STAGE_RETAINED")
    for report in reports:
        os.unlink(report["name"], dir_fd=directory_fd)
    if reports:
        os.fsync(directory_fd)


def _hba_parser_report(dsn: str) -> dict[str, Any]:
    import psycopg

    with psycopg.connect(dsn, connect_timeout=5) as conn, conn.cursor() as cur:
        cur.execute("SET LOCAL statement_timeout='10s'")
        cur.execute(
            "SELECT rule_number,type,database,user_name,address,netmask,"
            "auth_method,error FROM pg_hba_file_rules ORDER BY rule_number"
        )
        rows = cur.fetchall()
        digest = cur.execute(
            "SELECT encode(sha256(pg_read_binary_file("
            "current_setting('hba_file'))),'hex')"
        ).fetchone()[0]
    role_rows = [
        [row[0], row[1], row[2], row[3], row[4], row[5], row[6]]
        for row in rows if row[3] is not None and ROLE in row[3]
    ]
    return {
        "fileSha256": digest,
        "errors": [[row[0], row[7]] for row in rows if row[7] is not None],
        "roleRows": role_rows,
    }


def _reload(dsn: str, container: str, before_load_time: Any) -> dict[str, Any]:
    import psycopg

    started = dt.datetime.now(dt.timezone.utc).isoformat()
    with psycopg.connect(dsn, connect_timeout=5, autocommit=True) as conn:
        if conn.execute("SELECT pg_reload_conf()").fetchone()[0] is not True:
            raise HbaDeploymentError("PG_RELOAD_CONF_FALSE")
    load_time = None
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        with psycopg.connect(dsn, connect_timeout=5) as conn:
            load_time = conn.execute("SELECT pg_conf_load_time()").fetchone()[0]
        if load_time > before_load_time:
            break
        time.sleep(0.1)
    else:
        raise HbaDeploymentError("PG_CONF_LOAD_TIME_NOT_ADVANCED")
    logs = subprocess.run(
        ["docker", "logs", "--since", started, container],
        capture_output=True, text=True, check=False, timeout=10,
        env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")},
    )
    if logs.returncode != 0:
        raise HbaDeploymentError("POST_RELOAD_LOG_READ_FAILED")
    combined = (logs.stdout + "\n" + logs.stderr).lower()
    forbidden = (
        "pg_hba.conf was not reloaded", "invalid authentication method",
        "could not load pg_hba.conf", "error in file",
    )
    if any(item in combined for item in forbidden):
        raise HbaDeploymentError("POST_RELOAD_HBA_LOG_ERROR")
    return {"loadTimeAdvanced": True, "hbaLogErrors": False}


def _load_time(dsn: str) -> Any:
    import psycopg

    with psycopg.connect(dsn, connect_timeout=5) as conn:
        return conn.execute("SELECT pg_conf_load_time()").fetchone()[0]


def _post_recovery_rebind(
    *, container: str, expected_container_id: str, expected_image_id: str,
    require_healthy: bool, observation_dsn: str, admin_dsn: str,
    before_container: dict[str, Any], cluster_before: dict[str, Any],
    manifest: dict[str, Any], allow_contract_container: bool,
) -> None:
    rebound = _inspect_container(
        container, expected_container_id, expected_image_id,
        require_healthy, observation_dsn,
    )
    cluster_after = _cluster_identity(admin_dsn)
    _verify_cluster(
        cluster_after, manifest,
        allow_contract_container=allow_contract_container,
    )
    _catalog_preflight(observation_dsn, manifest["database"])
    role_after = inspect_role(admin_dsn)
    if (rebound != before_container or cluster_after != cluster_before
            or role_after.get("status") != "match"
            or role_after.get("loginState") != "DISABLED"
            or role_after.get("credentialState") != "ABSENT"
            or role_after.get("hbaIsolationStatus")
               != "MISSING_OR_DRIFTED"
            or role_after.get("hbaFileSha256")
               != manifest["expectedOriginalSha256"]):
        raise HbaDeploymentError("POST_RECOVERY_TARGET_REBIND_FAILED")


def _clean_state(directory_fd: int, state_fd: int) -> None:
    entries = os.listdir(state_fd)
    unexpected = [
        name for name in entries
        if name not in {JOURNAL_NAME, BACKUP_NAME}
        and not JOURNAL_TEMP_PATTERN.fullmatch(name)
    ]
    if unexpected:
        raise HbaDeploymentError("HBA_STATE_DIRECTORY_UNEXPECTED_ENTRY")
    for name in entries:
        os.unlink(name, dir_fd=state_fd)
    os.fsync(state_fd)
    os.close(state_fd)
    os.rmdir(STATE_DIRECTORY, dir_fd=directory_fd)
    os.fsync(directory_fd)


def _receipt_base(action: str) -> dict[str, Any]:
    return {
        "schemaVersion": "obsidian-b64-snapshot-reader-hba-deployment.v1",
        "action": action,
        "status": "FAILED",
        "customerRowsRead": False,
        "credentialReadOrIssued": False,
        "roleLoginChanged": False,
        "serviceRestarted": False,
        "rollbackAttempted": False,
        "rollbackVerified": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--postgres-env", default="EXCHANGE_DATABASE_URL")
    parser.add_argument("--admin-postgres-env", required=True)
    parser.add_argument("--container", required=True)
    parser.add_argument("--expected-container-id", required=True)
    parser.add_argument("--expected-image-id", required=True)
    parser.add_argument("--require-healthy", action="store_true")
    parser.add_argument("--allow-contract-container", action="store_true")
    operation = parser.add_mutually_exclusive_group()
    operation.add_argument("--apply", action="store_true")
    operation.add_argument("--rollback", action="store_true")
    operation.add_argument("--reconcile", action="store_true")
    args = parser.parse_args()
    action = (
        "ROLLBACK" if args.rollback else
        "RECONCILE" if args.reconcile else
        "APPLY" if args.apply else "PREFLIGHT"
    )
    result = _receipt_base(action)
    observation_dsn = os.environ.get(args.postgres_env)
    admin_input = os.environ.get(args.admin_postgres_env)
    if not observation_dsn or not admin_input:
        result["reason"] = "REQUIRED_POSTGRES_ENV_MISSING"
        print(json.dumps(result, sort_keys=True))
        return 2
    if args.allow_contract_container and not re.fullmatch(
            r"b64-hba-contract-[0-9]+", args.container):
        result["reason"] = "CONTRACT_CONTAINER_NAME_INVALID"
        print(json.dumps(result, sort_keys=True))
        return 2

    directory_fd: int | None = None
    state_fd: int | None = None
    passfile_fd: int | None = None
    mutation_attempted = False
    state_created = False
    before_container = None
    original: bytes | None = None
    original_metadata = None
    admin_dsn = admin_input
    manifest = None
    cluster_before = None
    try:
        _load_and_bind_plan()
        manifest = _load_manifest()
        before_container = _inspect_container(
            args.container, args.expected_container_id,
            args.expected_image_id, args.require_healthy, observation_dsn,
        )
        raw_container = _docker_inspect(args.container)
        if raw_container["Id"].removeprefix("sha256:") != args.expected_container_id:
            raise HbaDeploymentError("RAW_CONTAINER_IDENTITY_MISMATCH")
        pgdata = _bind_mount(
            raw_container, manifest,
            allow_contract_container=args.allow_contract_container,
        )
        _validate_container_admin_dsn(
            admin_input, manifest["database"], before_container["containerPid"]
        )
        passfile_fd, admin_dsn = _bind_empty_memfd_passfile(admin_input)
        admin_preflight = _admin_preflight(admin_dsn, manifest["database"])
        cluster_before = _cluster_identity(admin_dsn)
        _verify_cluster(
            cluster_before, manifest,
            allow_contract_container=args.allow_contract_container,
        )
        catalog = _catalog_preflight(observation_dsn, manifest["database"])
        role = inspect_role(admin_dsn)
        if (catalog["serverVersionNum"] // 10000 != 17
                or role.get("status") != "match"
                or role.get("loginState") != "DISABLED"
                or role.get("credentialState") != "ABSENT"):
            raise HbaDeploymentError("DORMANT_ROLE_PREFLIGHT_MISMATCH")
        directory_fd = _open_pgdata(pgdata)
        original, original_metadata = _read_at(directory_fd, HBA_NAME)
        _validate_hba_metadata(original_metadata)
        current_sha = _sha256(original)
        parser_report = _hba_parser_report(admin_dsn)
        result.update({
            "container": before_container,
            "cluster": {
                "systemIdentifier": cluster_before["systemIdentifier"],
                "postmasterStartTime": cluster_before["postmasterStartTime"].isoformat(),
                "serverVersionNum": cluster_before["serverVersionNum"],
            },
            "adminPreflight": admin_preflight,
            "preflight": {
                "hbaFileSha256": current_sha,
                "hbaFileMode": oct(stat.S_IMODE(original_metadata.st_mode)),
                "hbaFileUid": original_metadata.st_uid,
                "hbaFileGid": original_metadata.st_gid,
                "hbaFileSize": original_metadata.st_size,
                "hbaParserErrors": parser_report["errors"],
                "roleHbaRows": parser_report["roleRows"],
                "roleLoginState": role["loginState"],
                "credentialState": role["credentialState"],
            },
        })
        if parser_report["errors"]:
            raise HbaDeploymentError("PREEXISTING_HBA_PARSE_ERRORS")
        if not args.apply and not args.rollback and not args.reconcile:
            expected = manifest["expectedOriginalSha256"]
            if current_sha != expected or parser_report["roleRows"]:
                raise HbaDeploymentError("HBA_PREFLIGHT_NOT_UNAPPLIED")
            if os.path.exists(pgdata / STATE_DIRECTORY):
                raise HbaDeploymentError("HBA_STATE_DIRECTORY_ALREADY_EXISTS")
            result["status"] = "PREFLIGHT_PASS"
            print(json.dumps(result, sort_keys=True))
            return 0

        if args.reconcile:
            if current_sha not in {
                manifest["expectedOriginalSha256"],
                manifest["expectedDeployedSha256"],
            }:
                raise HbaDeploymentError("RECONCILE_CURRENT_SHA_UNKNOWN")
            state_fd = _open_state(directory_fd)
            stages = _stage_reports(directory_fd)
            known_stage_hashes = {
                manifest["expectedOriginalSha256"],
                manifest["expectedDeployedSha256"],
            }
            if any(stage["sha256"] not in known_stage_hashes
                   for stage in stages):
                raise HbaDeploymentError("RECONCILE_FOREIGN_STAGE_RETAINED")
            before_load = _load_time(admin_dsn)
            result["rollbackAttempted"] = True
            mutation_attempted = True
            if current_sha == manifest["expectedDeployedSha256"]:
                journal, backup, pending_phases = _validate_recovery_bundle(
                    state_fd, before_container, cluster_before, manifest,
                    RECOVERABLE_JOURNAL_PHASES, strict_pid=False,
                )
                recovered_journal_phase = journal["phase"]
                if pending_phases:
                    recovered_journal_phase += "+PENDING"
                journal["phase"] = "ROLLBACK_ATTEMPTED"
                _replace_journal(state_fd, journal)
                _exchange_target(
                    directory_fd, backup, original_metadata,
                    manifest["expectedDeployedSha256"],
                )
                reconciled_status = "RECONCILED_ROLLED_BACK"
            else:
                recovered_journal_phase = _validate_original_recovery_state(
                    state_fd, original, before_container, cluster_before,
                    manifest,
                )
                reconciled_status = "RECONCILED_ORIGINAL"
            reload_report = _reload(
                admin_dsn, args.container, before_load
            )
            restored, restored_metadata = _read_at(directory_fd, HBA_NAME)
            _validate_hba_metadata(restored_metadata)
            post = _hba_parser_report(admin_dsn)
            if (_sha256(restored) != manifest["expectedOriginalSha256"]
                    or post["errors"] or post["roleRows"]):
                raise HbaDeploymentError("RECONCILE_POSTVERIFY_FAILED")
            _post_recovery_rebind(
                container=args.container,
                expected_container_id=args.expected_container_id,
                expected_image_id=args.expected_image_id,
                require_healthy=args.require_healthy,
                observation_dsn=observation_dsn, admin_dsn=admin_dsn,
                before_container=before_container,
                cluster_before=cluster_before, manifest=manifest,
                allow_contract_container=args.allow_contract_container,
            )
            _remove_known_stages(directory_fd, stages, manifest)
            _clean_state(directory_fd, state_fd)
            state_fd = None
            result.update({
                "status": reconciled_status,
                "rollbackVerified": True,
                "reload": reload_report,
                "postHbaFileSha256": _sha256(restored),
                "recoveredJournalPhase": recovered_journal_phase,
            })
            print(json.dumps(result, sort_keys=True))
            return 0

        if args.rollback:
            if current_sha != manifest["expectedDeployedSha256"]:
                raise HbaDeploymentError("ROLLBACK_CURRENT_SHA_MISMATCH")
            state_fd = _open_state(directory_fd)
            journal, backup, _pending_phases = _validate_recovery_bundle(
                state_fd, before_container, cluster_before, manifest,
                frozenset({"DEPLOYED_VERIFIED"}), strict_pid=True,
            )
            before_load = _load_time(admin_dsn)
            result["rollbackAttempted"] = True
            journal["phase"] = "ROLLBACK_ATTEMPTED"
            _replace_journal(state_fd, journal)
            mutation_attempted = True
            _exchange_target(
                directory_fd, backup, original_metadata,
                manifest["expectedDeployedSha256"],
            )
            reload_report = _reload(admin_dsn, args.container, before_load)
            restored, restored_metadata = _read_at(directory_fd, HBA_NAME)
            _validate_hba_metadata(restored_metadata)
            post = _hba_parser_report(admin_dsn)
            if (_sha256(restored) != manifest["expectedOriginalSha256"]
                    or post["errors"] or post["roleRows"]):
                raise HbaDeploymentError("ROLLBACK_POSTVERIFY_FAILED")
            _post_recovery_rebind(
                container=args.container,
                expected_container_id=args.expected_container_id,
                expected_image_id=args.expected_image_id,
                require_healthy=args.require_healthy,
                observation_dsn=observation_dsn, admin_dsn=admin_dsn,
                before_container=before_container,
                cluster_before=cluster_before, manifest=manifest,
                allow_contract_container=args.allow_contract_container,
            )
            _clean_state(directory_fd, state_fd)
            state_fd = None
            result.update({"status": "ROLLED_BACK", "rollbackVerified": True,
                           "reload": reload_report,
                           "postHbaFileSha256": _sha256(restored)})
            print(json.dumps(result, sort_keys=True))
            return 0

        if current_sha != manifest["expectedOriginalSha256"]:
            raise HbaDeploymentError("ORIGINAL_HBA_SHA_MISMATCH")
        if (b"BEGIN OBSIDIAN_B64_SNAPSHOT_READER_HBA_V1" in original
                or b"END OBSIDIAN_B64_SNAPSHOT_READER_HBA_V1" in original):
            raise HbaDeploymentError("MANAGED_HBA_MARKER_ALREADY_PRESENT")
        if os.path.exists(pgdata / STATE_DIRECTORY):
            raise HbaDeploymentError("HBA_STATE_DIRECTORY_ALREADY_EXISTS")
        candidate = MANAGED_BLOCK + original
        if _sha256(candidate) != manifest["expectedDeployedSha256"]:
            raise HbaDeploymentError("DEPLOYED_HBA_SHA_MISMATCH")
        state_fd = _mkdir_state(directory_fd)
        state_created = True
        _write_new(
            state_fd, BACKUP_NAME, original, mode=0o600,
            uid=original_metadata.st_uid, gid=original_metadata.st_gid,
        )
        backup, _ = _read_at(state_fd, BACKUP_NAME)
        if _sha256(backup) != manifest["expectedOriginalSha256"]:
            raise HbaDeploymentError("BACKUP_VERIFY_FAILED")
        nonce = secrets.token_hex(16)
        journal = {
            "schemaVersion": "obsidian-b64-hba-journal.v1",
            "nonce": nonce, "phase": "BACKUP_VERIFIED",
            "containerId": before_container["containerId"],
            "containerImageId": before_container["imageId"],
            "containerPid": before_container["containerPid"],
            "systemIdentifier": cluster_before["systemIdentifier"],
            "originalSha256": manifest["expectedOriginalSha256"],
            "deployedSha256": manifest["expectedDeployedSha256"],
        }
        _replace_journal(state_fd, journal)
        before_load = _load_time(admin_dsn)
        journal["phase"] = "APPLY_ATTEMPTED"
        _replace_journal(state_fd, journal)
        mutation_attempted = True
        _exchange_target(
            directory_fd, candidate, original_metadata,
            manifest["expectedOriginalSha256"],
        )
        journal["phase"] = "CANDIDATE_INSTALLED"
        _replace_journal(state_fd, journal)
        installed, installed_metadata = _read_at(directory_fd, HBA_NAME)
        _validate_hba_metadata(installed_metadata)
        if _sha256(installed) != manifest["expectedDeployedSha256"]:
            raise HbaDeploymentError("POST_EXCHANGE_SHA_MISMATCH")
        parser_after = _hba_parser_report(admin_dsn)
        if parser_after["errors"]:
            raise HbaDeploymentError("CANDIDATE_HBA_PARSE_ERRORS")
        reload_report = _reload(admin_dsn, args.container, before_load)
        role_after = inspect_role(admin_dsn)
        rebound = _inspect_container(
            args.container, args.expected_container_id,
            args.expected_image_id, args.require_healthy, observation_dsn,
        )
        cluster_after = _cluster_identity(admin_dsn)
        _verify_cluster(
            cluster_after, manifest,
            allow_contract_container=args.allow_contract_container,
        )
        _catalog_preflight(observation_dsn, manifest["database"])
        if (rebound != before_container or cluster_after != cluster_before
                or role_after.get("status") != "match"
                or role_after.get("loginState") != "DISABLED"
                or role_after.get("credentialState") != "ABSENT"
                or role_after.get("hbaIsolationStatus") != "EXACT"
                or role_after.get("hbaFileSha256")
                   != manifest["expectedDeployedSha256"]):
            raise HbaDeploymentError("POST_DEPLOY_VERIFICATION_FAILED")
        journal["phase"] = "DEPLOYED_VERIFIED"
        journal["verifiedAt"] = dt.datetime.now(dt.timezone.utc).isoformat()
        _replace_journal(state_fd, journal)
        result.update({
            "status": "HBA_DEPLOYED_PARSED_DORMANT",
            "deploymentNonce": nonce,
            "postHbaFileSha256": manifest["expectedDeployedSha256"],
            "hbaIsolationStatus": role_after["hbaIsolationStatus"],
            "roleLoginState": role_after["loginState"],
            "credentialState": role_after["credentialState"],
            "activationStatus": role_after["activationStatus"],
            "activationBlockers": role_after["activationBlockers"],
            "reload": reload_report,
            "rollbackBackupRetained": True,
        })
        print(json.dumps(result, sort_keys=True))
        return 0
    except BaseException as exc:
        result["reason"] = _safe_reason(exc)
        if args.apply and state_created and manifest is not None:
            result["rollbackAttempted"] = True
            try:
                if (directory_fd is None or state_fd is None
                        or before_container is None or cluster_before is None
                        or original_metadata is None):
                    raise HbaDeploymentError("COMPENSATION_CONTEXT_MISSING")
                rebound = _inspect_container(
                    args.container, args.expected_container_id,
                    args.expected_image_id, args.require_healthy,
                    observation_dsn,
                )
                cluster_now = _cluster_identity(admin_dsn)
                if rebound != before_container or cluster_now != cluster_before:
                    raise HbaDeploymentError("COMPENSATION_TARGET_CHANGED")
                current, current_metadata = _read_at(directory_fd, HBA_NAME)
                current_sha = _sha256(current)
                stages = _stage_reports(directory_fd)
                if current_sha == manifest["expectedDeployedSha256"]:
                    journal, backup, pending_phases = \
                        _validate_recovery_bundle(
                            state_fd, before_container, cluster_before,
                            manifest, RECOVERABLE_JOURNAL_PHASES,
                            strict_pid=False,
                        )
                    compensation_recovery_phase = journal["phase"]
                    if pending_phases:
                        compensation_recovery_phase += "+PENDING"
                    before_load = _load_time(admin_dsn)
                    _exchange_target(
                        directory_fd, backup, current_metadata,
                        manifest["expectedDeployedSha256"],
                    )
                    reload_report = _reload(
                        admin_dsn, args.container, before_load
                    )
                elif current_sha == manifest["expectedOriginalSha256"]:
                    compensation_recovery_phase = \
                        _validate_original_recovery_state(
                            state_fd, original, before_container,
                            cluster_before, manifest,
                        )
                    before_load = _load_time(admin_dsn)
                    reload_report = _reload(
                        admin_dsn, args.container, before_load
                    )
                else:
                    raise HbaDeploymentError("COMPENSATION_FOREIGN_HBA_SHA")
                restored, restored_metadata = _read_at(directory_fd, HBA_NAME)
                _validate_hba_metadata(restored_metadata)
                parser_restored = _hba_parser_report(admin_dsn)
                if (_sha256(restored) != manifest["expectedOriginalSha256"]
                        or parser_restored["errors"]
                        or parser_restored["roleRows"]):
                    raise HbaDeploymentError("COMPENSATION_VERIFY_FAILED")
                _post_recovery_rebind(
                    container=args.container,
                    expected_container_id=args.expected_container_id,
                    expected_image_id=args.expected_image_id,
                    require_healthy=args.require_healthy,
                    observation_dsn=observation_dsn,
                    admin_dsn=admin_dsn,
                    before_container=before_container,
                    cluster_before=cluster_before, manifest=manifest,
                    allow_contract_container=args.allow_contract_container,
                )
                _remove_known_stages(directory_fd, stages, manifest)
                _clean_state(directory_fd, state_fd)
                state_fd = None
                result.update({"status": "FAILED_ROLLED_BACK",
                               "rollbackVerified": True,
                               "compensationReload": reload_report,
                               "compensationRecoveryPhase":
                                   compensation_recovery_phase})
            except BaseException:
                result["status"] = "ROLLBACK_UNCERTAIN"
        elif args.rollback and mutation_attempted:
            result["status"] = "ROLLBACK_UNCERTAIN"
        elif args.reconcile:
            result["status"] = "ROLLBACK_UNCERTAIN"
        elif result["status"] == "FAILED":
            result["status"] = "PRECHECK_FAILED_NO_MUTATION"
        print(json.dumps(result, sort_keys=True))
        return 2
    finally:
        for fd in (state_fd, directory_fd, passfile_fd):
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass


if __name__ == "__main__":
    raise SystemExit(main())
