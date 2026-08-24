#!/usr/bin/env python3
"""Short-lived snapshot-reader credential lease and TCP snapshot helpers.

The lease API is intended for a bounded orchestrator.  It never returns the
password: callers receive two independent sealed pgpass memfds, one for the
exporting source session and one for the importing dump session.
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import fcntl
import hashlib
import hmac
import json
import os
import re
import secrets
import select
import stat
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

_HELPER_PROCESS = any(
    flag in {"--export-helper", "--import-helper"}
    for flag in sys.argv[1:]
)

if not _HELPER_PROCESS:
    from deploy_b64_snapshot_reader import (
        _admin_preflight,
        _bind_empty_memfd_passfile,
        _catalog_preflight,
        _inspect_container,
        _load_and_bind_plan,
        _validate_container_admin_dsn,
    )
    from deploy_b64_snapshot_reader_hba import (
        _bind_mount,
        _cluster_identity,
        _docker_inspect,
        _hba_parser_report,
        _load_manifest,
        _open_pgdata,
        _open_state,
        _read_at,
        _stage_reports,
        _validate_hba_metadata,
        _validate_recovery_bundle,
        _verify_cluster,
    )
    from verify_b64_snapshot_reader import inspect as inspect_role


ROLE = "obsidian_b64_snapshot_reader"
DATABASE = "obsidian_exchange"
HOST = "127.0.0.1"
PORT = 5432
PRODUCTION_SYSTEM_IDENTIFIER = "7672203973020184609"
DATA_DIRECTORY = "/var/lib/postgresql/data"
HBA_FILE = f"{DATA_DIRECTORY}/pg_hba.conf"
MIN_TTL_SECONDS = 30
MAX_TTL_SECONDS = 180
MAX_PGPASS_BYTES = 512
SCRAM_SALT_BYTES = 16
MIN_SCRAM_ITERATIONS = 4096
MAX_SCRAM_ITERATIONS = 1_000_000
RUNTIME_ADVISORY_LOCK_KEY = 664064017023001
HELPER_APPLICATION_PREFIX = "obsidian-b64-snapshot"
LOCK_APPLICATION_PREFIX = "obsidian-b64-lease-lock"
INITIAL_LOCK_IDLE_TIMEOUT_SECONDS = MAX_TTL_SECONDS + 30
RECONCILE_CLEANUP_SECONDS = 15
REQUIRED_SEALS = (
    fcntl.F_SEAL_SEAL | fcntl.F_SEAL_SHRINK |
    fcntl.F_SEAL_GROW | fcntl.F_SEAL_WRITE
)


class RuntimeContractError(RuntimeError):
    """Closed reason code that is safe to expose in receipts."""


def _safe_reason(exc: BaseException) -> str:
    if (isinstance(exc, RuntimeContractError)
            and re.fullmatch(r"[A-Z0-9_]+", str(exc))):
        return str(exc)
    return "UNEXPECTED_SNAPSHOT_READER_RUNTIME_FAILURE"


def _snapshot(value: str) -> str:
    if not re.fullmatch(r"[0-9A-Fa-f:-]{1,128}", value):
        raise RuntimeContractError("INVALID_EXPORTED_SNAPSHOT")
    return value


def _sealed_pgpass_memfd(value: bytes, name: str) -> int:
    if (not 1 <= len(value) <= MAX_PGPASS_BYTES or b"\n" not in value
            or value.count(b"\n") != 1 or not value.endswith(b"\n")):
        raise RuntimeContractError("INVALID_PGPASS_PAYLOAD")
    fd = os.memfd_create(
        name, os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING
    )
    try:
        os.fchmod(fd, 0o600)
        offset = 0
        while offset < len(value):
            offset += os.write(fd, value[offset:])
        os.lseek(fd, 0, os.SEEK_SET)
        fcntl.fcntl(fd, fcntl.F_ADD_SEALS, REQUIRED_SEALS)
        _validate_credential_fd(fd)
        return fd
    except BaseException:
        os.close(fd)
        raise


def _validate_credential_fd(
    fd: int, *, require_cloexec: bool = True,
) -> os.stat_result:
    try:
        metadata = os.fstat(fd)
        seals = fcntl.fcntl(fd, fcntl.F_GET_SEALS)
        descriptor_flags = fcntl.fcntl(fd, fcntl.F_GETFD)
    except (OSError, TypeError, ValueError) as exc:
        raise RuntimeContractError("INVALID_CREDENTIAL_FD") from exc
    if (not stat.S_ISREG(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_nlink != 0
            or not 1 <= metadata.st_size <= MAX_PGPASS_BYTES
            or seals & REQUIRED_SEALS != REQUIRED_SEALS
            or (require_cloexec
                and descriptor_flags & fcntl.FD_CLOEXEC == 0)):
        raise RuntimeContractError("INVALID_CREDENTIAL_FD")
    return metadata


def _validate_observation_dsn_secret_boundary(dsn: str) -> None:
    try:
        connection = conninfo_to_dict(dsn)
    except BaseException as exc:
        raise RuntimeContractError("INVALID_OBSERVATION_DSN") from exc
    if any(connection.get(key) for key in (
            "password", "service", "servicefile", "sslpassword")):
        raise RuntimeContractError("OBSERVATION_DSN_INLINE_SECRET_FORBIDDEN")
    passfile = connection.get("passfile")
    if passfile is None:
        return
    match = re.fullmatch(r"/proc/self/fd/([0-9]+)", passfile)
    if match is None:
        raise RuntimeContractError("OBSERVATION_PASSFILE_NOT_ANONYMOUS_FD")
    _validate_credential_fd(int(match.group(1)))


def _role_auth_state_on(
    conn: Any, lock_expires_at: dt.datetime | None = None,
) -> dict[str, Any]:
    if lock_expires_at is None:
        row = conn.execute(
            "SELECT r.rolcanlogin,a.rolpassword IS NULL,"
            "COALESCE(a.rolvaliduntil::text,''),"
            "(SELECT count(*) FROM pg_stat_activity WHERE usename=%s) "
            "FROM pg_roles r JOIN pg_authid a ON a.oid=r.oid "
            "WHERE r.rolname=%s",
            (ROLE, ROLE),
        ).fetchone()
    else:
        row = conn.execute(sql.SQL(
            "WITH obsidian_deadline AS MATERIALIZED ("
            "SELECT CEIL(EXTRACT(EPOCH FROM ({}::timestamptz-"
            "clock_timestamp()))*1000)::bigint AS remaining_ms) "
            "SELECT r.rolcanlogin,a.rolpassword IS NULL,"
            "COALESCE(a.rolvaliduntil::text,''),"
            "(SELECT count(*) FROM pg_stat_activity WHERE usename=%s),"
            "set_config('idle_session_timeout',(CASE WHEN d.remaining_ms "
            "BETWEEN 1 AND {} THEN d.remaining_ms ELSE 1 END)::text||'ms',"
            "false),d.remaining_ms "
            "FROM pg_roles r JOIN pg_authid a ON a.oid=r.oid "
            "CROSS JOIN obsidian_deadline d WHERE r.rolname=%s"
        ).format(
            sql.Literal(lock_expires_at.isoformat()),
            sql.Literal((MAX_TTL_SECONDS + 1) * 1000),
        ), (ROLE, ROLE)).fetchone()
        row = _validated_deadlined_row(row)
    if row is None:
        raise RuntimeContractError("SNAPSHOT_READER_ROLE_MISSING")
    return {
        "login": row[0], "passwordAbsent": row[1],
        "validUntil": row[2], "sessions": row[3],
    }


def _role_auth_state(admin_dsn: str) -> dict[str, Any]:
    import psycopg

    with psycopg.connect(admin_dsn, connect_timeout=5) as conn:
        conn.execute("SET LOCAL statement_timeout='10s'")
        conn.execute("SET LOCAL lock_timeout='3s'")
        return _role_auth_state_on(conn)


def _reconcile_role_auth_state(
    conn: Any,
) -> tuple[dict[str, Any], dt.datetime]:
    """Atomically derive and arm a short absolute recovery deadline."""
    row = conn.execute(sql.SQL(
        "WITH role_state AS MATERIALIZED (SELECT r.rolcanlogin,"
        "a.rolpassword IS NULL AS password_absent,"
        "COALESCE(a.rolvaliduntil::text,'') AS valid_until_text,"
        "(SELECT count(*) FROM pg_stat_activity WHERE usename={}) AS sessions,"
        "a.rolvaliduntil,clock_timestamp() AS observed_at "
        "FROM pg_roles r JOIN pg_authid a ON a.oid=r.oid "
        "WHERE r.rolname={}),cleanup AS MATERIALIZED (SELECT *,"
        "observed_at+{}::interval AS deadline_at FROM role_state),"
        "residual AS MATERIALIZED (SELECT *,CEIL(EXTRACT(EPOCH FROM "
        "(deadline_at-clock_timestamp()))*1000)::bigint AS remaining_ms "
        "FROM cleanup) SELECT rolcanlogin,password_absent,valid_until_text,"
        "sessions,deadline_at,set_config('idle_session_timeout',(CASE WHEN "
        "remaining_ms BETWEEN 1 AND {} THEN remaining_ms ELSE 1 END)::text||"
        "'ms',false),remaining_ms FROM residual"
    ).format(
        sql.Literal(ROLE), sql.Literal(ROLE),
        sql.Literal(f"{RECONCILE_CLEANUP_SECONDS}s"),
        sql.Literal((MAX_TTL_SECONDS + 1) * 1000),
    )).fetchone()
    if row is None:
        raise RuntimeContractError("SNAPSHOT_READER_ROLE_MISSING")
    checked = _validated_deadlined_row(row)
    deadline_at = checked[4]
    if not isinstance(deadline_at, dt.datetime) or deadline_at.tzinfo is None:
        raise RuntimeContractError("INVALID_RECONCILE_DEADLINE")
    return ({
        "login": checked[0], "passwordAbsent": checked[1],
        "validUntil": checked[2], "sessions": checked[3],
    }, deadline_at)


def _scram_verifier(
    password: bytes, iterations: int, *, salt: bytes | None = None,
) -> str:
    """Build PostgreSQL's RFC 5803 SCRAM verifier without sending plaintext."""
    if (not isinstance(password, bytes)
            or re.fullmatch(rb"[A-Za-z0-9_-]{43}", password) is None):
        raise RuntimeContractError("INVALID_GENERATED_PASSWORD")
    if (type(iterations) is not int
            or not MIN_SCRAM_ITERATIONS <= iterations <= MAX_SCRAM_ITERATIONS):
        raise RuntimeContractError("UNSAFE_SCRAM_ITERATIONS")
    if salt is None:
        salt = secrets.token_bytes(SCRAM_SALT_BYTES)
    if not isinstance(salt, bytes) or len(salt) != SCRAM_SALT_BYTES:
        raise RuntimeContractError("INVALID_SCRAM_SALT")
    salted_password = hashlib.pbkdf2_hmac(
        "sha256", password, salt, iterations
    )
    client_key = hmac.new(
        salted_password, b"Client Key", hashlib.sha256
    ).digest()
    stored_key = hashlib.sha256(client_key).digest()
    server_key = hmac.new(
        salted_password, b"Server Key", hashlib.sha256
    ).digest()
    encode = lambda value: base64.b64encode(value).decode("ascii")
    return (
        f"SCRAM-SHA-256${iterations}:{encode(salt)}$"
        f"{encode(stored_key)}:{encode(server_key)}"
    )


