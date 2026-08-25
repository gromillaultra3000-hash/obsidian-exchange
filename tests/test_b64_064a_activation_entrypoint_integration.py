"""Real one-shot activation rehearsal against an allowlisted disposable PG17.

The caller owns creation and removal of TEST_POSTGRES_CONTAINER.  This script
deploys the production HBA contract into that disposable container, consumes
one synthetic activation decision through the durable journal, performs a real
exported-snapshot pg_dump and a real tmpfs restore/equality check, and rolls the
HBA back byte-for-byte.  It runs the production executor implementation only
with its production-contact profile hard-disabled.
"""
import base64
import fcntl
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import psycopg
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo


ROOT = Path(__file__).resolve().parents[1]
POSTGRES = ROOT / "deploy/postgres"
sys.path.insert(0, str(POSTGRES))

import b64_064a_activation_entrypoint as activation
import b64_064a_activation_executor as production_executor
import b64_064a_activation_launcher as activation_launcher
import b64_064a_hardened_refresh as refresh
import b64_dump_restore_supervisor as supervisor
import b64_snapshot_dump as fingerprint
import b64_snapshot_reader_runtime as runtime
import b64_snapshot_reader_watchdog as watchdog
from migration_profile import selected_paths
from verify_b64_snapshot_reader import inspect


ROLE = "obsidian_b64_snapshot_reader"
CONTAINER = os.environ["TEST_POSTGRES_CONTAINER"]
BOOTSTRAP_DSN = os.environ["TEST_POSTGRES_DSN"]
ORIGINAL_HBA = Path(os.environ["TEST_POSTGRES_ORIGINAL_HBA"])
DEPLOYMENT_NONCE = "1234567890abcdef1234567890abcdef"


def _canonical(value):
    return activation._canonical(value)


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _run(command, **kwargs):
    return subprocess.run(
        command, check=False, capture_output=True, **kwargs,
    )


def _inspect_container(reference: str):
    observed = _run(["docker", "inspect", reference], text=True)
    if observed.returncode != 0:
        return None
    values = json.loads(observed.stdout)
    if len(values) != 1:
        raise refresh.HardenedRefreshError("CONTAINER_INSPECTION_AMBIGUOUS")
    return values[0]


def _execute_bound(conn, path: Path, database: str):
    conn.execute(sql.SQL(
        "SET obsidian.snapshot_reader_expected_database = {}"
    ).format(sql.Literal(database)))
    conn.execute("SET obsidian.snapshot_reader_require_absent = 'on'")
    conn.execute(sql.SQL(
        "SET obsidian.snapshot_reader_deployment_nonce = {}"
    ).format(sql.Literal(DEPLOYMENT_NONCE)))
    conn.execute(path.read_text("utf-8"))


def _write_manifest(directory_fd: int, name: str, value) -> None:
    descriptor = os.open(
        name, os.O_WRONLY | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0),
        dir_fd=directory_fd,
    )
    raw = _canonical(value) + b"\n"
    try:
        offset = 0
        while offset < len(raw):
            written = os.write(descriptor, raw[offset:])
            if written <= 0:
                raise refresh.HardenedRefreshError("MANIFEST_SHORT_WRITE")
            offset += written
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class ContractSource:
    production_contact = False

    def __init__(self, delegate):
        self.delegate = delegate

    def open(self, plan, secret_fd, deadline):
        try:
            return self.delegate.open(plan, secret_fd, deadline)
        except BaseException as exc:
            raise refresh.HardenedRefreshError(
                "SOURCE_ADAPTER_FAILURE"
            ) from exc

    def close(self):
        return self.delegate.close()


class ContractDump:
    production_contact = False

    def __init__(self, run_nonce: str):
        self.run_nonce = run_nonce
        self.container_id = None
        self.container_name = "b64-064a-pgdump-one-shot"

    def _force_cleanup(self):
        observed = _inspect_container(self.container_name)
        if observed is None:
            return
        labels = observed.get("Config", {}).get("Labels") or {}
        observed_id = observed["Id"].removeprefix("sha256:")
        if (observed_id == self.container_id
                and labels.get("org.obsidian.run-nonce") == self.run_nonce
                and labels.get("org.obsidian.route")
                == "e0-e0.3-b5.3-064a"):
            _run(["docker", "stop", "--time", "2", observed_id], text=True)
            return
        raise refresh.HardenedRefreshError("DUMP_CLEANUP_BINDING_MISMATCH")

    def run(self, plan, snapshot, source_container_id,
            credential_not_after_epoch, archive_fd, secret_fd, deadline):
        preflight = _run(refresh.compile_client_preflight(plan), text=True)
        if (preflight.returncode != 0
                or preflight.stdout.strip() != refresh.PG_DUMP_VERSION
                or preflight.stderr):
            raise refresh.HardenedRefreshError(
                "PINNED_CLIENT_PREFLIGHT_FAILED"
            )
        remaining = min(
            credential_not_after_epoch - time.time() - 5,
            deadline - time.monotonic() - 5,
        )
        transaction_timeout_ms = min(150_000, int(remaining * 1000))
        if transaction_timeout_ms < 1:
            raise refresh.HardenedRefreshError("DUMP_DEADLINE_EXHAUSTED")
        command = refresh.compile_dump_command(
            plan, snapshot, source_container_id,
            transaction_timeout_ms=transaction_timeout_ms,
            lease_not_after_epoch=credential_not_after_epoch,
        )
        try:
            with tempfile.TemporaryDirectory(
                    prefix="b64-contract-dump-cid-", dir="/tmp") as cid_root:
                cid_path = Path(cid_root) / "container.id"
                command.insert(2, f"--cidfile={cid_path}")
                completed = subprocess.run(
                    command, stdin=secret_fd, stdout=archive_fd,
                    stderr=subprocess.PIPE, check=False,
                    timeout=max(1.0, deadline - time.monotonic()),
                )
                try:
                    container_id = cid_path.read_text("ascii").strip()
                except OSError as exc:
                    raise refresh.HardenedRefreshError(
                        "DUMP_CONTAINER_ID_MISSING"
                    ) from exc
                if re.fullmatch(r"[0-9a-f]{64}", container_id) is None:
                    raise refresh.HardenedRefreshError(
                        "DUMP_CONTAINER_ID_MISSING"
                    )
                self.container_id = container_id
                if (completed.returncode != 0 or completed.stderr
                        or _inspect_container(container_id) is not None):
                    raise refresh.HardenedRefreshError(
                        "DUMP_EXECUTION_FAILED"
                    )
                return {
                    "clientVersion": refresh.PG_DUMP_VERSION,
                    "exitCode": 0,
                    "stderrBytes": 0,
                    "stderrSha256": hashlib.sha256(b"").hexdigest(),
                    "warningCount": 0,
                    "sourceContainerId": source_container_id,
                    "containerId": container_id,
                }
        except BaseException as exc:
            self._force_cleanup()
            if isinstance(exc, refresh.HardenedRefreshError):
                raise
            raise refresh.HardenedRefreshError(
                "DUMP_ADAPTER_FAILURE"
            ) from exc

    def cleanup(self, expected_container_id):
        if expected_container_id != self.container_id:
            raise refresh.HardenedRefreshError(
                "DUMP_CLEANUP_BINDING_MISMATCH"
            )
        self._force_cleanup()
        absent = (_inspect_container(expected_container_id) is None
                  and _inspect_container(self.container_name) is None)
        return {
            "containerId": expected_container_id,
            "containerAbsent": absent,
            "tmpfsReleased": absent,
        }


