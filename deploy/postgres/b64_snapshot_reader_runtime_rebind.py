#!/usr/bin/env python3
"""Atomically rebind dormant B64 HBA recovery evidence after a container recreate.

This command never changes pg_hba.conf, role privileges, credentials, or LOGIN.
It accepts only an already-healthy, exact dormant target and replaces the
root-owned journal binding after every filesystem and catalog check passes.
"""
from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import hashlib
import json
import os
import re
import secrets
import stat
import subprocess
from contextlib import contextmanager, nullcontext
from pathlib import Path
from typing import Any, Iterator

from psycopg.conninfo import make_conninfo

from verify_b64_snapshot_reader import inspect as inspect_role


ROLE = "obsidian_b64_snapshot_reader"
DATABASE = "obsidian_exchange"
PRODUCTION_CONTAINER = "obsidian-postgres"
PRODUCTION_VOLUME = "obsidian-postgres-data"
CONTRACT_COMPOSE_PROJECT = "obsidian-postgres-contract"
CONTRACT_COMPOSE_SERVICE = "postgres-contract"
PRODUCTION_SYSTEM_IDENTIFIER = "7672203973020184609"
DATA_DIRECTORY = "/var/lib/postgresql/data"
HBA_NAME = "pg_hba.conf"
STATE_DIRECTORY = ".obsidian-b64-hba-v1"
JOURNAL_NAME = "journal.json"
BACKUP_NAME = "original.pg_hba"
EXPECTED_ORIGINAL_HBA_SHA256 = (
    "45b68cd420caab6d19725857c309871880a66a4c195bcd7e1604e7c334b6be82"
)
EXPECTED_DEPLOYED_HBA_SHA256 = (
    "08b049674e7593bc87c8e78744ba6b65b557750807c17e860920931aa1b3d3b6"
)
POSTGRES_17_10_IMAGE_ID = (
    "sha256:742f40ea20b9ff2ff31db5458d127452988a2164df9e17441e191f3b72252193"
)
POSTGRES_17_11_IMAGE_ID = (
    "sha256:7456ef82e5f5bc43d997f4781bbd7c0d6389bff397564649a356e206ba473aee"
)
PRODUCTION_IMAGE_TRANSITIONS = {
    (POSTGRES_17_10_IMAGE_ID, POSTGRES_17_10_IMAGE_ID),
    (POSTGRES_17_10_IMAGE_ID, POSTGRES_17_11_IMAGE_ID),
    (POSTGRES_17_11_IMAGE_ID, POSTGRES_17_11_IMAGE_ID),
    (POSTGRES_17_11_IMAGE_ID, POSTGRES_17_10_IMAGE_ID),
}
RUNTIME_ADVISORY_LOCK_KEY = 664064017023001
HOST_LOCK_PATH = Path("/run/lock/obsidian-b64-runtime-rebind.lock")
MAX_FILE_BYTES = 1024 * 1024
TEMP_JOURNAL = re.compile(r"journal[.][0-9a-f]{16}[.]tmp")
HBA_STAGE = re.compile(r"[.]obsidian-b64-hba-stage-[0-9a-f]{24}")


class RebindError(RuntimeError):
    """Closed reason code safe for an operational receipt."""


def _safe_reason(exc: BaseException) -> str:
    if isinstance(exc, RebindError) and re.fullmatch(r"[A-Z0-9_]+", str(exc)):
        return str(exc)
    return "UNEXPECTED_RUNTIME_REBIND_FAILURE"


def _closed_token(value: str, pattern: str, reason: str) -> str:
    if not re.fullmatch(pattern, value or ""):
        raise RebindError(reason)
    return value


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _read_regular_at(
    directory_fd: int,
    name: str,
    *,
    mode: int,
    uid: int,
    gid: int,
) -> bytes:
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory_fd)
    except OSError as exc:
        raise RebindError("RUNTIME_REBIND_FILE_OPEN_FAILED") from exc
    try:
        metadata = os.fstat(fd)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != mode
            or metadata.st_uid != uid
            or metadata.st_gid != gid
            or metadata.st_nlink != 1
            or not 1 <= metadata.st_size <= MAX_FILE_BYTES
        ):
            raise RebindError("RUNTIME_REBIND_FILE_METADATA_MISMATCH")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(fd)