def _credential_server_state(conn: Any) -> tuple[dt.datetime, int]:
    row = conn.execute(
        "SELECT clock_timestamp(),current_setting('password_encryption'),"
        "current_setting('scram_iterations')"
    ).fetchone()
    if (row is None or row[1] != "scram-sha-256"
            or not re.fullmatch(r"[0-9]+", row[2])):
        raise RuntimeContractError("SCRAM_SERVER_POLICY_MISMATCH")
    iterations = int(row[2])
    if not MIN_SCRAM_ITERATIONS <= iterations <= MAX_SCRAM_ITERATIONS:
        raise RuntimeContractError("UNSAFE_SCRAM_ITERATIONS")
    return row[0], iterations


def _revoke(
    conn: Any, lock_expires_at: dt.datetime | None = None,
) -> None:
    command = sql.SQL(
        "ALTER ROLE {} NOLOGIN PASSWORD NULL VALID UNTIL 'infinity'"
    ).format(sql.Identifier(ROLE))
    if lock_expires_at is None:
        conn.execute(command)
    else:
        _execute_commands_with_deadline(conn, command, lock_expires_at)


def _set_short_lived_verifier(
    conn: Any, verifier: str, expires_at: dt.datetime,
) -> None:
    if re.fullmatch(
        r"SCRAM-SHA-256\$[0-9]+:[A-Za-z0-9+/]+={0,2}\$"
        r"[A-Za-z0-9+/]+={0,2}:[A-Za-z0-9+/]+={0,2}",
        verifier,
    ) is None:
        raise RuntimeContractError("INVALID_SCRAM_VERIFIER")
    command = sql.SQL(
        "ALTER ROLE {} LOGIN PASSWORD {} VALID UNTIL {}"
    ).format(
        sql.Identifier(ROLE),
        sql.Literal(verifier),
        sql.Literal(expires_at.isoformat()),
    )
    _execute_commands_with_deadline(conn, command, expires_at)


def _acquire_runtime_lock(
    admin_dsn: str, operation_nonce: str, *,
    initial_idle_timeout_seconds: int = INITIAL_LOCK_IDLE_TIMEOUT_SECONDS,
    lock_expires_at: dt.datetime | None = None,
):
    import psycopg

    if re.fullmatch(r"[0-9a-f]{32}", operation_nonce) is None:
        raise RuntimeContractError("INVALID_RUNTIME_OPERATION_NONCE")
    if (type(initial_idle_timeout_seconds) is not int
            or not 1 <= initial_idle_timeout_seconds
            <= INITIAL_LOCK_IDLE_TIMEOUT_SECONDS):
        raise RuntimeContractError("INVALID_INITIAL_LOCK_TIMEOUT")
    dsn = make_conninfo(
        admin_dsn,
        application_name=f"{LOCK_APPLICATION_PREFIX}-{operation_nonce}",
    )
    conn = psycopg.connect(dsn, connect_timeout=5, autocommit=True)
    try:
        conn.execute("SET statement_timeout='10s'")
        conn.execute("SET lock_timeout='3s'")
        # These harmless statements must execute before any Query message can
        # contain a SCRAM verifier: PostgreSQL statement logging happens before
        # execution of statements within that later Query message.
        conn.execute("SET log_statement='none'")
        conn.execute("SET log_min_duration_statement=-1")
        conn.execute("SET log_min_error_statement='panic'")
        conn.execute(sql.SQL("SET idle_session_timeout={}").format(
            sql.Literal(f"{initial_idle_timeout_seconds}s")
        ))
        if lock_expires_at is None:
            acquired = conn.execute(
                "SELECT pg_try_advisory_lock(%s)",
                (RUNTIME_ADVISORY_LOCK_KEY,),
            ).fetchone()[0]
        else:
            row = conn.execute(sql.SQL(
                "WITH acquired AS MATERIALIZED (SELECT "
                "pg_try_advisory_lock({}) AS ok),"
                "obsidian_deadline AS MATERIALIZED (SELECT acquired.ok,"
                "CEIL(EXTRACT(EPOCH FROM ({}::timestamptz-"
                "clock_timestamp()))*1000)::bigint AS remaining_ms "
                "FROM acquired) SELECT ok,set_config("
                "'idle_session_timeout',(CASE WHEN remaining_ms BETWEEN 1 "
                "AND {} THEN remaining_ms ELSE 1 END)::text||'ms',false),"
                "remaining_ms FROM obsidian_deadline"
            ).format(
                sql.Literal(RUNTIME_ADVISORY_LOCK_KEY),
                sql.Literal(lock_expires_at.isoformat()),
                sql.Literal((MAX_TTL_SECONDS + 1) * 1000),
            )).fetchone()
            acquired = _validated_deadlined_row(row)[0]
        if acquired is not True:
            raise RuntimeContractError("CREDENTIAL_RUNTIME_BUSY")
        return conn
    except BaseException:
        conn.close()
        raise


def _deadline_statement(expires_at: dt.datetime) -> sql.Composed:
    """Set the residual idle timeout from server time in one statement."""
    return sql.SQL(
        "WITH obsidian_deadline AS MATERIALIZED ("
        "SELECT CEIL(EXTRACT(EPOCH FROM ({}::timestamptz-clock_timestamp()))"
        "*1000)::bigint AS remaining_ms) "
        "SELECT set_config('idle_session_timeout',(CASE WHEN remaining_ms "
        "BETWEEN 1 AND {} THEN remaining_ms ELSE 1 END)::text||'ms',false),"
        "remaining_ms FROM obsidian_deadline"
    ).format(
        sql.Literal(expires_at.isoformat()),
        sql.Literal((MAX_TTL_SECONDS + 1) * 1000),
    )


def _validated_deadlined_row(row: Any) -> Any:
    if (row is None or len(row) < 2 or type(row[-1]) is not int
            or row[-1] <= 0
            or row[-1] > (MAX_TTL_SECONDS + 1) * 1000):
        raise RuntimeContractError("LOCK_EXPIRY_OUT_OF_BOUNDS")
    return row[:-2]


def _arm_runtime_lock_deadline(conn: Any, expires_at: dt.datetime) -> None:
    try:
        row = conn.execute(_deadline_statement(expires_at)).fetchone()
        _validated_deadlined_row(row)
    except RuntimeContractError:
        raise
    except BaseException as exc:
        raise RuntimeContractError("CREDENTIAL_RUNTIME_LOCK_LOST") from exc


def _execute_commands_with_deadline(
    conn: Any, commands: sql.Composed, expires_at: dt.datetime,
) -> None:
    """Send mutations plus final absolute re-arm in one server Query message."""
    try:
        cursor = conn.execute(sql.SQL("{};{}").format(
            commands, _deadline_statement(expires_at)
        ))
        deadline_row = None
        while True:
            if cursor.description is not None:
                deadline_row = cursor.fetchone()
            if not cursor.nextset():
                break
        _validated_deadlined_row(deadline_row)
    except RuntimeContractError:
        raise
    except BaseException as exc:
        raise RuntimeContractError("CREDENTIAL_RUNTIME_LOCK_LOST") from exc


def _assert_runtime_lock(
    conn: Any, lock_expires_at: dt.datetime | None = None,
) -> None:
    try:
        if conn.closed:
            raise RuntimeContractError("CREDENTIAL_RUNTIME_LOCK_LOST")
        if lock_expires_at is None:
            if conn.execute("SELECT 1").fetchone()[0] != 1:
                raise RuntimeContractError("CREDENTIAL_RUNTIME_LOCK_LOST")
        else:
            _arm_runtime_lock_deadline(conn, lock_expires_at)
    except RuntimeContractError:
        raise
    except BaseException as exc:
        raise RuntimeContractError("CREDENTIAL_RUNTIME_LOCK_LOST") from exc


def _recover_runtime_lock(
    admin_dsn: str, conn: Any,
    lock_expires_at: dt.datetime | None = None,
) -> Any:
    try:
        _assert_runtime_lock(conn, lock_expires_at)
        return conn
    except RuntimeContractError:
        try:
            conn.close()
        except BaseException:
            pass
        recovered = _acquire_runtime_lock(
            admin_dsn, secrets.token_hex(16),
            initial_idle_timeout_seconds=RECONCILE_CLEANUP_SECONDS,
            lock_expires_at=lock_expires_at,
        )
        try:
            return recovered
        except BaseException:
            recovered.close()
            raise


def _evict_reader_held_runtime_lock(
    *, observation_dsn: str, admin_dsn: str, admin_input_dsn: str,
    container: str, expected_container_id: str, expected_image_id: str,
    require_healthy: bool, allow_contract_container: bool,
) -> bool:
    """Reduce authority around any lock not held by the exact issuer."""
    import psycopg

    class_id = RUNTIME_ADVISORY_LOCK_KEY >> 32
    object_id = RUNTIME_ADVISORY_LOCK_KEY & 0xFFFFFFFF
    with psycopg.connect(
        admin_dsn, connect_timeout=5, autocommit=True
    ) as conn:
        conn.execute("SET statement_timeout='10s'")
        conn.execute("SET lock_timeout='3s'")
        conn.execute("SET log_statement='none'")
        conn.execute("SET log_min_duration_statement=-1")
        conn.execute("SET log_min_error_statement='panic'")
        holders = conn.execute(
            "SELECT a.usename,a.application_name,l.pid "
            "FROM pg_locks l JOIN pg_stat_activity a ON a.pid=l.pid "
            "WHERE l.locktype='advisory' AND l.database="
            "(SELECT oid FROM pg_database WHERE datname=current_database()) "
            "AND l.classid=%s AND l.objid=%s AND l.objsubid=1 "
            "AND l.granted ORDER BY l.pid",
            (class_id, object_id),
        ).fetchall()
        if not holders or any(
            row[0] == "postgres"
            and isinstance(row[1], str)
            and row[1].startswith(f"{LOCK_APPLICATION_PREFIX}-")
            for row in holders
        ):
            raise RuntimeContractError("CREDENTIAL_RUNTIME_BUSY")
        _state, cleanup_deadline = _reconcile_role_auth_state(conn)
        _minimal_mutation_binding(
            observation_dsn=observation_dsn,
            admin_input_dsn=admin_input_dsn, lock_conn=conn,
            container=container,
            expected_container_id=expected_container_id,
            expected_image_id=expected_image_id,
            require_healthy=require_healthy,
            allow_contract_container=allow_contract_container,
            lock_expires_at=cleanup_deadline,
        )
        _force_dormant(conn, cleanup_deadline)
        remaining = conn.execute(
            "SELECT count(*) FROM pg_locks WHERE locktype='advisory' "
            "AND database=(SELECT oid FROM pg_database "
            "WHERE datname=current_database()) AND classid=%s "
            "AND objid=%s AND objsubid=1 AND granted",
            (class_id, object_id),
        ).fetchone()[0]
        return remaining == 0