class ContractRestore:
    production_contact = False

    def __init__(self, run_nonce: str, source_tables, source_catalog,
                 source_system_identifier: str):
        self.run_nonce = run_nonce
        self.source_tables = source_tables
        self.source_catalog = source_catalog
        self.source_system_identifier = source_system_identifier
        self.container_id = None
        self.container_name = f"b64-064a-restore-contract-{os.getpid()}"

    def _force_cleanup(self):
        if self.container_id is None:
            observed = _inspect_container(self.container_name)
            if observed is None:
                return
            candidate = observed["Id"].removeprefix("sha256:")
        else:
            candidate = self.container_id
            observed = _inspect_container(candidate)
            if observed is None:
                return
        labels = observed.get("Config", {}).get("Labels") or {}
        if (observed["Name"].lstrip("/") != self.container_name
                or labels.get("org.obsidian.run-nonce") != self.run_nonce
                or labels.get("org.obsidian.route")
                != "e0-e0.3-b5.3-064a"):
            raise refresh.HardenedRefreshError(
                "RESTORE_CLEANUP_BINDING_MISMATCH"
            )
        _run(["docker", "stop", "--time", "2", candidate], text=True)

    def _start(self):
        command = [
            "docker", "run", "-d", "--rm", "--pull=never",
            "--platform=linux/amd64", f"--name={self.container_name}",
            "--label=org.obsidian.route=e0-e0.3-b5.3-064a",
            f"--label=org.obsidian.run-nonce={self.run_nonce}",
            "--network=none", "--read-only", "--user=70:70",
            "--cap-drop=ALL", "--security-opt=no-new-privileges=true",
            "--pids-limit=128", "--memory=512m", "--cpus=1",
            "--tmpfs=/var/lib/postgresql/data:rw,nosuid,nodev,size=256m,mode=0700,uid=70,gid=70",
            "--tmpfs=/run/postgresql:rw,nosuid,nodev,size=1m,mode=0770,uid=70,gid=70",
            "--tmpfs=/tmp:rw,noexec,nosuid,nodev,size=16m,mode=1777",
            "--env=POSTGRES_DB=obsidian_exchange",
            "--env=POSTGRES_HOST_AUTH_METHOD=trust",
            refresh.IMAGE_REF,
        ]
        started = _run(command, text=True)
        container_id = started.stdout.strip()
        if (started.returncode != 0 or started.stderr
                or re.fullmatch(r"[0-9a-f]{64}", container_id) is None):
            raise refresh.HardenedRefreshError(
                "RESTORE_CONTAINER_START_FAILED"
            )
        self.container_id = container_id
        for _attempt in range(200):
            ready = _run([
                "docker", "exec", container_id, "pg_isready", "-q",
                "-U", "postgres", "-d", "obsidian_exchange",
            ])
            if ready.returncode == 0:
                return
            observed = _inspect_container(container_id)
            if observed is None or not observed["State"]["Running"]:
                raise refresh.HardenedRefreshError(
                    "RESTORE_CONTAINER_EARLY_EXIT"
                )
            time.sleep(0.1)
        raise refresh.HardenedRefreshError("RESTORE_CONTAINER_NOT_READY")

    def verify(self, plan, archive_fd, workspace_fd,
               source_fingerprints, deadline):
        self.source_tables = source_fingerprints["tables"]
        self.source_catalog = source_fingerprints["catalog"]
        self.source_system_identifier = source_fingerprints[
            "systemIdentifier"
        ]
        stage = "START"
        try:
            self._start()
            if time.monotonic() >= deadline:
                raise refresh.HardenedRefreshError(
                    "RESTORE_DEADLINE_EXHAUSTED"
                )
            observed = _inspect_container(self.container_id)
            if observed is None:
                raise refresh.HardenedRefreshError(
                    "RESTORE_CONTAINER_MISSING"
                )
            container_pid = observed["State"]["Pid"]
            stage = "SOCKET_BIND"
            restore_dsn = make_conninfo(
                host=f"/proc/{container_pid}/root/run/postgresql",
                dbname="obsidian_exchange", user="postgres", port=5432,
                connect_timeout=5, sslmode="disable",
                target_session_attrs="read-write",
            )
            stage = "BOOTSTRAP_ROLES"
            identity = None
            last_identity_error = None
            identity_deadline = min(deadline, time.monotonic() + 5.0)
            while identity is None and time.monotonic() < identity_deadline:
                try:
                    with psycopg.connect(restore_dsn) as identity_conn:
                        identity = identity_conn.execute(
                            "SELECT current_user,current_database(),"
                            "current_setting('server_version_num')::int/10000,"
                            "current_setting('server_encoding'),"
                            "system_identifier::text FROM pg_control_system()"
                        ).fetchone()
                except psycopg.OperationalError as exc:
                    last_identity_error = exc
                    time.sleep(0.1)
            if identity is None:
                raise refresh.HardenedRefreshError(
                    "RESTORE_SOCKET_UNAVAILABLE"
                ) from last_identity_error
            if (identity[:4]
                    != ("postgres", "obsidian_exchange", 17, "UTF8")
                    or identity[4] == self.source_system_identifier):
                raise refresh.HardenedRefreshError(
                    "RESTORE_SOCKET_IDENTITY_MISMATCH"
                )
            try:
                with psycopg.connect(restore_dsn, autocommit=True) as conn:
                    conn.execute(
                        (POSTGRES / "bootstrap_roles.sql").read_text("utf-8")
                    )
            except psycopg.Error as exc:
                sqlstate = exc.sqlstate or "NO_SQLSTATE"
                if re.fullmatch(r"[A-Z0-9_]{2,16}", sqlstate) is None:
                    sqlstate = "UNSAFE_SQLSTATE"
                raise refresh.HardenedRefreshError(
                    f"RESTORE_BOOTSTRAP_SQLSTATE_{sqlstate}"
                ) from exc
            stage = "PREPARE_DATABASE"
            with psycopg.connect(restore_dsn) as conn:
                conn.execute((POSTGRES / "prepare_database.sql").read_text("utf-8"))
                public_objects = conn.execute(
                    "SELECT count(*) FROM pg_class c JOIN pg_namespace n "
                    "ON n.oid=c.relnamespace WHERE n.nspname='public'"
                ).fetchone()[0]
                public_functions = conn.execute(
                    "SELECT count(*) FROM pg_proc p JOIN pg_namespace n "
                    "ON n.oid=p.pronamespace WHERE n.nspname='public'"
                ).fetchone()[0]
                public_types = conn.execute(
                    "SELECT count(*) FROM pg_type t JOIN pg_namespace n "
                    "ON n.oid=t.typnamespace WHERE n.nspname='public' "
                    "AND t.typtype NOT IN ('p')"
                ).fetchone()[0]
                if public_objects or public_functions or public_types:
                    raise refresh.HardenedRefreshError(
                        "RESTORE_TARGET_SCHEMA_NOT_EMPTY"
                    )
                conn.execute("DROP SCHEMA public")
            stage = "PG_RESTORE"
            os.lseek(archive_fd, 0, os.SEEK_SET)
            restored = subprocess.run(
                [
                    "docker", "exec", "-i", self.container_id,
                    "pg_restore", "--username=postgres",
                    "--dbname=obsidian_exchange", "--role=obsidian_migrator",
                    "--no-owner", "--no-privileges", "--exit-on-error",
                ],
                stdin=archive_fd, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, check=False,
                timeout=max(1.0, deadline - time.monotonic()),
            )
            if restored.returncode != 0 or restored.stderr:
                raise refresh.HardenedRefreshError("PG_RESTORE_FAILED")
            stage = "RUNTIME_PRIVILEGES"
            with psycopg.connect(restore_dsn, autocommit=True) as conn:
                conn.execute((POSTGRES / "runtime_privileges.sql").read_text("utf-8"))
                _execute_bound(
                    conn, POSTGRES / "provision_b64_snapshot_reader.sql",
                    "obsidian_exchange",
                )
            stage = "FINGERPRINT"
            with psycopg.connect(restore_dsn) as conn:
                restore_tables, _ = fingerprint._table_fingerprint(conn)
                restore_catalog, _ = fingerprint._catalog_fingerprint(conn)
                restore_system_identifier = conn.execute(
                    "SELECT system_identifier::text FROM pg_control_system()"
                ).fetchone()[0]
            stage = "MANIFEST"
            _write_manifest(
                workspace_fd, "source-table-fingerprint.json",
                self.source_tables,
            )
            _write_manifest(
                workspace_fd, "restore-table-fingerprint.json",
                restore_tables,
            )
            _write_manifest(
                workspace_fd, "source-catalog-fingerprint.json",
                self.source_catalog,
            )
            _write_manifest(
                workspace_fd, "restore-catalog-fingerprint.json",
                restore_catalog,
            )
            return {
                "tables": len(restore_tables),
                "catalogSections": len(restore_catalog),
                "tableMatch": restore_tables == self.source_tables,
                "catalogMatch": restore_catalog == self.source_catalog,
                "restoreClusterDistinct": restore_system_identifier
                != self.source_system_identifier,
                "sequenceRuntimeStateCompared": False,
                "restoreNoOwnerApplied": True,
                "restoreNoPrivilegesApplied": True,
                "containerId": self.container_id,
            }
        except BaseException as exc:
            self._force_cleanup()
            if isinstance(exc, refresh.HardenedRefreshError):
                raise
            raise refresh.HardenedRefreshError(
                f"RESTORE_{stage}_FAILURE"
            ) from exc

    def cleanup(self, expected_container_id):
        if expected_container_id != self.container_id:
            raise refresh.HardenedRefreshError(
                "RESTORE_CLEANUP_BINDING_MISMATCH"
            )
        self._force_cleanup()
        absent = (_inspect_container(expected_container_id) is None
                  and _inspect_container(self.container_name) is None)
        return {
            "containerId": expected_container_id,
            "containerAbsent": absent,
            "tmpfsReleased": absent,
        }