def _read_regular_at_with_owners(
    directory_fd: int,
    name: str,
    *,
    mode: int,
    allowed_owners: set[tuple[int, int]],
    allow_empty: bool = False,
) -> tuple[bytes, tuple[int, int]]:
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory_fd)
    except OSError as exc:
        raise RebindError("RUNTIME_REBIND_FILE_OPEN_FAILED") from exc
    try:
        metadata = os.fstat(fd)
        owner = (metadata.st_uid, metadata.st_gid)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != mode
            or owner not in allowed_owners
            or metadata.st_nlink != 1
            or not (0 if allow_empty else 1) <= metadata.st_size <= MAX_FILE_BYTES
        ):
            raise RebindError("RUNTIME_REBIND_FILE_METADATA_MISMATCH")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks), owner
    finally:
        os.close(fd)


@contextmanager
def _host_lock(path: Path = HOST_LOCK_PATH) -> Iterator[None]:
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        metadata = os.fstat(fd)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != 0
            or metadata.st_gid != 0
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_nlink != 1
        ):
            raise RebindError("RUNTIME_REBIND_HOST_LOCK_UNSAFE")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RebindError("RUNTIME_REBIND_ALREADY_RUNNING") from exc
        yield
    finally:
        os.close(fd)


def inspect_container(
    name: str,
    *,
    expected_image_id: str,
    expected_volume_name: str,
    allow_contract_container: bool = False,
) -> dict[str, Any]:
    if allow_contract_container:
        _closed_token(
            name,
            r"b64-(?:hba|watchdog|upgrade)-contract-[0-9]+",
            "CONTRACT_CONTAINER_NAME_INVALID",
        )
        _closed_token(
            expected_volume_name,
            r"(?:b64-(?:watchdog|upgrade)-volume-[0-9a-f]{16,64}|b64[0-9a-f]{61})",
            "CONTRACT_VOLUME_NAME_INVALID",
        )
    elif name != PRODUCTION_CONTAINER or expected_volume_name != PRODUCTION_VOLUME:
        raise RebindError("PRODUCTION_TARGET_MISMATCH")
    _closed_token(
        expected_image_id,
        r"sha256:[0-9a-f]{64}",
        "EXPECTED_IMAGE_ID_INVALID",
    )
    result = subprocess.run(
        ["/usr/bin/docker", "inspect", name],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=10,
        env={"PATH": "/usr/bin:/bin"},
    )
    if result.returncode != 0:
        raise RebindError("CONTAINER_INSPECT_FAILED")
    try:
        value = json.loads(result.stdout)[0]
        state = value["State"]
        labels = value["Config"]["Labels"]
        mounts = value["Mounts"]
        ports = value["NetworkSettings"]["Ports"]["5432/tcp"]
    except (IndexError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise RebindError("CONTAINER_INSPECTION_INVALID") from exc
    pgdata = [item for item in mounts if item.get("Destination") == DATA_DIRECTORY]
    port_valid = (
        len(ports) == 1
        and ports[0].get("HostIp") == "127.0.0.1"
        and isinstance(ports[0].get("HostPort"), str)
        and ports[0]["HostPort"].isdigit()
        and (
            allow_contract_container
            or ports[0]["HostPort"] == "5432"
        )
    )
    if (
        value.get("Image") != expected_image_id
        or state.get("Running") is not True
        or state.get("Status") != "running"
        or state.get("Health", {}).get("Status") != "healthy"
        or not isinstance(state.get("Pid"), int)
        or state["Pid"] <= 0
        or labels.get("com.docker.compose.project") != (
            CONTRACT_COMPOSE_PROJECT
            if allow_contract_container else "obsidian-postgres"
        )
        or labels.get("com.docker.compose.service") != (
            CONTRACT_COMPOSE_SERVICE
            if allow_contract_container else "postgres"
        )
        or len(pgdata) != 1
        or pgdata[0].get("Type") != "volume"
        or pgdata[0].get("Name") != expected_volume_name
        or pgdata[0].get("RW") is not True
        or pgdata[0].get("Source")
        != f"/var/lib/docker/volumes/{expected_volume_name}/_data"
        or not port_valid
    ):
        raise RebindError("CONTAINER_BINDING_MISMATCH")
    container_id = str(value.get("Id", "")).removeprefix("sha256:")
    if re.fullmatch(r"[0-9a-f]{64}", container_id) is None:
        raise RebindError("CONTAINER_ID_INVALID")
    return {
        "containerId": container_id,
        "containerPid": state["Pid"],
        "imageId": value["Image"],
        "health": state["Health"]["Status"],
        "startedAt": state.get("StartedAt"),
        "restartCount": value.get("RestartCount"),
        "hostPort": int(ports[0]["HostPort"]),
        "mountSource": pgdata[0]["Source"],
    }


@contextmanager
def admin_connection(container_pid: int) -> Iterator[Any]:
    if any(name.startswith("PG") and value for name, value in os.environ.items()):
        raise RebindError("AMBIENT_LIBPQ_ENVIRONMENT_FORBIDDEN")
    passfile_fd = os.memfd_create("obsidian-b64-empty-pgpass", os.MFD_CLOEXEC)
    os.fchmod(passfile_fd, 0o600)
    dsn = make_conninfo(
        host=f"/proc/{container_pid}/root/var/run/postgresql",
        dbname=DATABASE,
        user="postgres",
        port=5432,
        connect_timeout=5,
        sslmode="disable",
        target_session_attrs="read-write",
        passfile=f"/proc/self/fd/{passfile_fd}",
        application_name="obsidian-b64-runtime-rebind",
    )
    try:
        import psycopg

        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute("SET statement_timeout='10s'")
            conn.execute("SET lock_timeout='3s'")
            conn.execute("SET idle_session_timeout='15s'")
            yield conn
    except RebindError:
        raise
    except BaseException as exc:
        raise RebindError("ADMIN_SOCKET_CONNECTION_FAILED") from exc
    finally:
        os.close(passfile_fd)


def inspect_server(
    conn: Any,
    *,
    expected_server_version_num: int,
    expected_system_identifier: str,
    require_dormant: bool = True,
) -> dict[str, Any]:
    row = conn.execute(
        "SELECT current_user,current_database(),r.rolsuper,r.rolcreaterole,"
        "current_setting('transaction_read_only'),inet_client_addr() IS NULL,"
        "current_setting('server_version_num')::int,"
        "current_setting('data_directory'),current_setting('hba_file'),"
        "system_identifier::text,pg_postmaster_start_time(),target.oid,"
        "target.rolcanlogin,(auth.rolpassword IS NULL),"
        "COALESCE(auth.rolvaliduntil::text,''),"
        "target.rolconnlimit,(SELECT count(*) FROM pg_stat_activity "
        "WHERE usename=%s) FROM pg_roles r CROSS JOIN pg_control_system() "
        "JOIN pg_roles target ON target.rolname=%s "
        "JOIN pg_authid auth ON auth.oid=target.oid WHERE r.rolname=current_user",
        (ROLE, ROLE),
    ).fetchone()
    base_mismatch = (
        row is None
        or row[:6] != ("postgres", DATABASE, True, True, "off", True)
        or row[6] != expected_server_version_num
        or row[7] != DATA_DIRECTORY
        or row[8] != f"{DATA_DIRECTORY}/{HBA_NAME}"
        or row[9] != expected_system_identifier
        or not isinstance(row[11], int)
        or row[11] <= 0
        or row[15] != 2
        or not isinstance(row[16], int)
        or not 0 <= row[16] <= 2
    )
    dormant = (
        not base_mismatch
        and row[12] is False
        and row[13] is True
        and row[14] in {"", "infinity"}
        and row[16] == 0
    )
    if base_mismatch or (require_dormant and not dormant):
        raise RebindError("DORMANT_SERVER_BINDING_MISMATCH")
    return {
        "serverVersionNum": row[6],
        "systemIdentifier": row[9],
        "postmasterStartTime": row[10].isoformat(),
        "roleOid": row[11],
        "roleLoginState": "ENABLED" if row[12] else "DISABLED",
        "credentialState": "ABSENT" if row[13] else "PRESENT",
        "validUntil": row[14],
        "activeSessions": row[16],
        "dormant": dormant,
    }


def force_dormant(conn: Any) -> None:
    """Reduce authority, including after an ambiguous ALTER acknowledgement."""
    from psycopg import sql

    command = sql.SQL(
        "ALTER ROLE {} NOLOGIN PASSWORD NULL VALID UNTIL 'infinity'"
    ).format(sql.Identifier(ROLE))
    try:
        conn.execute(command)
    except BaseException:
        pass
    state = conn.execute(
        "SELECT r.rolcanlogin,(a.rolpassword IS NULL),"
        "COALESCE(a.rolvaliduntil::text,'') "
        "FROM pg_roles r JOIN pg_authid a ON a.oid=r.oid WHERE r.rolname=%s",
        (ROLE,),
    ).fetchone()
    if state not in {(False, True, ""), (False, True, "infinity")}:
        try:
            conn.execute(command)
        except BaseException as exc:
            raise RebindError("RUNTIME_REBIND_REVOKE_UNCERTAIN") from exc
    for (pid,) in conn.execute(
        "SELECT pid FROM pg_stat_activity WHERE usename=%s "
        "AND pid<>pg_backend_pid() ORDER BY pid",
        (ROLE,),
    ).fetchall():
        if conn.execute(
            "SELECT pg_terminate_backend(%s,5000)", (pid,)
        ).fetchone()[0] is not True:
            raise RebindError("RUNTIME_REBIND_SESSION_TERMINATION_FAILED")
    post = conn.execute(
        "SELECT r.rolcanlogin,(a.rolpassword IS NULL),"
        "COALESCE(a.rolvaliduntil::text,''),"
        "(SELECT count(*) FROM pg_stat_activity WHERE usename=%s) "
        "FROM pg_roles r JOIN pg_authid a ON a.oid=r.oid WHERE r.rolname=%s",
        (ROLE, ROLE),
    ).fetchone()
    if post not in {
        (False, True, "", 0), (False, True, "infinity", 0)
    }:
        raise RebindError("RUNTIME_REBIND_REVOKE_UNCERTAIN")


def _open_bundle(
    container: dict[str, Any],
) -> tuple[
    int, int, dict[str, Any], tuple[str, dict[str, Any] | None] | None, bool
]:
    pgdata_fd = os.open(container["mountSource"], os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        pgdata_metadata = os.fstat(pgdata_fd)
        if (
            not stat.S_ISDIR(pgdata_metadata.st_mode)
            or stat.S_IMODE(pgdata_metadata.st_mode) != 0o700
            or pgdata_metadata.st_uid != 70
            or pgdata_metadata.st_gid != 70
        ):
            raise RebindError("PGDATA_METADATA_MISMATCH")
        stages = [name for name in os.listdir(pgdata_fd) if HBA_STAGE.fullmatch(name)]
        if stages:
            raise RebindError("HBA_STAGE_EVIDENCE_PENDING")
        hba = _read_regular_at(pgdata_fd, HBA_NAME, mode=0o600, uid=70, gid=70)
        if _sha256(hba) != EXPECTED_DEPLOYED_HBA_SHA256:
            raise RebindError("HBA_FILE_SHA256_MISMATCH")
        state_fd = os.open(
            STATE_DIRECTORY,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
            dir_fd=pgdata_fd,
        )
    except BaseException:
        os.close(pgdata_fd)
        raise
    state_metadata = os.fstat(state_fd)
    if (
        not stat.S_ISDIR(state_metadata.st_mode)
        or stat.S_IMODE(state_metadata.st_mode) != 0o700
        or (state_metadata.st_uid, state_metadata.st_gid)
        not in {(0, 0), (70, 0), (70, 70)}
    ):
        os.close(state_fd)
        os.close(pgdata_fd)
        raise RebindError("HBA_STATE_DIRECTORY_METADATA_MISMATCH")
    entries = set(os.listdir(state_fd))
    temporary = sorted(name for name in entries if TEMP_JOURNAL.fullmatch(name))
    if (
        not {JOURNAL_NAME, BACKUP_NAME}.issubset(entries)
        or entries - {JOURNAL_NAME, BACKUP_NAME, *temporary}
        or len(temporary) > 1
    ):
        os.close(state_fd)
        os.close(pgdata_fd)
        raise RebindError("HBA_RECOVERY_BUNDLE_NOT_CLEAN")
    backup = _read_regular_at(state_fd, BACKUP_NAME, mode=0o600, uid=70, gid=70)
    if _sha256(backup) != EXPECTED_ORIGINAL_HBA_SHA256:
        os.close(state_fd)
        os.close(pgdata_fd)
        raise RebindError("HBA_ROLLBACK_BACKUP_SHA256_MISMATCH")
    state_owner = (state_metadata.st_uid, state_metadata.st_gid)
    allowed_journal_owners = (
        {(0, 0)} if state_owner == (0, 0) else {state_owner, (0, 0)}
    )
    journal_bytes, journal_owner = _read_regular_at_with_owners(
        state_fd,
        JOURNAL_NAME,
        mode=0o600,
        allowed_owners=allowed_journal_owners,
    )
    try:
        journal = json.loads(journal_bytes)
    except json.JSONDecodeError as exc:
        os.close(state_fd)
        os.close(pgdata_fd)
        raise RebindError("HBA_JOURNAL_INVALID") from exc
    pending = None
    if temporary:
        pending_bytes, pending_owner = _read_regular_at_with_owners(
            state_fd,
            temporary[0],
            mode=0o600,
            allowed_owners=allowed_journal_owners,
            allow_empty=True,
        )
        try:
            decoded_pending = json.loads(pending_bytes)
        except json.JSONDecodeError:
            decoded_pending = None
        pending_value = decoded_pending if isinstance(decoded_pending, dict) else None
        pending = (temporary[0], pending_value)
    else:
        pending_owner = (0, 0)
    ownership_rebind = (
        state_owner != (0, 0)
        or journal_owner != (0, 0)
        or pending_owner != (0, 0)
    )
    return pgdata_fd, state_fd, journal, pending, ownership_rebind


def _reclaim_state_ownership(
    state_fd: int, pending: tuple[str, dict[str, Any] | None] | None
) -> None:
    state_metadata = os.fstat(state_fd)
    state_owner = (state_metadata.st_uid, state_metadata.st_gid)
    if state_owner not in {(0, 0), (70, 0), (70, 70)}:
        raise RebindError("HBA_STATE_OWNERSHIP_TRANSITION_MISMATCH")
    allowed_file_owners = (
        {(0, 0)} if state_owner == (0, 0) else {state_owner, (0, 0)}
    )
    for name in [JOURNAL_NAME] + ([pending[0]] if pending is not None else []):
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=state_fd)
        try:
            metadata = os.fstat(fd)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or stat.S_IMODE(metadata.st_mode) != 0o600
                or (metadata.st_uid, metadata.st_gid) not in allowed_file_owners
            ):
                raise RebindError("HBA_STATE_OWNERSHIP_TRANSITION_MISMATCH")
            if (metadata.st_uid, metadata.st_gid) != (0, 0):
                os.fchown(fd, 0, 0)
                os.fsync(fd)
        finally:
            os.close(fd)
    metadata = os.fstat(state_fd)
    if (metadata.st_uid, metadata.st_gid) != state_owner:
        raise RebindError("HBA_STATE_OWNERSHIP_TRANSITION_MISMATCH")
    if state_owner != (0, 0):
        os.fchown(state_fd, 0, 0)
        os.fsync(state_fd)