def _netns_inode(pid: int) -> int:
    try:
        inode = os.stat(f"/proc/{pid}/ns/net").st_ino
    except OSError as exc:
        raise RuntimeContractError("SOURCE_NETNS_ATTESTATION_FAILED") from exc
    if inode <= 0:
        raise RuntimeContractError("SOURCE_NETNS_ATTESTATION_FAILED")
    return inode


@dataclass(frozen=True)
class RuntimeBinding:
    container: dict[str, Any]
    cluster: dict[str, Any]
    manifest: dict[str, Any]
    netns_inode: int
    recovery_nonce: str


@dataclass(frozen=True)
class MutationBinding:
    container: dict[str, Any]
    system_identifier: str
    postmaster_start_time: dt.datetime
    data_directory: str
    hba_file: str
    mount_source: str
    netns_inode: int
    role_oid: int


def _minimal_mutation_binding(
    *, observation_dsn: str, admin_input_dsn: str, lock_conn: Any,
    container: str, expected_container_id: str, expected_image_id: str,
    require_healthy: bool, allow_contract_container: bool,
    lock_expires_at: dt.datetime | None = None,
) -> MutationBinding:
    """Bind only immutable authority needed to revoke before broad checks."""
    before = _inspect_container(
        container, expected_container_id, expected_image_id,
        False, observation_dsn,
    )
    _validate_container_admin_dsn(
        admin_input_dsn, DATABASE, before["containerPid"]
    )
    raw = _docker_inspect(container)
    if raw["Id"].removeprefix("sha256:") != expected_container_id:
        raise RuntimeContractError("RAW_CONTAINER_IDENTITY_MISMATCH")
    mounts = [
        item for item in raw.get("Mounts", [])
        if item.get("Destination") == DATA_DIRECTORY
    ]
    if len(mounts) != 1:
        raise RuntimeContractError("MINIMAL_PGDATA_MOUNT_MISMATCH")
    mount = mounts[0]
    source = mount.get("Source")
    if (mount.get("Type") != "volume" or mount.get("RW") is not True
            or not isinstance(source, str)
            or not source.startswith("/var/lib/docker/volumes/")):
        raise RuntimeContractError("MINIMAL_PGDATA_MOUNT_MISMATCH")
    query = (
        "SELECT current_user,current_database(),r.rolsuper,r.rolcreaterole,"
        "current_setting('transaction_read_only'),inet_client_addr() IS NULL,"
        "current_setting('server_version_num')::int,"
        "current_setting('data_directory'),current_setting('hba_file'),"
        "current_setting('password_encryption'),system_identifier::text,"
        "pg_postmaster_start_time(),target.oid{} "
        "FROM pg_roles r CROSS JOIN pg_control_system() "
        "JOIN pg_roles target ON target.rolname=%s {}"
        "WHERE r.rolname=current_user"
    )
    if lock_expires_at is None:
        row = lock_conn.execute(query.format("", ""), (ROLE,)).fetchone()
    else:
        deadline_prefix = sql.SQL(
            "WITH obsidian_deadline AS MATERIALIZED (SELECT CEIL("
            "EXTRACT(EPOCH FROM ({}::timestamptz-clock_timestamp()))"
            "*1000)::bigint AS remaining_ms) "
        ).format(sql.Literal(lock_expires_at.isoformat()))
        deadline_query = sql.SQL(query.format(
            ",set_config('idle_session_timeout',(CASE WHEN d.remaining_ms "
            "BETWEEN 1 AND {} THEN d.remaining_ms ELSE 1 END)::text||'ms',"
            "false),d.remaining_ms",
            "CROSS JOIN obsidian_deadline d ",
        )).format(sql.Literal((MAX_TTL_SECONDS + 1) * 1000))
        row = lock_conn.execute(
            deadline_prefix + deadline_query, (ROLE,)
        ).fetchone()
        row = _validated_deadlined_row(row)
    if (row is None or row[:6] != (
            "postgres", DATABASE, True, True, "off", True)
            or row[6] // 10000 != 17 or row[7] != DATA_DIRECTORY
            or row[8] != HBA_FILE or row[9] != "scram-sha-256"
            or (not allow_contract_container
                and row[10] != PRODUCTION_SYSTEM_IDENTIFIER)
            or not isinstance(row[12], int) or row[12] <= 0):
        raise RuntimeContractError("MINIMAL_MUTATION_TARGET_MISMATCH")
    return MutationBinding(
        container={
            key: before[key] for key in (
                "containerId", "imageId", "status", "hostPort",
                "containerPid",
            )
        },
        system_identifier=row[10],
        postmaster_start_time=row[11], data_directory=row[7],
        hba_file=row[8], mount_source=source,
        netns_inode=_netns_inode(before["containerPid"]), role_oid=row[12],
    )


def _force_dormant_bound(
    *, observation_dsn: str, admin_dsn: str, admin_input_dsn: str,
    lock_conn: Any, expected: MutationBinding, container: str,
    expected_container_id: str, expected_image_id: str,
    require_healthy: bool, allow_contract_container: bool,
    lock_expires_at: dt.datetime | None = None,
) -> tuple[dict[str, Any], Any]:
    """Reacquire serialization after connection loss, then revoke minimally."""
    try:
        result = _force_dormant(lock_conn, lock_expires_at)
    except BaseException:
        lock_conn = _recover_runtime_lock(
            admin_dsn, lock_conn, lock_expires_at
        )
        rebound = _minimal_mutation_binding(
            observation_dsn=observation_dsn,
            admin_input_dsn=admin_input_dsn, lock_conn=lock_conn,
            container=container, expected_container_id=expected_container_id,
            expected_image_id=expected_image_id,
            require_healthy=require_healthy,
            allow_contract_container=allow_contract_container,
            lock_expires_at=lock_expires_at,
        )
        if rebound != expected:
            raise RuntimeContractError("REVOCATION_TARGET_CHANGED")
        result = _force_dormant(lock_conn, lock_expires_at)
    post = _minimal_mutation_binding(
        observation_dsn=observation_dsn,
        admin_input_dsn=admin_input_dsn, lock_conn=lock_conn,
        container=container, expected_container_id=expected_container_id,
        expected_image_id=expected_image_id,
        require_healthy=require_healthy,
        allow_contract_container=allow_contract_container,
        lock_expires_at=lock_expires_at,
    )
    if post != expected:
        raise RuntimeContractError("REVOCATION_TARGET_CHANGED")
    return result, lock_conn


def _exact_runtime_binding(
    *, observation_dsn: str, admin_dsn: str, admin_input_dsn: str,
    container: str,
    expected_container_id: str, expected_image_id: str,
    require_healthy: bool, allow_contract_container: bool,
    expected_login: bool,
) -> RuntimeBinding:
    """Bind every mutable execution dependency before/after auth mutation."""
    _load_and_bind_plan()
    manifest = _load_manifest()
    before = _inspect_container(
        container, expected_container_id, expected_image_id,
        require_healthy, observation_dsn,
    )
    _validate_container_admin_dsn(
        admin_input_dsn, DATABASE, before["containerPid"]
    )
    _admin_preflight(admin_dsn, DATABASE)
    raw = _docker_inspect(container)
    if raw["Id"].removeprefix("sha256:") != expected_container_id:
        raise RuntimeContractError("RAW_CONTAINER_IDENTITY_MISMATCH")
    pgdata = _bind_mount(
        raw, manifest, allow_contract_container=allow_contract_container
    )
    cluster = _cluster_identity(admin_dsn)
    _verify_cluster(
        cluster, manifest,
        allow_contract_container=allow_contract_container,
    )
    _catalog_preflight(observation_dsn, DATABASE)
    role = inspect_role(admin_dsn, expected_login=expected_login)
    parser = _hba_parser_report(admin_dsn)
    if (role.get("status") != "match"
            or role.get("hbaIsolationStatus") != "EXACT"
            or role.get("hbaFileSha256")
               != manifest["expectedDeployedSha256"]
            or parser["fileSha256"] != manifest["expectedDeployedSha256"]
            or parser["errors"]):
        raise RuntimeContractError("RUNTIME_ROLE_OR_HBA_BINDING_MISMATCH")
    directory_fd = _open_pgdata(pgdata)
    state_fd = None
    try:
        hba, metadata = _read_at(directory_fd, "pg_hba.conf")
        _validate_hba_metadata(metadata)
        if hashlib.sha256(hba).hexdigest() \
                != manifest["expectedDeployedSha256"]:
            raise RuntimeContractError("RUNTIME_HBA_FILE_SHA_MISMATCH")
        state_fd = _open_state(directory_fd)
        journal, _backup, pending = _validate_recovery_bundle(
            state_fd, before, cluster, manifest,
            frozenset({"DEPLOYED_VERIFIED"}), strict_pid=True,
        )
        if pending or _stage_reports(directory_fd):
            raise RuntimeContractError("RUNTIME_HBA_RECOVERY_STATE_NOT_CLEAN")
        recovery_nonce = journal["nonce"]
    finally:
        if state_fd is not None:
            os.close(state_fd)
        os.close(directory_fd)
    return RuntimeBinding(
        container=before, cluster=cluster, manifest=manifest,
        netns_inode=_netns_inode(before["containerPid"]),
        recovery_nonce=recovery_nonce,
    )


def _terminate_role_sessions(
    conn: Any, lock_expires_at: dt.datetime | None = None,
) -> None:
    if lock_expires_at is None:
        rows = conn.execute(
            "SELECT pid FROM pg_stat_activity WHERE usename=%s "
            "AND pid<>pg_backend_pid() ORDER BY pid",
            (ROLE,),
        ).fetchall()
        pids = [row[0] for row in rows]
    else:
        rows = conn.execute(sql.SQL(
            "WITH obsidian_deadline AS MATERIALIZED ("
            "SELECT CEIL(EXTRACT(EPOCH FROM ({}::timestamptz-"
            "clock_timestamp()))*1000)::bigint AS remaining_ms) "
            "SELECT sessions.pid,set_config('idle_session_timeout',"
            "(CASE WHEN d.remaining_ms BETWEEN 1 AND {} THEN "
            "d.remaining_ms ELSE 1 END)::text||'ms',false),d.remaining_ms "
            "FROM obsidian_deadline d LEFT JOIN LATERAL (SELECT pid FROM "
            "pg_stat_activity WHERE usename=%s AND pid<>pg_backend_pid() "
            "ORDER BY pid) sessions ON true"
        ).format(
            sql.Literal(lock_expires_at.isoformat()),
            sql.Literal((MAX_TTL_SECONDS + 1) * 1000),
        ), (ROLE,)).fetchall()
        pids = []
        for row in rows:
            checked = _validated_deadlined_row(row)
            if checked[0] is not None:
                pids.append(checked[0])
    for pid in pids:
        if lock_expires_at is None:
            terminated = conn.execute(
                "SELECT pg_terminate_backend(%s,5000)", (pid,)
            ).fetchone()[0]
        else:
            row = conn.execute(sql.SQL(
                "WITH terminated AS MATERIALIZED ("
                "SELECT pg_terminate_backend(%s,5000) AS ok),"
                "obsidian_deadline AS MATERIALIZED (SELECT "
                "CEIL(EXTRACT(EPOCH FROM ({}::timestamptz-"
                "clock_timestamp()))*1000)::bigint AS remaining_ms "
                "FROM terminated) SELECT terminated.ok,"
                "set_config('idle_session_timeout',(CASE WHEN "
                "d.remaining_ms BETWEEN 1 AND {} THEN d.remaining_ms "
                "ELSE 1 END)::text||'ms',false),d.remaining_ms "
                "FROM terminated CROSS JOIN obsidian_deadline d"
            ).format(
                sql.Literal(lock_expires_at.isoformat()),
                sql.Literal((MAX_TTL_SECONDS + 1) * 1000),
            ), (pid,)).fetchone()
            terminated = _validated_deadlined_row(row)[0]
        if terminated is not True:
            raise RuntimeContractError("ROLE_SESSION_TERMINATION_FAILED")