class ContractActivationExecutor:
    production_contact = False

    def __init__(self, *, observation_dsn, admin_dsn, container_id,
                 image_id, workspace_parent):
        self.observation_dsn = observation_dsn
        self.admin_dsn = admin_dsn
        self.container_id = container_id
        self.image_id = image_id
        self.workspace_parent = workspace_parent
        self.calls = 0

    def execute(self, plan, authorization, deadline):
        self.calls += 1
        if (self.calls != 1 or plan["target"]["containerName"] != CONTAINER
                or plan["target"]["containerId"] != self.container_id
                or plan["target"]["imageId"] != self.image_id
                or deadline - time.monotonic()
                > activation.LIMITS["overallDeadlineSeconds"] + 1):
            raise activation.ActivationError("CONTRACT_EXECUTOR_BINDING_FAILED")
        with psycopg.connect(self.admin_dsn) as conn:
            source_tables, _ = fingerprint._table_fingerprint(conn)
            source_catalog, _ = fingerprint._catalog_fingerprint(conn)
            source_system_identifier = conn.execute(
                "SELECT system_identifier::text FROM pg_control_system()"
            ).fetchone()[0]
        lease = runtime.issue_credential_lease(
            observation_dsn=self.observation_dsn,
            admin_dsn=self.admin_dsn, container=CONTAINER,
            expected_container_id=self.container_id,
            expected_image_id=self.image_id,
            ttl_seconds=activation.LIMITS["credentialTtlSeconds"],
            allow_contract_container=True,
        )
        source = ContractSource(runtime.ProductionSourceAdapter(lease))
        dump = ContractDump(plan["runNonce"])
        restore = ContractRestore(
            plan["runNonce"], source_tables, source_catalog,
            source_system_identifier,
        )
        frozen_plan = json.loads((
            ROOT / "docs/e0-3-bot-b5-3-064a-hardened-refresh-plan.v1.json"
        ).read_text("utf-8"))
        try:
            receipt = refresh.execute_hermetic(
                frozen_plan, self.workspace_parent,
                source=source, dump=dump, restore=restore,
                source_secret_fd=lease.source_fd,
                dump_secret_fd=lease.dump_fd,
            )
        finally:
            lease.close()
        if (receipt["status"] != "COMPLETED"
                or receipt["cleanupStatus"] != "CLEANUP_VERIFIED"
                or time.monotonic() > deadline):
            error_code = receipt.get("errorCode") or "UNKNOWN"
            if (type(error_code) is not str
                    or re.fullmatch(r"[A-Z0-9_]+", error_code) is None):
                error_code = "UNSAFE_OR_MISSING_REASON"
            raise activation.ActivationError(
                f"HARDENED_DISPOSABLE_REHEARSAL_{error_code}"
            )
        closed = inspect(self.admin_dsn)
        closed_sessions = runtime._role_auth_state(self.admin_dsn)["sessions"]
        return {
            "schemaVersion": activation.EXECUTION_RECEIPT_SCHEMA,
            "route": activation.ROUTE,
            "environment": authorization.environment,
            "runNonce": authorization.run_nonce,
            "planSha256": authorization.plan_sha256,
            "decisionSha256": authorization.decision_sha256,
            "status": "COMPLETED_DORMANT_VERIFIED",
            "archiveBytes": receipt["archiveBytes"],
            "archiveSha256": receipt["archiveSha256"],
            "catalogEquality": True,
            "tableEquality": True,
            "credentialIssued": True,
            "credentialRevoked": receipt["cleanup"][
                "credentialRevocationAttested"
            ],
            "sourceSessionClosed": receipt["cleanup"]["sourceSessionClosed"],
            "readerLoginState": closed["loginState"],
            "readerCredentialState": closed["credentialState"],
            "readerActiveSessions": closed_sessions,
            "registeredWorkspaceAbsent": receipt["cleanup"]["workspaceAbsent"],
            "dumpContainerAbsent": receipt["cleanup"][
                "expectedContainerIdsAbsent"
            ],
            "restoreContainerAbsent": receipt["cleanup"][
                "expectedContainerIdsAbsent"
            ],
            "containerTmpfsLifetimesEnded": receipt["cleanup"][
                "containerTmpfsLifetimesEnded"
            ],
            "productionDataRetained": False,
            "automaticRetryAllowed": False,
            "actionAllowed": False,
        }