def _validate_journal(
    journal: dict[str, Any],
    *,
    allowed_container_ids: set[str],
    allowed_image_ids: set[str],
    expected_system_identifier: str,
) -> None:
    if (
        not isinstance(journal, dict)
        or journal.get("schemaVersion") != "obsidian-b64-hba-journal.v1"
        or journal.get("phase") != "DEPLOYED_VERIFIED"
        or journal.get("containerId") not in allowed_container_ids
        or journal.get("containerImageId") not in allowed_image_ids
        or not isinstance(journal.get("containerPid"), int)
        or journal["containerPid"] <= 0
        or journal.get("systemIdentifier") != expected_system_identifier
        or journal.get("originalSha256") != EXPECTED_ORIGINAL_HBA_SHA256
        or journal.get("deployedSha256") != EXPECTED_DEPLOYED_HBA_SHA256
        or re.fullmatch(r"[0-9a-f]{32}", str(journal.get("nonce", ""))) is None
        or not isinstance(journal.get("verifiedAt"), str)
    ):
        raise RebindError("HBA_JOURNAL_BINDING_MISMATCH")


def _replace_journal(state_fd: int, journal: dict[str, Any]) -> None:
    name = f"journal.{secrets.token_hex(8)}.tmp"
    payload = json.dumps(journal, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"
    fd = os.open(
        name,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600,
        dir_fd=state_fd,
    )
    try:
        os.fchmod(fd, 0o600)
        offset = 0
        while offset < len(payload):
            offset += os.write(fd, payload[offset:])
        os.fsync(fd)
    finally:
        os.close(fd)
    os.rename(name, JOURNAL_NAME, src_dir_fd=state_fd, dst_dir_fd=state_fd)
    os.fsync(state_fd)


def _previous_container_inactive(
    previous_container_id: str, current_container_id: str
) -> None:
    if previous_container_id == current_container_id:
        return
    inventory = subprocess.run(
        [
            "/usr/bin/docker", "container", "ls", "--all", "--no-trunc",
            "--format", "{{.ID}}",
        ],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=10,
        env={"PATH": "/usr/bin:/bin"},
    )
    if inventory.returncode != 0:
        raise RebindError("CONTAINER_INVENTORY_FAILED")
    container_ids = set(inventory.stdout.splitlines())
    if any(re.fullmatch(r"[0-9a-f]{64}", item) is None for item in container_ids):
        raise RebindError("CONTAINER_INVENTORY_INVALID")
    if previous_container_id not in container_ids:
        return
    result = subprocess.run(
        ["/usr/bin/docker", "inspect", previous_container_id],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=10,
        env={"PATH": "/usr/bin:/bin"},
    )
    if result.returncode != 0:
        raise RebindError("PREVIOUS_CONTAINER_INSPECTION_FAILED")
    try:
        value = json.loads(result.stdout)[0]
    except (IndexError, TypeError, json.JSONDecodeError) as exc:
        raise RebindError("PREVIOUS_CONTAINER_INSPECTION_INVALID") from exc
    if value.get("State", {}).get("Running") is True:
        raise RebindError("PREVIOUS_CONTAINER_STILL_RUNNING")


def _apply_bundle_rebind(
    *,
    container: dict[str, Any],
    previous_container_id: str,
    previous_image_id: str,
    expected_image_id: str,
    expected_system_identifier: str,
    apply: bool,
) -> str:
    pgdata_fd, state_fd, journal, pending, ownership_rebind = _open_bundle(container)
    try:
        _validate_journal(
            journal,
            allowed_container_ids={previous_container_id, container["containerId"]},
            allowed_image_ids={previous_image_id, expected_image_id},
            expected_system_identifier=expected_system_identifier,
        )
        allowed_runtime_bindings = {
            (previous_container_id, previous_image_id),
            (container["containerId"], expected_image_id),
        }
        if (journal["containerId"], journal["containerImageId"]) not in \
                allowed_runtime_bindings:
            raise RebindError("HBA_JOURNAL_RUNTIME_PAIR_MISMATCH")
        invalid_pending = pending is not None and pending[1] is None
        if pending is not None and not invalid_pending:
            assert pending[1] is not None
            _validate_journal(
                pending[1],
                allowed_container_ids={container["containerId"]},
                allowed_image_ids={expected_image_id},
                expected_system_identifier=expected_system_identifier,
            )
            if pending[1]["containerPid"] != container["containerPid"]:
                raise RebindError("HBA_PENDING_JOURNAL_BINDING_MISMATCH")
        current_bound = (
            journal["containerId"] == container["containerId"]
            and journal["containerPid"] == container["containerPid"]
        )
        needs_rebind = not current_bound or pending is not None or ownership_rebind
        if not needs_rebind:
            status = "ALREADY_RUNTIME_BOUND"
        elif not apply:
            status = "RUNTIME_REBIND_REQUIRED"
        else:
            if ownership_rebind:
                _reclaim_state_ownership(state_fd, pending)
            if invalid_pending:
                assert pending is not None
                os.unlink(pending[0], dir_fd=state_fd)
                os.fsync(state_fd)
                pending = None
            if pending is not None and not current_bound:
                os.rename(
                    pending[0], JOURNAL_NAME,
                    src_dir_fd=state_fd, dst_dir_fd=state_fd,
                )
                os.fsync(state_fd)
                status = "RUNTIME_REBIND_RECOVERED_VERIFIED"
            elif pending is not None and current_bound:
                os.unlink(pending[0], dir_fd=state_fd)
                os.fsync(state_fd)
                status = "RUNTIME_REBIND_TEMP_CLEANED_VERIFIED"
            elif invalid_pending and current_bound:
                status = "RUNTIME_REBIND_INVALID_TEMP_CLEANED_VERIFIED"
            else:
                previous_pid = journal["containerPid"]
                journal.update(
                    {
                        "containerId": container["containerId"],
                        "containerPid": container["containerPid"],
                        "previousContainerId": previous_container_id,
                        "previousContainerPid": previous_pid,
                        "previousContainerImageId": previous_image_id,
                        "containerImageId": expected_image_id,
                        "runtimeReboundAt": dt.datetime.now(dt.timezone.utc).isoformat(),
                        "verifiedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
                    }
                )
                _replace_journal(state_fd, journal)
                status = "RUNTIME_REBOUND_VERIFIED"
        if apply and needs_rebind:
            rebound = json.loads(
                _read_regular_at(state_fd, JOURNAL_NAME, mode=0o600, uid=0, gid=0)
            )
            _validate_journal(
                rebound,
                allowed_container_ids={container["containerId"]},
                allowed_image_ids={expected_image_id},
                expected_system_identifier=expected_system_identifier,
            )
            if rebound["containerPid"] != container["containerPid"]:
                raise RebindError("RUNTIME_REBIND_POSTVERIFY_FAILED")
            residual = set(os.listdir(state_fd)) - {JOURNAL_NAME, BACKUP_NAME}
            if residual:
                raise RebindError("RUNTIME_REBIND_RESIDUAL_EVIDENCE")
        return status
    finally:
        os.close(state_fd)
        os.close(pgdata_fd)


def rebind_runtime(
    *,
    container_name: str,
    expected_image_id: str,
    expected_volume_name: str,
    previous_container_id: str,
    previous_image_id: str,
    expected_server_version_num: int,
    expected_system_identifier: str,
    apply: bool,
    allow_contract_container: bool = False,
    host_lock_held: bool = False,
) -> dict[str, Any]:
    previous_container_id = _closed_token(
        previous_container_id,
        r"[0-9a-f]{64}",
        "PREVIOUS_CONTAINER_ID_INVALID",
    )
    previous_image_id = _closed_token(
        previous_image_id,
        r"sha256:[0-9a-f]{64}",
        "PREVIOUS_IMAGE_ID_INVALID",
    )
    if (
        type(expected_server_version_num) is not int
        or expected_server_version_num // 10000 != 17
    ):
        raise RebindError("EXPECTED_SERVER_VERSION_INVALID")
    if allow_contract_container:
        _closed_token(
            expected_system_identifier,
            r"[0-9]{10,24}",
            "EXPECTED_SYSTEM_IDENTIFIER_INVALID",
        )
    elif expected_system_identifier != PRODUCTION_SYSTEM_IDENTIFIER:
        raise RebindError("PRODUCTION_SYSTEM_IDENTIFIER_MISMATCH")
    elif (previous_image_id, expected_image_id) not in PRODUCTION_IMAGE_TRANSITIONS:
        raise RebindError("PRODUCTION_IMAGE_TRANSITION_NOT_ALLOWED")

    lock_context = nullcontext() if host_lock_held else _host_lock()
    with lock_context:
        container = inspect_container(
            container_name,
            expected_image_id=expected_image_id,
            expected_volume_name=expected_volume_name,
            allow_contract_container=allow_contract_container,
        )
        if previous_container_id == container["containerId"]:
            if previous_image_id != expected_image_id:
                raise RebindError("SAME_CONTAINER_IMAGE_TRANSITION_INVALID")
        _previous_container_inactive(previous_container_id, container["containerId"])
        with admin_connection(container["containerPid"]) as conn:
            before_server = inspect_server(
                conn,
                expected_server_version_num=expected_server_version_num,
                expected_system_identifier=expected_system_identifier,
                require_dormant=False,
            )
            if conn.execute(
                "SELECT pg_try_advisory_lock(%s)",
                (RUNTIME_ADVISORY_LOCK_KEY,),
            ).fetchone()[0] is not True:
                raise RebindError("RUNTIME_REBIND_ADVISORY_LOCK_BUSY")
            authority_reduced = not before_server["dormant"]
            if authority_reduced:
                force_dormant(conn)
            server = inspect_server(
                conn,
                expected_server_version_num=expected_server_version_num,
                expected_system_identifier=expected_system_identifier,
                require_dormant=True,
            )
            role = inspect_role(conn.info.dsn, expected_login=False)
            if (
                role.get("status") != "match"
                or role.get("loginState") != "DISABLED"
                or role.get("credentialState") != "ABSENT"
                or role.get("hbaIsolationStatus") != "EXACT"
                or role.get("hbaFileSha256") != EXPECTED_DEPLOYED_HBA_SHA256
            ):
                raise RebindError("DORMANT_ROLE_OR_HBA_MISMATCH")
            status = _apply_bundle_rebind(
                container=container,
                previous_container_id=previous_container_id,
                previous_image_id=previous_image_id,
                expected_image_id=expected_image_id,
                expected_system_identifier=expected_system_identifier,
                apply=apply,
            )
            after = inspect_container(
                container_name,
                expected_image_id=expected_image_id,
                expected_volume_name=expected_volume_name,
                allow_contract_container=allow_contract_container,
            )
            if after != container:
                raise RebindError("CONTAINER_CHANGED_DURING_RUNTIME_REBIND")
            inspect_server(
                conn,
                expected_server_version_num=expected_server_version_num,
                expected_system_identifier=expected_system_identifier,
                require_dormant=True,
            )
            final_role = inspect_role(conn.info.dsn, expected_login=False)
            if (
                final_role.get("status") != "match"
                or final_role.get("loginState") != "DISABLED"
                or final_role.get("credentialState") != "ABSENT"
            ):
                raise RebindError("RUNTIME_REBIND_FINAL_DORMANCY_MISMATCH")
        return {
            "schemaVersion": "obsidian-b64-runtime-rebind.v1",
            "status": status,
            "container": container,
            "server": server,
            "hbaFileSha256": EXPECTED_DEPLOYED_HBA_SHA256,
            "roleLoginState": "DISABLED",
            "credentialState": "ABSENT",
            "customerRowsRead": False,
            "hbaChanged": False,
            "credentialChanged": authority_reduced,
            "roleLoginChanged": authority_reduced,
            "authorityIncreased": False,
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--container", default=PRODUCTION_CONTAINER)
    parser.add_argument("--expected-image-id", required=True)
    parser.add_argument("--expected-volume-name", default=PRODUCTION_VOLUME)
    parser.add_argument("--previous-container-id", required=True)
    parser.add_argument("--previous-image-id", required=True)
    parser.add_argument("--expected-server-version-num", required=True, type=int)
    parser.add_argument(
        "--expected-system-identifier", default=PRODUCTION_SYSTEM_IDENTIFIER
    )
    parser.add_argument("--allow-contract-container", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        result = rebind_runtime(
            container_name=args.container,
            expected_image_id=args.expected_image_id,
            expected_volume_name=args.expected_volume_name,
            previous_container_id=args.previous_container_id,
            previous_image_id=args.previous_image_id,
            expected_server_version_num=args.expected_server_version_num,
            expected_system_identifier=args.expected_system_identifier,
            apply=args.apply,
            allow_contract_container=args.allow_contract_container,
        )
        print(json.dumps(result, sort_keys=True))
        return 0 if result["status"] != "RUNTIME_REBIND_REQUIRED" else 3
    except BaseException as exc:
        print(
            json.dumps(
                {
                    "schemaVersion": "obsidian-b64-runtime-rebind.v1",
                    "status": "FAILED_OR_AUTHORITY_REDUCED_NO_HBA_MUTATION",
                    "reason": _safe_reason(exc),
                    "customerRowsRead": False,
                    "hbaChanged": False,
                    "authorityIncreased": False,
                },
                sort_keys=True,
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