def _force_dormant(
    conn: Any, lock_expires_at: dt.datetime | None = None,
) -> dict[str, Any]:
    """Resolve even an acknowledged-or-not revoke, then end all role sessions."""
    revoke_error = False
    try:
        _revoke(conn, lock_expires_at)
    except BaseException:
        revoke_error = True
    try:
        state = _role_auth_state_on(conn, lock_expires_at)
        if state["login"] is not False or state["passwordAbsent"] is not True:
            second_error = False
            try:
                _revoke(conn, lock_expires_at)
            except BaseException:
                second_error = True
            state = _role_auth_state_on(conn, lock_expires_at)
            if (second_error and (state["login"] is not False
                                  or state["passwordAbsent"] is not True)):
                raise RuntimeContractError("CREDENTIAL_REVOKE_UNCERTAIN")
        _terminate_role_sessions(conn, lock_expires_at)
        state = _role_auth_state_on(conn, lock_expires_at)
    except BaseException as exc:
        raise RuntimeContractError("CREDENTIAL_REVOKE_UNCERTAIN") from exc
    if state != {
        "login": False, "passwordAbsent": True,
        "validUntil": "infinity", "sessions": 0,
    }:
        raise RuntimeContractError("CREDENTIAL_REVOKE_UNCERTAIN")
    return {
        "status": (
            "REVOKED_AFTER_AMBIGUOUS_ACK_VERIFIED" if revoke_error
            else "REVOKED_VERIFIED"
        ),
        "loginState": "DISABLED", "credentialState": "ABSENT",
        "activeSessions": 0,
    }


@dataclass(repr=False)
class CredentialLease:
    source_fd: int
    dump_fd: int
    expires_at: dt.datetime
    lease_nonce: str
    source_netns_inode: int
    system_identifier: str
    _admin_dsn: str
    _admin_input_dsn: str
    _admin_passfile_fd: int
    _lock_conn: Any
    _observation_dsn: str
    _container: str
    _expected_container_id: str
    _expected_image_id: str
    _require_healthy: bool
    _binding: RuntimeBinding
    _mutation_binding: MutationBinding
    _allow_contract_container: bool
    _source_fd_identity: tuple[int, int]
    _dump_fd_identity: tuple[int, int]
    _admin_passfile_fd_identity: tuple[int, int]
    _closed: bool = False
    _mutex: threading.Lock = field(
        default_factory=threading.Lock, init=False, repr=False
    )

    def close(self) -> dict[str, Any]:
        with self._mutex:
            return self._close_locked()

    def _close_locked(self) -> dict[str, Any]:
        if self._closed:
            return {
                "status": "ALREADY_REVOKED", "loginState": "DISABLED",
                "credentialState": "ABSENT",
            }
        descriptor_binding_lost = False
        try:
            try:
                _assert_runtime_lock(self._lock_conn)
                _state, cleanup_deadline = _reconcile_role_auth_state(
                    self._lock_conn
                )
                minimal = _minimal_mutation_binding(
                    observation_dsn=self._observation_dsn,
                    admin_input_dsn=self._admin_input_dsn,
                    lock_conn=self._lock_conn,
                    container=self._container,
                    expected_container_id=self._expected_container_id,
                    expected_image_id=self._expected_image_id,
                    require_healthy=self._require_healthy,
                    allow_contract_container=self._allow_contract_container,
                    lock_expires_at=cleanup_deadline,
                )
                if minimal != self._mutation_binding:
                    raise RuntimeContractError("REVOCATION_TARGET_CHANGED")
                result, self._lock_conn = _force_dormant_bound(
                    observation_dsn=self._observation_dsn,
                    admin_dsn=self._admin_dsn,
                    admin_input_dsn=self._admin_input_dsn,
                    lock_conn=self._lock_conn,
                    expected=self._mutation_binding,
                    container=self._container,
                    expected_container_id=self._expected_container_id,
                    expected_image_id=self._expected_image_id,
                    require_healthy=self._require_healthy,
                    allow_contract_container=self._allow_contract_container,
                    lock_expires_at=cleanup_deadline,
                )
            except BaseException:
                if self._lock_conn is not None:
                    try:
                        self._lock_conn.close()
                    except BaseException:
                        pass
                    self._lock_conn = None
                reconciled = reconcile_credential(
                    observation_dsn=self._observation_dsn,
                    admin_dsn=self._admin_input_dsn,
                    container=self._container,
                    expected_container_id=self._expected_container_id,
                    expected_image_id=self._expected_image_id,
                    require_healthy=self._require_healthy,
                    allow_contract_container=self._allow_contract_container,
                )
                result = {
                    "status": reconciled["status"],
                    "loginState": reconciled["loginState"],
                    "credentialState": reconciled["credentialState"],
                    "activeSessions": reconciled["activeSessions"],
                }
            try:
                post = _exact_runtime_binding(
                    observation_dsn=self._observation_dsn,
                    admin_dsn=self._admin_dsn,
                    admin_input_dsn=self._admin_input_dsn,
                    container=self._container,
                    expected_container_id=self._expected_container_id,
                    expected_image_id=self._expected_image_id,
                    require_healthy=self._require_healthy,
                    allow_contract_container=self._allow_contract_container,
                    expected_login=False,
                )
            except BaseException:
                raise RuntimeContractError(
                    "CREDENTIAL_REVOKED_POSTVERIFY_DRIFT"
                ) from None
            if post != self._binding:
                raise RuntimeContractError(
                    "CREDENTIAL_REVOKED_POSTVERIFY_DRIFT"
                )
            self._closed = True
            return result
        except BaseException as exc:
            reason = (
                str(exc) if isinstance(exc, RuntimeContractError)
                else "CREDENTIAL_REVOKE_UNCERTAIN"
            )
            raise RuntimeContractError(reason) from None
        finally:
            for name, identity in (
                ("source_fd", self._source_fd_identity),
                ("dump_fd", self._dump_fd_identity),
            ):
                fd = getattr(self, name)
                if fd >= 0:
                    try:
                        metadata = os.fstat(fd)
                        if (metadata.st_dev, metadata.st_ino) != identity:
                            descriptor_binding_lost = True
                        else:
                            os.close(fd)
                    except OSError:
                        descriptor_binding_lost = True
                    finally:
                        setattr(self, name, -1)
            if self._admin_passfile_fd >= 0:
                try:
                    metadata = os.fstat(self._admin_passfile_fd)
                    if (metadata.st_dev, metadata.st_ino) != \
                            self._admin_passfile_fd_identity:
                        descriptor_binding_lost = True
                    else:
                        os.close(self._admin_passfile_fd)
                except OSError:
                    descriptor_binding_lost = True
                self._admin_passfile_fd = -1
            if self._lock_conn is not None:
                self._lock_conn.close()
                self._lock_conn = None
            if descriptor_binding_lost:
                raise RuntimeContractError("CREDENTIAL_FD_BINDING_LOST")

    def __enter__(self) -> "CredentialLease":
        return self

    def __exit__(self, _exc_type: Any, _exc: Any, _tb: Any) -> None:
        self.close()