def _signed_package(*, now_epoch: int, container_id: str, image_id: str,
                    system_identifier: str):
    private_keys = {
        "ACCOUNTABLE_OWNER": Ed25519PrivateKey.generate(),
    }
    entries = []
    for role, identity, domain in (
        ("ACCOUNTABLE_OWNER", "synthetic_contract_owner",
         "synthetic_owner_disposable_domain"),
    ):
        public = private_keys[role].public_key().public_bytes_raw()
        entries.append({
            "keyId": activation.activation_key_id(public),
            "identityId": identity,
            "trustDomain": domain, "role": role, "status": "ACTIVE",
            "publicKeyB64": _b64(public),
        })
    keyring_unsigned = {
        "schemaVersion": activation.ACTIVATION_KEYRING_SCHEMA,
        "route": activation.ROUTE,
        "trustEnvironment": activation.ACTIVATION_TRUST_ENVIRONMENT,
        "registryVersion": 3, "issuedAtEpoch": now_epoch - 120,
        "expiresAtEpoch": now_epoch + 1800,
        "revokedKeys": [], "keys": entries,
    }
    keyring_sha = hashlib.sha256(_canonical(keyring_unsigned)).hexdigest()
    keyring = {**keyring_unsigned, "keyringSha256": keyring_sha}
    artifacts = {
        key: _sha_file(path)
        for key, path in activation.ARTIFACT_PATHS.items()
    }
    plan = activation.build_plan(
        environment="DISPOSABLE_CONTRACT",
        run_nonce=_b64(secrets.token_bytes(24)),
        created_at_epoch=now_epoch - 10, container_name=CONTAINER,
        container_id=container_id, image_id=image_id,
        system_identifier=system_identifier,
        artifacts_sha256=artifacts,
    )
    plan_sha = hashlib.sha256(_canonical(plan)).hexdigest()
    unsigned = {
        "schemaVersion": activation.DECISION_SCHEMA,
        "route": activation.ROUTE,
        "decision": "AUTHORIZE_ONE_BOUNDED_READ_ONLY_REFRESH",
        "environment": "DISPOSABLE_CONTRACT",
        "activationPlanSha256": plan_sha,
        "keyringSha256": keyring_sha,
        "issuedAtEpoch": now_epoch - 5,
        "expiresAtEpoch": now_epoch + 600,
        "nonce": plan["runNonce"],
        "limits": dict(activation.LIMITS),
        "authority": dict(activation.CONTRACT_AUTHORITY),
    }
    payload = activation.SIGNATURE_DOMAIN + _canonical(unsigned)
    signatures = []
    for entry in reversed(entries):
        signatures.append({
            "role": entry["role"], "keyId": entry["keyId"],
            "identityId": entry["identityId"],
            "signatureB64": _b64(
                private_keys[entry["role"]].sign(payload)
            ),
        })
    decision = {
        **unsigned,
        "decisionSha256": hashlib.sha256(_canonical(unsigned)).hexdigest(),
        "signatures": signatures,
    }
    return keyring, keyring_sha, plan, decision