@dataclass(repr=False)
class ProductionSourceAdapter:
    """Exact SourceAdapter backed by one issued two-memfd lease.

    Production LOGIN activation is deliberately impossible in this version;
    the same adapter is rehearsed against an allowlisted disposable container.
    """

    lease: CredentialLease = field(repr=False)
    _process: subprocess.Popen[bytes] | None = field(
        default=None, init=False, repr=False
    )
    _closed: bool = field(default=False, init=False, repr=False)
    _close_evidence: dict[str, Any] | None = field(
        default=None, init=False, repr=False
    )
    _mutex: threading.Lock = field(
        default_factory=threading.Lock, init=False, repr=False
    )

    @property
    def production_contact(self) -> bool:
        return not self.lease._allow_contract_container

    def _kill_helper(self) -> bool:
        process = self._process
        if process is None:
            return True
        try:
            if process.poll() is None:
                process.kill()
            try:
                process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate(timeout=5)
        except BaseException:
            return process.poll() is not None
        return process.poll() is not None

    def _read_export_report(self, deadline: float) -> dict[str, Any]:
        process = self._process
        if process is None or process.stdout is None:
            raise RuntimeContractError("SOURCE_HELPER_NOT_STARTED")
        fd = process.stdout.fileno()
        payload = b""
        while b"\n" not in payload:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeContractError("SOURCE_HELPER_START_TIMEOUT")
            ready, _, _ = select.select([fd], [], [], remaining)
            if not ready:
                raise RuntimeContractError("SOURCE_HELPER_START_TIMEOUT")
            chunk = os.read(fd, 8193 - len(payload))
            if not chunk:
                raise RuntimeContractError("SOURCE_HELPER_EARLY_EXIT")
            payload += chunk
            if len(payload) > 8192:
                raise RuntimeContractError("SOURCE_HELPER_REPORT_TOO_LARGE")
        line, remainder = payload.split(b"\n", 1)
        if remainder or not line:
            raise RuntimeContractError("SOURCE_HELPER_PROTOCOL_INVALID")
        try:
            report = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeContractError("SOURCE_HELPER_PROTOCOL_INVALID") from exc
        if not isinstance(report, dict):
            raise RuntimeContractError("SOURCE_HELPER_PROTOCOL_INVALID")
        return report

    def open(
        self, plan: Mapping[str, Any], secret_fd: int, deadline: float,
    ) -> tuple[Mapping[str, Any], str]:
        with self._mutex:
            return self._open_locked(plan, secret_fd, deadline)

    def _open_locked(
        self, plan: Mapping[str, Any], secret_fd: int, deadline: float,
    ) -> tuple[Mapping[str, Any], str]:
        if self._closed or self._process is not None:
            raise RuntimeContractError("SOURCE_ADAPTER_STATE_INVALID")
        if type(deadline) is not float or deadline <= time.monotonic():
            raise RuntimeContractError("SOURCE_ADAPTER_DEADLINE_INVALID")
        secret = _validate_credential_fd(secret_fd)
        owner_secret = _validate_credential_fd(self.lease.source_fd)
        dump_secret = _validate_credential_fd(self.lease.dump_fd)
        if ((secret.st_dev, secret.st_ino)
                != (owner_secret.st_dev, owner_secret.st_ino)
                or (secret.st_dev, secret.st_ino)
                == (dump_secret.st_dev, dump_secret.st_ino)):
            raise RuntimeContractError("SOURCE_CREDENTIAL_BINDING_MISMATCH")
        frozen = _load_and_bind_plan()
        try:
            supplied = json.dumps(
                dict(plan), sort_keys=True, separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
            expected = json.dumps(
                frozen, sort_keys=True, separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise RuntimeContractError("SOURCE_PLAN_INVALID") from exc
        if supplied != expected:
            raise RuntimeContractError("SOURCE_PLAN_BINDING_MISMATCH")
        container = self.lease._binding.container
        helper_deadline = min(
            deadline,
            time.monotonic() + max(
                0.0, self.lease.expires_at.timestamp() - time.time()
            ),
        )
        interpreter = Path("/usr/bin/python3")
        nsenter = Path("/usr/bin/nsenter")
        for executable in (interpreter, nsenter):
            metadata = executable.stat()
            if (not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != 0
                    or stat.S_IMODE(metadata.st_mode) & 0o022):
                raise RuntimeContractError("SOURCE_HELPER_EXECUTABLE_UNSAFE")
        script_fd = os.open(
            Path(__file__), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        )
        script_metadata = os.fstat(script_fd)
        script_digest = hashlib.sha256()
        try:
            if (not stat.S_ISREG(script_metadata.st_mode)
                    or script_metadata.st_uid != 0
                    or stat.S_IMODE(script_metadata.st_mode) & 0o022):
                raise RuntimeContractError("SOURCE_HELPER_SCRIPT_UNSAFE")
            while True:
                chunk = os.read(script_fd, 1024 * 1024)
                if not chunk:
                    break
                script_digest.update(chunk)
            os.lseek(script_fd, 0, os.SEEK_SET)
            if script_digest.hexdigest() != frozen["artifactsSha256"][
                    "snapshotReaderRuntime"]:
                raise RuntimeContractError("SOURCE_HELPER_SCRIPT_DRIFT")
        except BaseException:
            os.close(script_fd)
            raise
        command = [
            "/usr/bin/nsenter", "--target",
            str(container["containerPid"]), "--net",
            "/usr/bin/python3", f"/proc/self/fd/{script_fd}",
            "--export-helper", "--credential-fd", str(secret_fd),
            "--expires-at", self.lease.expires_at.isoformat(),
            "--lease-nonce", self.lease.lease_nonce,
            "--expected-netns-inode", str(self.lease.source_netns_inode),
            "--expected-system-identifier", self.lease.system_identifier,
        ]
        environment = {
            "PATH": "/usr/bin:/bin",
            "PYTHONPATH": "/usr/lib/python3/dist-packages",
            "LC_ALL": "C",
        }
        try:
            try:
                self._process = subprocess.Popen(
                    command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE, pass_fds=(secret_fd, script_fd),
                    close_fds=True, env=environment,
                )
            finally:
                os.close(script_fd)
            report = self._read_export_report(helper_deadline)
            role = inspect_role(self.lease._admin_dsn, expected_login=True)
            rebound = _exact_runtime_binding(
                observation_dsn=self.lease._observation_dsn,
                admin_dsn=self.lease._admin_dsn,
                admin_input_dsn=self.lease._admin_input_dsn,
                container=self.lease._container,
                expected_container_id=self.lease._expected_container_id,
                expected_image_id=self.lease._expected_image_id,
                require_healthy=self.lease._require_healthy,
                allow_contract_container=self.lease._allow_contract_container,
                expected_login=True,
            )
        except BaseException:
            helper_clean = self._kill_helper()
            try:
                revoked = self.lease.close()
                self._closed = True
            except BaseException:
                raise RuntimeContractError(
                    "SOURCE_ADAPTER_OPEN_REVOKE_UNCERTAIN"
                ) from None
            self._close_evidence = {
                "sourceSessionClosed": helper_clean,
                "credentialRevocationAttested": True,
                "loginState": revoked.get("loginState"),
                "credentialState": revoked.get("credentialState"),
                "activeSessions": revoked.get("activeSessions"),
            }
            raise RuntimeContractError("SOURCE_ADAPTER_OPEN_FAILED") from None
        expected_report = {
            "clientAddress": "127.0.0.1/32",
            "customerRowsRead": False,
            "database": DATABASE,
            "isolation": "repeatable read",
            "readOnly": True,
            "sessionAttestation": report.get("sessionAttestation"),
            "snapshot": report.get("snapshot"),
            "status": "SNAPSHOT_EXPORTED_HELD",
            "user": ROLE,
        }
        inventory = role.get("inventory", {})
        expected_session = {
            "roleCanLogin": True, "roleSuperuser": False,
            "roleCreateDb": False, "roleCreateRole": False,
            "roleInherit": False, "roleReplication": False,
            "roleBypassRls": False, "roleConnectionLimit": 2,
            "roleMemberships": [], "roleSettingsMatch": True,
            "databaseConnect": True, "databaseCreate": False,
            "databaseTemp": False, "schemaUsage": True,
            "schemaCreate": False,
            "publicTables": inventory.get("tables"),
            "publicColumns": inventory.get("columns"),
            "publicSequences": inventory.get("sequences"),
            "rlsTables": 0, "largeObjects": 0,
            "columnCatalogSha256": role.get("columnCatalogSha256"),
            "selectablePublicTables": inventory.get("tables"),
            "tableWritePrivileges": 0,
            "selectablePublicSequences": inventory.get("sequences"),
            "sequenceUsageOrUpdatePrivileges": 0,
            "userFunctionExecutePrivileges": 0,
            "otherSchemaPrivileges": 0,
        }
        attestation_failure = None
        if json.dumps(report, sort_keys=True, separators=(",", ":")) != \
                json.dumps(
                    expected_report, sort_keys=True, separators=(",", ":")
                ):
            attestation_failure = "SOURCE_ADAPTER_REPORT_MISMATCH"
        elif report.get("sessionAttestation") != expected_session:
            observed_session = report.get("sessionAttestation")
            if (not isinstance(observed_session, dict)
                    or set(observed_session) != set(expected_session)):
                attestation_failure = "SOURCE_SESSION_SHAPE_MISMATCH"
            else:
                mismatch = next(
                    key for key, expected_value in expected_session.items()
                    if (type(observed_session[key]) is not type(expected_value)
                        or observed_session[key] != expected_value)
                )
                safe_field = re.sub(
                    r"[^A-Z0-9]+", "_", mismatch.upper()
                ).strip("_")
                attestation_failure = (
                    f"SOURCE_SESSION_{safe_field}_MISMATCH"
                )
        elif rebound != self.lease._binding:
            attestation_failure = "SOURCE_RUNTIME_BINDING_MISMATCH"
        elif role.get("status") != "match":
            attestation_failure = "SOURCE_ROLE_VERIFICATION_MISMATCH"
        elif role.get("hbaIsolationStatus") != "EXACT":
            attestation_failure = "SOURCE_HBA_ATTESTATION_MISMATCH"
        elif role.get("profile") != "FROZEN_001_023_SOURCE_PROFILE":
            attestation_failure = "SOURCE_PROFILE_MISMATCH"
        elif role.get("profileInventorySha256") != (
                "cd65edefff6708dcb58b33fa554f8c19895f3312271819cce5eace9a276d7893"):
            attestation_failure = "SOURCE_PROFILE_INVENTORY_MISMATCH"
        if attestation_failure is not None:
            helper_clean = self._kill_helper()
            try:
                revoked = self.lease.close()
                self._closed = True
            except BaseException:
                raise RuntimeContractError(
                    "SOURCE_ADAPTER_ATTESTATION_REVOKE_UNCERTAIN"
                ) from None
            self._close_evidence = {
                "sourceSessionClosed": helper_clean,
                "credentialRevocationAttested": True,
                "loginState": revoked.get("loginState"),
                "credentialState": revoked.get("credentialState"),
                "activeSessions": revoked.get("activeSessions"),
            }
            raise RuntimeContractError(attestation_failure)
        cluster_material = (
            f"{self.lease.system_identifier}:"
            f"{rebound.cluster['postmasterStartTime'].isoformat()}"
        ).encode("ascii")
        session = report["sessionAttestation"]
        attestation = {
            "database": DATABASE,
            "serverMajor": 17,
            "clusterSha256": hashlib.sha256(cluster_material).hexdigest(),
            "sourceContainerId": container["containerId"],
            "sourceContainerImageSha256":
                container["imageId"].removeprefix("sha256:"),
            "transactionReadOnly": True,
            "transactionIsolation": "repeatable read",
            "snapshotReaderVerifierStatus": "match",
            "snapshotReaderProfile": role["profile"],
            "snapshotReaderInventorySha256": role["profileInventorySha256"],
            "aclVerifiedInExportingTransaction": True,
            "exclusiveDatabaseConnectivity": True,
            "hbaFirstMatchAttested": True,
            "roleCredentialAuthenticated": True,
            "credentialExpiryBound": True,
            "credentialNotAfterEpoch": int(
                self.lease.expires_at.timestamp()
            ),
            "credentialRevocationPending": True,
            "sessionUser": ROLE,
            "currentUser": ROLE,
            **session,
        }
        return attestation, _snapshot(report["snapshot"])

    def close(self) -> Mapping[str, Any]:
        with self._mutex:
            return self._close_locked()

    def _close_locked(self) -> Mapping[str, Any]:
        if self._closed:
            if self._close_evidence is None:
                raise RuntimeContractError("SOURCE_CLOSE_EVIDENCE_MISSING")
            if not self._close_evidence["sourceSessionClosed"]:
                self._close_evidence["sourceSessionClosed"] = \
                    self._kill_helper()
                if self._close_evidence["sourceSessionClosed"]:
                    self._process = None
            return dict(self._close_evidence)
        helper_clean = self._process is None
        process = self._process
        revoked: Mapping[str, Any] | None = None
        try:
            if process is not None and process.poll() is None:
                try:
                    if process.stdin is None:
                        raise RuntimeContractError(
                            "SOURCE_HELPER_STDIN_MISSING"
                        )
                    process.stdin.write(b"CLOSE\n")
                    process.stdin.flush()
                    process.communicate(timeout=10)
                    helper_clean = process.poll() is not None
                except BaseException:
                    helper_clean = self._kill_helper()
            elif process is not None:
                helper_clean = process.poll() is not None
        finally:
            revoked = self.lease.close()
        if revoked is None:
            raise RuntimeContractError("SOURCE_CREDENTIAL_REVOKE_UNCERTAIN")
        if (revoked.get("loginState") != "DISABLED"
                or revoked.get("credentialState") != "ABSENT"
                or revoked.get("activeSessions") != 0):
            raise RuntimeContractError("SOURCE_CREDENTIAL_REVOKE_UNCERTAIN")
        self._closed = True
        if helper_clean:
            self._process = None
        self._close_evidence = {
            "sourceSessionClosed": helper_clean,
            "credentialRevocationAttested": True,
            "loginState": "DISABLED",
            "credentialState": "ABSENT",
            "activeSessions": 0,
        }
        return dict(self._close_evidence)


def issue_credential_lease(
    *, observation_dsn: str, admin_dsn: str, container: str,
    expected_container_id: str, expected_image_id: str,
    ttl_seconds: int = 90, require_healthy: bool = True,
    allow_contract_container: bool = False,
) -> CredentialLease:
    """Issue one short lease after exact dormant/HBA/container preflight."""
    if (type(ttl_seconds) is not int
            or not MIN_TTL_SECONDS <= ttl_seconds <= MAX_TTL_SECONDS):
        raise RuntimeContractError("INVALID_CREDENTIAL_TTL")
    if allow_contract_container and not re.fullmatch(
            r"b64-hba-contract-[0-9]+", container):
        raise RuntimeContractError("CONTRACT_CONTAINER_NAME_INVALID")
    if not allow_contract_container:
        raise RuntimeContractError(
            "PRODUCTION_LOGIN_ACTIVATION_NOT_AUTHORIZED"
        )
    _validate_observation_dsn_secret_boundary(observation_dsn)
    initial_container = _inspect_container(
        container, expected_container_id, expected_image_id,
        require_healthy, observation_dsn,
    )
    _validate_container_admin_dsn(
        admin_dsn, DATABASE, initial_container["containerPid"]
    )
    passfile_fd, bound_admin_dsn = _bind_empty_memfd_passfile(admin_dsn)
    source_fd = -1
    dump_fd = -1
    lock_conn = None
    transferred = False
    issuance_attempted = False
    lease_nonce = secrets.token_hex(16)
    try:
        lock_conn = _acquire_runtime_lock(bound_admin_dsn, lease_nonce)
        mutation_binding = _minimal_mutation_binding(
            observation_dsn=observation_dsn, admin_input_dsn=admin_dsn,
            lock_conn=lock_conn, container=container,
            expected_container_id=expected_container_id,
            expected_image_id=expected_image_id,
            require_healthy=require_healthy,
            allow_contract_container=allow_contract_container,
        )
        state = _role_auth_state_on(lock_conn)
        dormant = (
            state["login"] is False
            and state["passwordAbsent"] is True
            and state["sessions"] == 0
            and state["validUntil"] in {"", "infinity"}
        )
        if not dormant:
            _result, lock_conn = _force_dormant_bound(
                observation_dsn=observation_dsn,
                admin_dsn=bound_admin_dsn,
                admin_input_dsn=admin_dsn, lock_conn=lock_conn,
                expected=mutation_binding, container=container,
                expected_container_id=expected_container_id,
                expected_image_id=expected_image_id,
                require_healthy=require_healthy,
                allow_contract_container=allow_contract_container,
            )
        binding = _exact_runtime_binding(
            observation_dsn=observation_dsn, admin_dsn=bound_admin_dsn,
            admin_input_dsn=admin_dsn,
            container=container, expected_container_id=expected_container_id,
            expected_image_id=expected_image_id,
            require_healthy=require_healthy,
            allow_contract_container=allow_contract_container,
            expected_login=False,
        )
        _assert_runtime_lock(lock_conn)
        password = base64.urlsafe_b64encode(
            secrets.token_bytes(32)
        ).rstrip(b"=")
        passline = (
            f"{HOST}:{PORT}:{DATABASE}:{ROLE}:".encode("ascii")
            + password + b"\n"
        )
        source_fd = _sealed_pgpass_memfd(
            passline, "obsidian-b64-source-pgpass"
        )
        dump_fd = _sealed_pgpass_memfd(
            passline, "obsidian-b64-dump-pgpass"
        )
        first = _validate_credential_fd(source_fd)
        second = _validate_credential_fd(dump_fd)
        if (first.st_dev, first.st_ino) == (second.st_dev, second.st_ino):
            raise RuntimeContractError("CREDENTIAL_FDS_NOT_INDEPENDENT")
        now, scram_iterations = _credential_server_state(lock_conn)
        expires_at = now + dt.timedelta(seconds=ttl_seconds)
        verifier = _scram_verifier(password, scram_iterations)
        _arm_runtime_lock_deadline(lock_conn, expires_at)
        issuance_attempted = True
        _set_short_lived_verifier(lock_conn, verifier, expires_at)
        post = _role_auth_state_on(lock_conn, expires_at)
        post_expiry = dt.datetime.fromisoformat(post["validUntil"])
        rebound = _exact_runtime_binding(
            observation_dsn=observation_dsn, admin_dsn=bound_admin_dsn,
            admin_input_dsn=admin_dsn,
            container=container, expected_container_id=expected_container_id,
            expected_image_id=expected_image_id,
            require_healthy=require_healthy,
            allow_contract_container=allow_contract_container,
            expected_login=True,
        )
        if (post["login"] is not True or post["passwordAbsent"] is not False
                or post_expiry != expires_at or post["sessions"] != 0
                or rebound != binding):
            raise RuntimeContractError("LEASE_POSTVERIFY_FAILED")
        minimal_post = _minimal_mutation_binding(
            observation_dsn=observation_dsn, admin_input_dsn=admin_dsn,
            lock_conn=lock_conn, container=container,
            expected_container_id=expected_container_id,
            expected_image_id=expected_image_id,
            require_healthy=require_healthy,
            allow_contract_container=allow_contract_container,
            lock_expires_at=expires_at,
        )
        if minimal_post != mutation_binding:
            raise RuntimeContractError("LEASE_MUTATION_TARGET_CHANGED")
        lease = CredentialLease(
            source_fd=source_fd, dump_fd=dump_fd, expires_at=expires_at,
            lease_nonce=lease_nonce,
            source_netns_inode=binding.netns_inode,
            system_identifier=binding.cluster["systemIdentifier"],
            _admin_dsn=bound_admin_dsn,
            _admin_input_dsn=admin_dsn,
            _admin_passfile_fd=passfile_fd,
            _lock_conn=lock_conn,
            _observation_dsn=observation_dsn, _container=container,
            _expected_container_id=expected_container_id,
            _expected_image_id=expected_image_id,
            _require_healthy=require_healthy,
            _binding=binding,
            _mutation_binding=mutation_binding,
            _allow_contract_container=allow_contract_container,
            _source_fd_identity=(first.st_dev, first.st_ino),
            _dump_fd_identity=(second.st_dev, second.st_ino),
            _admin_passfile_fd_identity=(
                os.fstat(passfile_fd).st_dev, os.fstat(passfile_fd).st_ino
            ),
        )
        transferred = True
        source_fd = -1
        dump_fd = -1
        passfile_fd = -1
        lock_conn = None
        return lease
    except BaseException as exc:
        if issuance_attempted:
            try:
                _assert_runtime_lock(lock_conn)
                _state, cleanup_deadline = _reconcile_role_auth_state(
                    lock_conn
                )
                _result, lock_conn = _force_dormant_bound(
                    observation_dsn=observation_dsn,
                    admin_dsn=bound_admin_dsn,
                    admin_input_dsn=admin_dsn, lock_conn=lock_conn,
                    expected=mutation_binding, container=container,
                    expected_container_id=expected_container_id,
                    expected_image_id=expected_image_id,
                    require_healthy=require_healthy,
                    allow_contract_container=allow_contract_container,
                    lock_expires_at=cleanup_deadline,
                )
            except BaseException:
                if lock_conn is not None:
                    try:
                        lock_conn.close()
                    except BaseException:
                        pass
                    lock_conn = None
                try:
                    reconcile_credential(
                        observation_dsn=observation_dsn,
                        admin_dsn=admin_dsn, container=container,
                        expected_container_id=expected_container_id,
                        expected_image_id=expected_image_id,
                        require_healthy=require_healthy,
                        allow_contract_container=allow_contract_container,
                    )
                except BaseException:
                    raise RuntimeContractError(
                        "LEASE_ISSUE_COMPENSATION_UNCERTAIN"
                    ) from None
            try:
                compensated = _exact_runtime_binding(
                    observation_dsn=observation_dsn,
                    admin_dsn=bound_admin_dsn,
                    admin_input_dsn=admin_dsn, container=container,
                    expected_container_id=expected_container_id,
                    expected_image_id=expected_image_id,
                    require_healthy=require_healthy,
                    allow_contract_container=allow_contract_container,
                    expected_login=False,
                )
                if compensated != binding:
                    raise RuntimeContractError(
                        "LEASE_ISSUE_COMPENSATION_REBIND_FAILED"
                    )
            except BaseException:
                raise RuntimeContractError(
                    "LEASE_ISSUE_FAILED_REVOKED_POSTVERIFY_DRIFT"
                ) from None
            raise RuntimeContractError("LEASE_ISSUE_FAILED_REVOKED") from None
        reason = (
            str(exc) if isinstance(exc, RuntimeContractError)
            else "LEASE_ISSUE_FAILED_DORMANT"
        )
        raise RuntimeContractError(reason) from None
    finally:
        if not transferred:
            for fd in (source_fd, dump_fd):
                if fd >= 0:
                    os.close(fd)
            if passfile_fd >= 0:
                os.close(passfile_fd)
            if lock_conn is not None:
                lock_conn.close()


def reconcile_credential(
    *, observation_dsn: str, admin_dsn: str, container: str,
    expected_container_id: str, expected_image_id: str,
    require_healthy: bool = True,
    allow_contract_container: bool = False,
) -> dict[str, Any]:
    """Revoke an abandoned/expired lease using a fresh exact binding."""
    if allow_contract_container and not re.fullmatch(
            r"b64-hba-contract-[0-9]+", container):
        raise RuntimeContractError("CONTRACT_CONTAINER_NAME_INVALID")
    before_container = _inspect_container(
        container, expected_container_id, expected_image_id,
        False, observation_dsn,
    )
    _validate_container_admin_dsn(
        admin_dsn, DATABASE, before_container["containerPid"]
    )
    passfile_fd, bound_admin_dsn = _bind_empty_memfd_passfile(admin_dsn)
    lock_conn = None
    try:
        try:
            lock_conn = _acquire_runtime_lock(
                bound_admin_dsn, secrets.token_hex(16),
                initial_idle_timeout_seconds=RECONCILE_CLEANUP_SECONDS,
            )
        except RuntimeContractError as exc:
            if str(exc) != "CREDENTIAL_RUNTIME_BUSY":
                raise
            lock_released = _evict_reader_held_runtime_lock(
                observation_dsn=observation_dsn,
                admin_dsn=bound_admin_dsn,
                admin_input_dsn=admin_dsn, container=container,
                expected_container_id=expected_container_id,
                expected_image_id=expected_image_id,
                require_healthy=require_healthy,
                allow_contract_container=allow_contract_container,
            )
            if not lock_released:
                _exact_runtime_binding(
                    observation_dsn=observation_dsn,
                    admin_dsn=bound_admin_dsn,
                    admin_input_dsn=admin_dsn, container=container,
                    expected_container_id=expected_container_id,
                    expected_image_id=expected_image_id,
                    require_healthy=require_healthy,
                    allow_contract_container=allow_contract_container,
                    expected_login=False,
                )
                return {
                    "status": "FOREIGN_LOCK_RETAINED_DORMANT_VERIFIED",
                    "loginState": "DISABLED",
                    "credentialState": "ABSENT",
                    "activeSessions": 0,
                    "customerRowsRead": False,
                }
            lock_conn = _acquire_runtime_lock(
                bound_admin_dsn, secrets.token_hex(16),
                initial_idle_timeout_seconds=RECONCILE_CLEANUP_SECONDS,
            )
        state, cleanup_deadline = _reconcile_role_auth_state(lock_conn)
        mutation_binding = _minimal_mutation_binding(
            observation_dsn=observation_dsn, admin_input_dsn=admin_dsn,
            lock_conn=lock_conn, container=container,
            expected_container_id=expected_container_id,
            expected_image_id=expected_image_id,
            require_healthy=require_healthy,
            allow_contract_container=allow_contract_container,
            lock_expires_at=cleanup_deadline,
        )
        already_dormant = (
            state["login"] is False
            and state["passwordAbsent"] is True
            and state["validUntil"] in {"", "infinity"}
            and state["sessions"] == 0
        )
        if already_dormant:
            _exact_runtime_binding(
                observation_dsn=observation_dsn,
                admin_dsn=bound_admin_dsn,
                admin_input_dsn=admin_dsn, container=container,
                expected_container_id=expected_container_id,
                expected_image_id=expected_image_id,
                require_healthy=require_healthy,
                allow_contract_container=allow_contract_container,
                expected_login=False,
            )
            return {
                "status": "ALREADY_DORMANT_VERIFIED",
                "loginState": "DISABLED", "credentialState": "ABSENT",
                "activeSessions": 0, "customerRowsRead": False,
            }
        _result, lock_conn = _force_dormant_bound(
            observation_dsn=observation_dsn,
            admin_dsn=bound_admin_dsn, admin_input_dsn=admin_dsn,
            lock_conn=lock_conn, expected=mutation_binding,
            container=container, expected_container_id=expected_container_id,
            expected_image_id=expected_image_id,
            require_healthy=require_healthy,
            allow_contract_container=allow_contract_container,
            lock_expires_at=cleanup_deadline,
        )
        try:
            _exact_runtime_binding(
                observation_dsn=observation_dsn,
                admin_dsn=bound_admin_dsn,
                admin_input_dsn=admin_dsn, container=container,
                expected_container_id=expected_container_id,
                expected_image_id=expected_image_id,
                require_healthy=require_healthy,
                allow_contract_container=allow_contract_container,
                expected_login=False,
            )
        except BaseException:
            raise RuntimeContractError(
                "CREDENTIAL_REVOKED_POSTVERIFY_DRIFT"
            ) from None
        return {
            "status": "ABANDONED_LEASE_REVOKED_VERIFIED",
            "loginState": "DISABLED", "credentialState": "ABSENT",
            "activeSessions": 0, "customerRowsRead": False,
        }
    except BaseException as exc:
        reason = (
            str(exc) if isinstance(exc, RuntimeContractError)
            else "CREDENTIAL_RECONCILE_UNCERTAIN"
        )
        raise RuntimeContractError(reason) from None
    finally:
        if lock_conn is not None:
            lock_conn.close()
        os.close(passfile_fd)


def _reject_ambient_libpq_environment() -> None:
    if any(name.startswith("PG") for name in os.environ):
        raise RuntimeContractError("AMBIENT_LIBPQ_ENVIRONMENT_FORBIDDEN")


def _helper_identity(
    lease_nonce: str, expected_netns_inode: int,
    expected_system_identifier: str, kind: str,
) -> str:
    if (re.fullmatch(r"[0-9a-f]{32}", lease_nonce) is None
            or type(expected_netns_inode) is not int
            or expected_netns_inode <= 0
            or re.fullmatch(r"[0-9]{10,32}", expected_system_identifier)
               is None
            or kind not in {"export", "import"}):
        raise RuntimeContractError("INVALID_HELPER_BINDING")
    if os.stat("/proc/self/ns/net").st_ino != expected_netns_inode:
        raise RuntimeContractError("HELPER_NETNS_MISMATCH")
    return f"{HELPER_APPLICATION_PREFIX}-{kind}-{lease_nonce}"


def _helper_connection(
    secret_fd: int, lease_nonce: str, expected_netns_inode: int,
    expected_system_identifier: str, kind: str,
):
    import psycopg

    _reject_ambient_libpq_environment()
    application_name = _helper_identity(
        lease_nonce, expected_netns_inode, expected_system_identifier, kind
    )
    try:
        # pass_fds must clear FD_CLOEXEC for this exact exec boundary; all
        # parent-owned credential descriptors are validated CLOEXEC before it.
        _validate_credential_fd(secret_fd, require_cloexec=False)
        dsn = make_conninfo(
            host=HOST, port=PORT, dbname=DATABASE, user=ROLE,
            passfile=f"/proc/self/fd/{secret_fd}", connect_timeout=5,
            sslmode="disable", require_auth="scram-sha-256",
            application_name=application_name,
            options="-c default_transaction_read_only=on",
            target_session_attrs="any",
        )
        try:
            return psycopg.connect(dsn, connect_timeout=5, autocommit=True)
        except psycopg.Error as exc:
            raise RuntimeContractError("HELPER_CONNECTION_FAILED") from exc
    finally:
        try:
            os.close(secret_fd)
        except OSError:
            pass


def _credential_expiry(value: str) -> dt.datetime:
    try:
        expiry = dt.datetime.fromisoformat(value)
    except ValueError as exc:
        raise RuntimeContractError("INVALID_CREDENTIAL_EXPIRY") from exc
    if expiry.tzinfo is None:
        raise RuntimeContractError("INVALID_CREDENTIAL_EXPIRY")
    return expiry


def _begin_transaction_with_deadline(
    conn: Any, expiry: dt.datetime, *, snapshot: str | None = None,
) -> float:
    """Arm a server-derived residual timeout and BEGIN in one Query message."""
    started = time.monotonic()
    deadline = sql.SQL(
        "WITH obsidian_deadline AS MATERIALIZED ("
        "SELECT CEIL(EXTRACT(EPOCH FROM ({}::timestamptz-"
        "clock_timestamp()))*1000)::bigint AS remaining_ms) "
        "SELECT set_config('transaction_timeout',(CASE WHEN remaining_ms "
        "BETWEEN 1 AND {} THEN remaining_ms ELSE 1 END)::text||'ms',false),"
        "remaining_ms FROM obsidian_deadline"
    ).format(
        sql.Literal(expiry.isoformat()),
        sql.Literal((MAX_TTL_SECONDS + 1) * 1000),
    )
    commands: list[Any] = [
        deadline,
        sql.SQL("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY"),
    ]
    if snapshot is not None:
        commands.append(sql.SQL("SET TRANSACTION SNAPSHOT {}").format(
            sql.Literal(_snapshot(snapshot))
        ))
    try:
        cursor = conn.execute(sql.SQL(";").join(commands))
        deadline_row = None
        while True:
            if cursor.description is not None:
                row = cursor.fetchone()
                if deadline_row is None:
                    deadline_row = row
            if not cursor.nextset():
                break
        _validated_deadlined_row(deadline_row)
    except RuntimeContractError:
        raise
    except BaseException as exc:
        raise RuntimeContractError("TRANSACTION_DEADLINE_BIND_FAILED") from exc
    return started + deadline_row[-1] / 1000


def _wait_for_export_close(conn: Any, deadline: float) -> None:
    """Read exactly CLOSE newline without any blocking step past deadline."""
    stdin_fd = sys.stdin.fileno()
    expected = b"CLOSE\n"
    received = b""
    original_flags = fcntl.fcntl(stdin_fd, fcntl.F_GETFL)
    fcntl.fcntl(stdin_fd, fcntl.F_SETFL, original_flags | os.O_NONBLOCK)
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeContractError("EXPORT_LEASE_DEADLINE_EXPIRED")
            ready, _, _ = select.select(
                [stdin_fd, conn.fileno()], [], [], remaining
            )
            if not ready:
                raise RuntimeContractError("EXPORT_LEASE_DEADLINE_EXPIRED")
            if conn.fileno() in ready:
                try:
                    conn.execute("SELECT 1")
                except BaseException as exc:
                    raise RuntimeContractError(
                        "EXPORT_SESSION_TERMINATED"
                    ) from exc
                raise RuntimeContractError("EXPORT_PROTOCOL_SOCKET_ACTIVITY")
            if stdin_fd in ready:
                try:
                    chunk = os.read(
                        stdin_fd, len(expected) - len(received) + 1
                    )
                except BlockingIOError:
                    continue
                if not chunk:
                    raise RuntimeContractError(
                        "EXPORT_CLOSE_PROTOCOL_INVALID"
                    )
                received += chunk
                if received == expected:
                    return
                if not expected.startswith(received):
                    raise RuntimeContractError(
                        "EXPORT_CLOSE_PROTOCOL_INVALID"
                    )
    finally:
        fcntl.fcntl(stdin_fd, fcntl.F_SETFL, original_flags)


def _source_session_attestation(conn: Any) -> dict[str, Any]:
    """Verify effective least privilege inside the exporting transaction."""
    role = conn.execute(
        "SELECT rolcanlogin,rolsuper,rolcreatedb,rolcreaterole,rolinherit,"
        "rolreplication,rolbypassrls,rolconnlimit FROM pg_roles "
        "WHERE rolname=current_user"
    ).fetchone()
    if role is None:
        raise RuntimeContractError("EXPORT_ROLE_ATTESTATION_FAILED")
    memberships = conn.execute(
        "SELECT granted.rolname,member.rolname FROM pg_auth_members m "
        "JOIN pg_roles granted ON granted.oid=m.roleid "
        "JOIN pg_roles member ON member.oid=m.member "
        "WHERE m.roleid=(SELECT oid FROM pg_roles WHERE rolname=current_user) "
        "OR m.member=(SELECT oid FROM pg_roles WHERE rolname=current_user) "
        "ORDER BY granted.rolname,member.rolname"
    ).fetchall()
    inventory = conn.execute(
        "SELECT "
        "(SELECT count(*) FROM pg_class c JOIN pg_namespace n "
        "ON n.oid=c.relnamespace WHERE n.nspname='public' "
        "AND c.relkind IN ('r','p')),"
        "(SELECT count(*) FROM pg_attribute a JOIN pg_class c "
        "ON c.oid=a.attrelid JOIN pg_namespace n ON n.oid=c.relnamespace "
        "WHERE n.nspname='public' AND c.relkind IN ('r','p') "
        "AND a.attnum>0 AND NOT a.attisdropped),"
        "(SELECT count(*) FROM pg_class c JOIN pg_namespace n "
        "ON n.oid=c.relnamespace WHERE n.nspname='public' "
        "AND c.relkind='S'),"
        "(SELECT count(*) FROM pg_class c JOIN pg_namespace n "
        "ON n.oid=c.relnamespace WHERE n.nspname='public' "
        "AND c.relkind IN ('r','p') AND c.relrowsecurity),"
        "(SELECT count(*) FROM pg_largeobject_metadata)"
    ).fetchone()
    column_row = conn.execute(
        "SELECT count(*),encode(sha256(convert_to(COALESCE(jsonb_agg("
        "jsonb_build_object('table',c.relname,'column',a.attname,"
        "'number',a.attnum,'type',format_type(a.atttypid,a.atttypmod),"
        "'notNull',a.attnotnull,'identity',a.attidentity::text,"
        "'generated',a.attgenerated::text,'default',"
        "pg_get_expr(d.adbin,d.adrelid,false),'collation',CASE WHEN "
        "a.attcollation=0 THEN NULL ELSE cn.nspname||'.'||coll.collname END) "
        "ORDER BY c.relname COLLATE \"C\",a.attnum),'[]'::jsonb)::text,"
        "'UTF8')),'hex') FROM pg_class c JOIN pg_namespace n "
        "ON n.oid=c.relnamespace JOIN pg_attribute a ON a.attrelid=c.oid "
        "LEFT JOIN pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum "
        "LEFT JOIN pg_collation coll ON coll.oid=a.attcollation "
        "LEFT JOIN pg_namespace cn ON cn.oid=coll.collnamespace "
        "WHERE n.nspname='public' AND c.relkind IN ('r','p') "
        "AND a.attnum>0 AND NOT a.attisdropped"
    ).fetchone()
    table_privileges = conn.execute(
        "SELECT count(*) FILTER (WHERE has_table_privilege(current_user,c.oid,"
        "'SELECT')),count(*) FILTER (WHERE "
        "has_table_privilege(current_user,c.oid,'INSERT') OR "
        "has_table_privilege(current_user,c.oid,'UPDATE') OR "
        "has_table_privilege(current_user,c.oid,'DELETE') OR "
        "has_table_privilege(current_user,c.oid,'TRUNCATE') OR "
        "has_table_privilege(current_user,c.oid,'REFERENCES') OR "
        "has_table_privilege(current_user,c.oid,'TRIGGER') OR "
        "has_table_privilege(current_user,c.oid,'MAINTAIN')) FROM pg_class c "
        "JOIN pg_namespace n ON n.oid=c.relnamespace "
        "WHERE n.nspname='public' AND c.relkind IN ('r','p')"
    ).fetchone()
    column_writes = conn.execute(
        "SELECT count(*) FROM pg_attribute a JOIN pg_class c "
        "ON c.oid=a.attrelid JOIN pg_namespace n ON n.oid=c.relnamespace "
        "WHERE n.nspname='public' AND c.relkind IN ('r','p') "
        "AND a.attnum>0 AND NOT a.attisdropped AND ("
        "has_column_privilege(current_user,c.oid,a.attname,'INSERT') OR "
        "has_column_privilege(current_user,c.oid,a.attname,'UPDATE') OR "
        "has_column_privilege(current_user,c.oid,a.attname,'REFERENCES'))"
    ).fetchone()[0]
    sequence_privileges = conn.execute(
        "SELECT count(*) FILTER (WHERE has_sequence_privilege(current_user,"
        "c.oid,'SELECT')),count(*) FILTER (WHERE "
        "has_sequence_privilege(current_user,c.oid,'USAGE') OR "
        "has_sequence_privilege(current_user,c.oid,'UPDATE')) "
        "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
        "WHERE n.nspname='public' AND c.relkind='S'"
    ).fetchone()
    function_execute = conn.execute(
        "SELECT count(*) FROM pg_proc p JOIN pg_namespace n "
        "ON n.oid=p.pronamespace WHERE n.nspname='public' "
        "AND has_function_privilege(current_user,p.oid,'EXECUTE')"
    ).fetchone()[0]
    other_schema_privileges = conn.execute(
        "SELECT "
        "(SELECT count(*) FROM pg_namespace n WHERE n.nspname<>'public' "
        "AND n.nspname<>'information_schema' AND n.nspname!~'^pg_' AND ("
        "has_schema_privilege(current_user,n.oid,'USAGE') OR "
        "has_schema_privilege(current_user,n.oid,'CREATE'))) + "
        "(SELECT count(*) FROM pg_class c JOIN pg_namespace n "
        "ON n.oid=c.relnamespace WHERE n.nspname<>'public' "
        "AND n.nspname<>'information_schema' AND n.nspname!~'^pg_' "
        "AND c.relkind IN ('r','p','v','m','f','S') AND (CASE WHEN "
        "c.relkind='S' THEN has_sequence_privilege(current_user,c.oid,"
        "'SELECT,USAGE,UPDATE') ELSE has_table_privilege(current_user,c.oid,"
        "'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER,MAINTAIN') "
        "END)) + (SELECT count(*) FROM pg_proc p JOIN pg_namespace n "
        "ON n.oid=p.pronamespace WHERE n.nspname<>'public' "
        "AND n.nspname<>'information_schema' AND n.nspname!~'^pg_' "
        "AND has_function_privilege(current_user,p.oid,'EXECUTE'))"
    ).fetchone()[0]
    database_privileges = conn.execute(
        "SELECT has_database_privilege(current_user,current_database(),"
        "'CONNECT'),has_database_privilege(current_user,current_database(),"
        "'CREATE'),has_database_privilege(current_user,current_database(),"
        "'TEMPORARY'),has_schema_privilege(current_user,'public','USAGE'),"
        "has_schema_privilege(current_user,'public','CREATE')"
    ).fetchone()
    settings = conn.execute(
        "SELECT current_setting('search_path'),"
        "current_setting('default_transaction_read_only')::boolean,"
        "current_setting('default_transaction_isolation'),"
        "current_setting('statement_timeout')::interval="
        "interval '180 seconds',"
        "current_setting('lock_timeout')::interval=interval '5 seconds',"
        "current_setting('idle_in_transaction_session_timeout')::interval="
        "interval '210 seconds',"
        "current_setting('row_security')::boolean"
    ).fetchone()
    return {
        "roleCanLogin": role[0], "roleSuperuser": role[1],
        "roleCreateDb": role[2], "roleCreateRole": role[3],
        "roleInherit": role[4], "roleReplication": role[5],
        "roleBypassRls": role[6], "roleConnectionLimit": role[7],
        "roleMemberships": [list(item) for item in memberships],
        "roleSettingsMatch": settings == (
            "pg_catalog", True, "repeatable read", True, True, True, False,
        ),
        "databaseConnect": database_privileges[0],
        "databaseCreate": database_privileges[1],
        "databaseTemp": database_privileges[2],
        "schemaUsage": database_privileges[3],
        "schemaCreate": database_privileges[4],
        "publicTables": inventory[0], "publicColumns": inventory[1],
        "publicSequences": inventory[2], "rlsTables": inventory[3],
        "largeObjects": inventory[4],
        "columnCatalogSha256": column_row[1],
        "selectablePublicTables": table_privileges[0],
        "tableWritePrivileges": table_privileges[1] + column_writes,
        "selectablePublicSequences": sequence_privileges[0],
        "sequenceUsageOrUpdatePrivileges": sequence_privileges[1],
        "userFunctionExecutePrivileges": function_execute,
        "otherSchemaPrivileges": other_schema_privileges,
    }


def _export_helper(
    secret_fd: int, expires_at: str, lease_nonce: str,
    expected_netns_inode: int, expected_system_identifier: str,
) -> int:
    import psycopg

    expected_expiry = _credential_expiry(expires_at)
    application_name = _helper_identity(
        lease_nonce, expected_netns_inode,
        expected_system_identifier, "export",
    )
    with _helper_connection(
        secret_fd, lease_nonce, expected_netns_inode,
        expected_system_identifier, "export",
    ) as conn:
        try:
            deadline = _begin_transaction_with_deadline(
                conn, expected_expiry
            )
            row = conn.execute(
                "SELECT current_user,session_user,current_database(),"
                "inet_client_addr()::text,"
                "current_setting('transaction_read_only'),"
                "current_setting('transaction_isolation'),"
                "pg_export_snapshot(),rolvaliduntil,"
                "current_setting('application_name'),"
                "(SELECT system_identifier::text FROM pg_control_system()) "
                "FROM pg_roles "
                "WHERE rolname=current_user"
            ).fetchone()
        except psycopg.Error as exc:
            raise RuntimeContractError("EXPORT_TRANSACTION_FAILED") from exc
        if (row[:6] != (
                ROLE, ROLE, DATABASE, "127.0.0.1/32", "on",
                "repeatable read") or row[7] != expected_expiry
                or row[8] != application_name
                or row[9] != expected_system_identifier):
            raise RuntimeContractError("EXPORT_SESSION_ATTESTATION_FAILED")
        session_attestation = _source_session_attestation(conn)
        report = {
            "status": "SNAPSHOT_EXPORTED_HELD",
            "user": row[0], "database": row[2],
            "clientAddress": row[3], "readOnly": True,
            "isolation": row[5], "snapshot": _snapshot(row[6]),
            "sessionAttestation": session_attestation,
            "customerRowsRead": False,
        }
        print(json.dumps(report, sort_keys=True), flush=True)
        _wait_for_export_close(conn, deadline)
        conn.execute("ROLLBACK")
    return 0


def _import_helper(secret_fd: int, snapshot: str,
                   expires_at: str, lease_nonce: str,
                   expected_netns_inode: int,
                   expected_system_identifier: str) -> int:
    import psycopg

    checked_snapshot = _snapshot(snapshot)
    expected_expiry = _credential_expiry(expires_at)
    application_name = _helper_identity(
        lease_nonce, expected_netns_inode,
        expected_system_identifier, "import",
    )
    with _helper_connection(
        secret_fd, lease_nonce, expected_netns_inode,
        expected_system_identifier, "import",
    ) as conn:
        try:
            _begin_transaction_with_deadline(
                conn, expected_expiry, snapshot=checked_snapshot
            )
            row = conn.execute(
                "SELECT current_user,current_database(),"
                "inet_client_addr()::text,"
                "current_setting('transaction_read_only'),"
                "current_setting('transaction_isolation'),rolvaliduntil,"
                "current_setting('application_name'),"
                "(SELECT system_identifier::text FROM pg_control_system()) "
                "FROM pg_roles WHERE rolname=current_user"
            ).fetchone()
        except psycopg.Error as exc:
            raise RuntimeContractError("IMPORT_TRANSACTION_FAILED") from exc
        if (row != (
                ROLE, DATABASE, "127.0.0.1/32", "on",
                "repeatable read", expected_expiry, application_name,
                expected_system_identifier)):
            raise RuntimeContractError("IMPORT_SESSION_ATTESTATION_FAILED")
        conn.execute("ROLLBACK")
    print(json.dumps({
        "status": "SNAPSHOT_IMPORTED",
        "user": ROLE, "database": DATABASE,
        "clientAddress": "127.0.0.1/32", "readOnly": True,
        "isolation": "repeatable read", "customerRowsRead": False,
    }, sort_keys=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    operation = parser.add_mutually_exclusive_group(required=True)
    operation.add_argument("--export-helper", action="store_true")
    operation.add_argument("--import-helper", action="store_true")
    parser.add_argument("--credential-fd", type=int, required=True)
    parser.add_argument("--expires-at", required=True)
    parser.add_argument("--lease-nonce", required=True)
    parser.add_argument("--expected-netns-inode", type=int, required=True)
    parser.add_argument("--expected-system-identifier", required=True)
    parser.add_argument("--snapshot")
    args = parser.parse_args()
    try:
        if args.export_helper:
            if args.snapshot is not None:
                raise RuntimeContractError("UNEXPECTED_SNAPSHOT_ARGUMENT")
            return _export_helper(
                args.credential_fd, args.expires_at, args.lease_nonce,
                args.expected_netns_inode, args.expected_system_identifier,
            )
        if args.snapshot is None:
            raise RuntimeContractError("SNAPSHOT_ARGUMENT_REQUIRED")
        return _import_helper(
            args.credential_fd, args.snapshot, args.expires_at,
            args.lease_nonce, args.expected_netns_inode,
            args.expected_system_identifier,
        )
    except BaseException as exc:
        print(json.dumps({
            "status": "ERROR", "reason": _safe_reason(exc),
            "credentialExposed": False, "customerRowsRead": False,
        }, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