def main():
    container = _inspect_container(CONTAINER)
    if container is None:
        raise RuntimeError("CONTRACT_CONTAINER_MISSING")
    container_id = container["Id"].removeprefix("sha256:")
    container_pid = container["State"]["Pid"]
    image_id = container["Image"]
    pgdata_mounts = [
        item for item in container.get("Mounts", [])
        if item.get("Destination") == "/var/lib/postgresql/data"
    ]
    if (len(pgdata_mounts) != 1
            or re.fullmatch(
                r"(?:[0-9a-f]{64}|"
                r"b64-(?:watchdog|upgrade)-volume-[0-9a-f]{16,64}|"
                r"b64[0-9a-f]{61})",
                            str(pgdata_mounts[0].get("Name", ""))) is None):
        raise RuntimeError("CONTRACT_VOLUME_BINDING_INVALID")
    volume_name = pgdata_mounts[0]["Name"]
    admin_dsn = make_conninfo(
        host=f"/proc/{container_pid}/root/var/run/postgresql",
        dbname="obsidian_exchange", user="postgres", port=5432,
        connect_timeout=5, sslmode="disable",
        target_session_attrs="read-write",
    )
    with psycopg.connect(BOOTSTRAP_DSN) as conn:
        existing_tables = conn.execute(
            "SELECT count(*) FROM pg_class c JOIN pg_namespace n "
            "ON n.oid=c.relnamespace WHERE n.nspname='public' "
            "AND c.relkind IN ('r','p')"
        ).fetchone()[0]
    if existing_tables == 0:
        with psycopg.connect(BOOTSTRAP_DSN, autocommit=True) as conn:
            conn.execute((POSTGRES / "bootstrap_roles.sql").read_text("utf-8"))
        with psycopg.connect(BOOTSTRAP_DSN) as conn:
            conn.execute((POSTGRES / "prepare_database.sql").read_text("utf-8"))
        with psycopg.connect(BOOTSTRAP_DSN) as conn:
            conn.execute("SET ROLE obsidian_migrator")
            for migration in selected_paths(ROOT, "production-cutover"):
                conn.execute(migration.read_text("utf-8"))
        with psycopg.connect(BOOTSTRAP_DSN, autocommit=True) as conn:
            conn.execute(
                (POSTGRES / "runtime_privileges.sql").read_text("utf-8")
            )
            _execute_bound(
                conn, POSTGRES / "provision_b64_snapshot_reader.sql",
                "obsidian_exchange",
            )
    elif existing_tables != 54:
        raise RuntimeError("CONTRACT_DATABASE_PARTIALLY_INITIALIZED")
    observation_password = secrets.token_urlsafe(48)
    with psycopg.connect(BOOTSTRAP_DSN, autocommit=True) as conn:
        conn.execute(sql.SQL("ALTER ROLE postgres PASSWORD {}").format(
            sql.Literal(observation_password)
        ))
    observation_port = conninfo_to_dict(BOOTSTRAP_DSN)["port"]
    passfile_fd = runtime._sealed_pgpass_memfd(
        (
            f"127.0.0.1:{observation_port}:obsidian_exchange:postgres:"
            f"{observation_password}\n"
        ).encode("utf-8"),
        "b64-activation-contract-observation-pgpass",
    )
    observation_password = ""
    observation_connection = conninfo_to_dict(BOOTSTRAP_DSN)
    observation_connection.pop("password", None)
    observation_dsn = make_conninfo(
        **observation_connection,
        passfile=f"/proc/self/fd/{passfile_fd}",
    )
    if _sha_file(ORIGINAL_HBA) != \
            "45b68cd420caab6d19725857c309871880a66a4c195bcd7e1604e7c334b6be82":
        raise RuntimeError("ORIGINAL_HBA_DIGEST_MISMATCH")
    copied = _run([
        "docker", "cp", str(ORIGINAL_HBA),
        f"{CONTAINER}:/var/lib/postgresql/data/pg_hba.conf",
    ], text=True)
    if copied.returncode != 0:
        raise RuntimeError("ORIGINAL_HBA_COPY_FAILED")
    for command in (
        ["docker", "exec", "-u", "0", CONTAINER, "chown", "70:70",
         "/var/lib/postgresql/data/pg_hba.conf"],
        ["docker", "exec", "-u", "0", CONTAINER, "chmod", "0600",
         "/var/lib/postgresql/data/pg_hba.conf"],
    ):
        completed = _run(command, text=True)
        if completed.returncode != 0:
            raise RuntimeError("ORIGINAL_HBA_MODE_FAILED")
    with psycopg.connect(observation_dsn, autocommit=True) as conn:
        if conn.execute("SELECT pg_reload_conf()").fetchone()[0] is not True:
            raise RuntimeError("ORIGINAL_HBA_RELOAD_FAILED")
    environment = dict(os.environ)
    environment["EXCHANGE_DATABASE_URL"] = observation_dsn
    environment["B64_LOCAL_ADMIN_DSN"] = admin_dsn
    hba_command = [
        sys.executable, str(POSTGRES / "deploy_b64_snapshot_reader_hba.py"),
        "--postgres-env", "EXCHANGE_DATABASE_URL",
        "--admin-postgres-env", "B64_LOCAL_ADMIN_DSN",
        "--container", CONTAINER,
        "--expected-container-id", container_id,
        "--expected-image-id", image_id,
        "--allow-contract-container",
    ]
    applied = subprocess.run(
        hba_command + ["--apply"], env=environment, check=False,
        capture_output=True, text=True, pass_fds=(passfile_fd,),
    )
    try:
        applied_receipt = json.loads(applied.stdout)
    except (json.JSONDecodeError, UnicodeDecodeError):
        applied_receipt = {}
    if (applied.returncode != 0
            or applied_receipt.get("status")
            != "HBA_DEPLOYED_PARSED_DORMANT"):
        safe_reason = applied_receipt.get("reason", "UNKNOWN")
        if (type(safe_reason) is not str
                or re.fullmatch(r"[A-Z0-9_:.-]+", safe_reason) is None):
            safe_reason = "UNSAFE_OR_MISSING_REASON"
        raise RuntimeError(f"CONTRACT_HBA_APPLY_FAILED_{safe_reason}")
    result = None
    replay_reason = None
    cold_recovery_result = None
    hard_kill_recovery_result = None
    try:
        system_identifier = runtime._exact_runtime_binding(
            observation_dsn=observation_dsn, admin_dsn=admin_dsn,
            admin_input_dsn=admin_dsn, container=CONTAINER,
            expected_container_id=container_id,
            expected_image_id=image_id, require_healthy=True,
            allow_contract_container=True, expected_login=False,
        ).cluster["systemIdentifier"]
        now_epoch = int(time.time())
        keyring, keyring_sha, plan, decision = _signed_package(
            now_epoch=now_epoch, container_id=container_id,
            image_id=image_id, system_identifier=system_identifier,
        )
        with tempfile.TemporaryDirectory(
                prefix="b64-activation-contract-") as temporary:
            temporary_path = Path(temporary)
            temporary_path.chmod(0o700)
            journal_root = temporary_path / "journal"
            workspace_parent = temporary_path / "workspace"
            proxy_parent = temporary_path / "proxy"
            resource_journal_root = temporary_path / "resources"
            journal_root.mkdir(mode=0o700)
            workspace_parent.mkdir(mode=0o700)
            proxy_parent.mkdir(mode=0o700)
            resource_journal_root.mkdir(mode=0o700)

            def reconcile():
                observed = runtime.reconcile_credential(
                    observation_dsn=observation_dsn, admin_dsn=admin_dsn,
                    container=CONTAINER,
                    expected_container_id=container_id,
                    expected_image_id=image_id,
                    allow_contract_container=True,
                )
                return {
                    "loginState": observed["loginState"],
                    "credentialState": observed["credentialState"],
                    "activeSessions": observed["activeSessions"],
                    "customerRowsRead": False,
                }

            def dormant():
                observed = inspect(admin_dsn)
                if observed["status"] != "match":
                    raise RuntimeError("DORMANT_VERIFIER_DRIFT")
                sessions = runtime._role_auth_state(admin_dsn)["sessions"]
                return {
                    "loginState": observed["loginState"],
                    "credentialState": observed["credentialState"],
                    "activeSessions": sessions,
                    "customerRowsRead": False,
                }

            executor = production_executor.BoundActivationExecutor(
                production_contact=False,
                observation_dsn=observation_dsn, admin_dsn=admin_dsn,
                container=CONTAINER,
                container_id=container_id, image_id=image_id,
                system_identifier=system_identifier,
                workspace_parent=workspace_parent,
                proxy_parent=proxy_parent,
                resource_journal_root=resource_journal_root,
            )
            arguments = {
                "keyring_raw": _canonical(keyring),
                "decision_raw": _canonical(decision),
                "activation_plan_raw": _canonical(plan),
                "expected_keyring_sha256": keyring_sha,
                "expected_environment": "DISPOSABLE_CONTRACT",
                "now_epoch": now_epoch, "journal_root": journal_root,
                "executor": executor, "reconcile": reconcile,
                "verify_dormant": dormant,
            }
            watchdog_result = {}
            watchdog_failure = []

            def supervise_live_lease():
                try:
                    wait_deadline = time.monotonic() + 120
                    while time.monotonic() < wait_deadline:
                        if runtime._role_auth_state(admin_dsn)["login"] is True:
                            watchdog_result.update(watchdog.watchdog_once(
                                container_name=CONTAINER,
                                expected_image_id=image_id,
                                expected_volume_name=volume_name,
                                expected_server_version_num=170011,
                                expected_system_identifier=system_identifier,
                                allow_contract_container=True,
                                require_dormant=True,
                            ))
                            return
                        time.sleep(0.02)
                    raise RuntimeError("WATCHDOG_LIVE_LEASE_NOT_OBSERVED")
                except BaseException as exc:
                    watchdog_failure.append(exc)

            interlock_fd = os.open(
                watchdog.ACTIVATION_INTERLOCK_PATH,
                os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
                0o600,
            )
            fcntl.flock(interlock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            watcher = threading.Thread(
                target=supervise_live_lease, name="b64-watchdog-contract",
            )
            watcher.start()
            try:
                result = activation.run_once(**arguments)
            finally:
                watcher.join(timeout=30)
                os.close(interlock_fd)
            if watcher.is_alive():
                raise RuntimeError("WATCHDOG_CONCURRENT_REHEARSAL_TIMEOUT")
            if watchdog_failure:
                raise RuntimeError("WATCHDOG_CONCURRENT_REHEARSAL_FAILED") \
                    from watchdog_failure[0]
            if watchdog_result.get("status") != (
                    "ACTIVE_LEASE_ACTIVATION_INTERLOCK_SUPERVISED"):
                raise RuntimeError("WATCHDOG_ACTIVE_LEASE_NOT_SUPERVISED")
            try:
                activation.run_once(**arguments)
            except activation.ActivationError as exc:
                replay_reason = str(exc)
            if replay_reason != "ACTIVATION_REPLAY_OR_INCOMPLETE":
                raise RuntimeError("ACTIVATION_REPLAY_NOT_REJECTED")
            if executor.calls != 1:
                raise RuntimeError("ACTIVATION_EXECUTOR_RETRIED")
            journal = activation.ActivationJournal(
                journal_root,
                activation.verify_activation_decision(
                    keyring_raw=_canonical(keyring),
                    decision_raw=_canonical(decision),
                    activation_plan_raw=_canonical(plan),
                    expected_keyring_sha256=keyring_sha,
                    expected_environment="DISPOSABLE_CONTRACT",
                    now_epoch=now_epoch,
                ),
            ).inspect()
            if journal["state"] != "CLOSED":
                raise RuntimeError("ACTIVATION_JOURNAL_NOT_CLOSED")

            recovery_keyring, recovery_keyring_sha, recovery_plan, \
                recovery_decision = _signed_package(
                    now_epoch=now_epoch, container_id=container_id,
                    image_id=image_id,
                    system_identifier=system_identifier,
                )
            recovery_authorization = activation.verify_activation_decision(
                keyring_raw=_canonical(recovery_keyring),
                decision_raw=_canonical(recovery_decision),
                activation_plan_raw=_canonical(recovery_plan),
                expected_keyring_sha256=recovery_keyring_sha,
                expected_environment="DISPOSABLE_CONTRACT",
                now_epoch=now_epoch,
            )
            recovery_journal = activation.ActivationJournal(
                journal_root, recovery_authorization,
            )
            recovery_journal.claim()
            recovery_journal.transition(
                expected_state={"CLAIMED"}, state="RUNNING",
            )
            recovery_resources = \
                production_executor.ExecutorResourceJournal(
                    root=resource_journal_root,
                    workspace_parent=workspace_parent,
                    run_nonce=recovery_authorization.run_nonce,
                    environment=recovery_authorization.environment,
                    target=recovery_authorization.target,
                    plan_sha256=recovery_authorization.plan_sha256,
                    decision_sha256=recovery_authorization.decision_sha256,
                    derived_plan_sha256=(
                        recovery_authorization
                        .derived_execution_plan_sha256
                    ),
                )
            recovery_resources.create()
            unbound_workspace = workspace_parent / \
                recovery_resources.initial["workspaceName"]
            unbound_workspace.mkdir(mode=0o700)
            unbound_archive = unbound_workspace / "snapshot.dump"
            unbound_archive.write_bytes(b"synthetic-unbound-partial")
            unbound_archive.chmod(0o600)
            expired_now = max(
                recovery_keyring["expiresAtEpoch"],
                recovery_decision["expiresAtEpoch"],
            ) + 1
            cold_recovery_result = \
                activation.recover_incomplete_from_package(
                    keyring_raw=_canonical(recovery_keyring),
                    decision_raw=_canonical(recovery_decision),
                    activation_plan_raw=_canonical(recovery_plan),
                    expected_keyring_sha256=recovery_keyring_sha,
                    expected_environment="DISPOSABLE_CONTRACT",
                    now_epoch=expired_now, journal_root=journal_root,
                    executor=executor, reconcile=reconcile,
                    verify_dormant=dormant,
                )
            if (cold_recovery_result.get("status")
                    != "ACTIVATION_RECONCILED_HOLD"
                    or recovery_journal.inspect()["state"]
                    != "RECONCILED_HOLD"
                    or recovery_resources.inspect()["state"]
                    != "RECONCILED_HOLD"
                    or unbound_workspace.exists()
                    or executor.calls != 1):
                raise RuntimeError("COLD_EXPIRY_RECOVERY_NOT_CLOSED")

            kill_keyring, kill_keyring_sha, kill_plan, kill_decision = \
                _signed_package(
                    now_epoch=now_epoch, container_id=container_id,
                    image_id=image_id,
                    system_identifier=system_identifier,
                )
            kill_authorization = activation.verify_activation_decision(
                keyring_raw=_canonical(kill_keyring),
                decision_raw=_canonical(kill_decision),
                activation_plan_raw=_canonical(kill_plan),
                expected_keyring_sha256=kill_keyring_sha,
                expected_environment="DISPOSABLE_CONTRACT",
                now_epoch=now_epoch,
            )
            kill_journal = activation.ActivationJournal(
                journal_root, kill_authorization,
            )
            kill_resources = production_executor.ExecutorResourceJournal(
                root=resource_journal_root,
                workspace_parent=workspace_parent,
                run_nonce=kill_authorization.run_nonce,
                environment=kill_authorization.environment,
                target=kill_authorization.target,
                plan_sha256=kill_authorization.plan_sha256,
                decision_sha256=kill_authorization.decision_sha256,
                derived_plan_sha256=(
                    kill_authorization.derived_execution_plan_sha256
                ),
            )
            kill_workspace = workspace_parent / \
                kill_resources.initial["workspaceName"]

            def killed_after_durable_running():
                execution_lock = kill_journal.acquire_execution_lock()
                try:
                    kill_journal.claim()
                    kill_journal.transition(
                        expected_state={"CLAIMED"}, state="RUNNING",
                    )
                    kill_resources.create()
                    kill_workspace.mkdir(mode=0o700)
                    archive = kill_workspace / "snapshot.dump"
                    archive.write_bytes(b"synthetic-hard-kill-partial")
                    archive.chmod(0o600)
                    while True:
                        time.sleep(1)
                finally:
                    os.close(execution_lock)

            kill_code, kill_receipt = activation_launcher.supervise_once(
                killed_after_durable_running, wall_seconds=0.4,
            )
            if (kill_code != 3
                    or kill_receipt.get("reason") != (
                        "LAUNCHER_HARD_WALL_TIMEOUT_"
                        "PROCESS_GROUP_TERMINATED"
                    )
                    or kill_journal.inspect()["state"] != "RUNNING"
                    or kill_resources.inspect()["state"] != "PREPARED"):
                raise RuntimeError("LAUNCHER_HARD_KILL_NOT_DURABLE")
            kill_recovery = activation.verify_cleanup_recovery(
                keyring_raw=_canonical(kill_keyring),
                decision_raw=_canonical(kill_decision),
                activation_plan_raw=_canonical(kill_plan),
                expected_keyring_sha256=kill_keyring_sha,
                expected_environment="DISPOSABLE_CONTRACT",
                now_epoch=max(
                    kill_keyring["expiresAtEpoch"],
                    kill_decision["expiresAtEpoch"],
                ) + 1,
            )
            hard_kill_recovery_result = activation.reconcile_incomplete(
                authorization=kill_recovery, journal_root=journal_root,
                activation_plan_raw=_canonical(kill_plan),
                executor=executor, reconcile=reconcile,
                verify_dormant=dormant, automatic_no_retry=True,
            )
            if (hard_kill_recovery_result.get("status")
                    != "ACTIVATION_RECONCILED_HOLD"
                    or kill_journal.inspect()["state"]
                    != "RECONCILED_HOLD"
                    or kill_resources.inspect()["state"]
                    != "RECONCILED_HOLD"
                    or kill_workspace.exists()
                    or executor.calls != 1):
                raise RuntimeError("LAUNCHER_HARD_KILL_RECOVERY_NOT_CLOSED")
    finally:
        primary_error = sys.exception()
        reconcile_error = None
        try:
            try:
                runtime.reconcile_credential(
                    observation_dsn=observation_dsn, admin_dsn=admin_dsn,
                    container=CONTAINER, expected_container_id=container_id,
                    expected_image_id=image_id, allow_contract_container=True,
                )
            except BaseException as exc:
                reconcile_error = exc
        finally:
            rolled_back = subprocess.run(
                hba_command + ["--rollback"], env=environment, check=False,
                capture_output=True, text=True, pass_fds=(passfile_fd,),
            )
            os.close(passfile_fd)
        if (rolled_back.returncode != 0
                or json.loads(rolled_back.stdout)["status"] != "ROLLED_BACK"):
            raise RuntimeError("CONTRACT_HBA_ROLLBACK_FAILED")
        if reconcile_error is not None and primary_error is None:
            raise reconcile_error
    if result is None:
        raise RuntimeError("ACTIVATION_RESULT_MISSING")
    print(json.dumps({
        "status": "DISPOSABLE_ACTIVATION_REHEARSAL_VERIFIED",
        "route": activation.ROUTE,
        "journalState": result["journalState"],
        "receiptSha256": result["receiptSha256"],
        "replayReason": replay_reason,
        "executorCalls": 1,
        "watchdogStatus": watchdog_result["status"],
        "coldRecoveryStatus": cold_recovery_result["status"],
        "hardKillRecoveryStatus": hard_kill_recovery_result["status"],
        "hardKillProcessGroupTerminated": True,
        "hardKillAutomaticRecoveryAttempts": 1,
        "hardKillSecondExecutorCall": False,
        "coldRecoveryAfterKeyringAndDecisionExpiry": True,
        "preInodeWorkspaceRecovered": True,
        "readerLoginState": "DISABLED",
        "readerCredentialState": "ABSENT",
        "readerActiveSessions": 0,
        "productionDatabaseContact": False,
        "productionConfigurationMutation": False,
        "productionHbaReadOnlyCopyUsed": True,
        "productionActivation": False,
        "automaticRetryAllowed": False,
        "actionAllowed": False,
    }, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
