#!/usr/bin/env python3
"""Fail-closed boot and abnormal-exit reconciliation for the B64 reader.

The watchdog uses only the container-local PostgreSQL admin socket.  It owns no
password and never enables LOGIN.  A valid short lease is deferred while its
exact advisory-lock holder and server expiry are present; every orphaned or
expired authority state is reduced to NOLOGIN/PASSWORD NULL and zero sessions.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
from typing import Any

from psycopg import sql

from b64_snapshot_reader_runtime_rebind import (
    DATABASE,
    EXPECTED_DEPLOYED_HBA_SHA256,
    HOST_LOCK_PATH,
    PRODUCTION_CONTAINER,
    PRODUCTION_SYSTEM_IDENTIFIER,
    PRODUCTION_VOLUME,
    ROLE,
    RebindError,
    _host_lock,
    _open_bundle,
    _safe_reason,
    _validate_journal,
    admin_connection,
    inspect_container,
    rebind_runtime,
)
from verify_b64_snapshot_reader import inspect as inspect_role


RUNTIME_ADVISORY_LOCK_KEY = 664064017023001
LOCK_APPLICATION_PREFIX = "obsidian-b64-lease-lock"
MAX_TTL_SECONDS = 180
EXPIRY_GRACE_SECONDS = 2
class WatchdogError(RebindError):
    """Closed watchdog reason code safe for journald."""


def _role_state(
    conn: Any,
    *,
    expected_server_version_num: int,
    expected_system_identifier: str,
) -> dict[str, Any]:
    row = conn.execute(
        "SELECT current_user,current_database(),r.rolsuper,r.rolcreaterole,"
        "current_setting('transaction_read_only'),inet_client_addr() IS NULL,"
        "current_setting('server_version_num')::int,"
        "current_setting('data_directory'),current_setting('hba_file'),"
        "system_identifier::text,pg_postmaster_start_time(),clock_timestamp(),"
        "target.oid,target.rolcanlogin,(auth.rolpassword IS NULL),"
        "COALESCE(auth.rolvaliduntil::text,''),target.rolconnlimit,"
        "(SELECT count(*) FROM pg_stat_activity WHERE usename=%s) "
        "FROM pg_roles r CROSS JOIN pg_control_system() "
        "JOIN pg_roles target ON target.rolname=%s "
        "JOIN pg_authid auth ON auth.oid=target.oid WHERE r.rolname=current_user",
        (ROLE, ROLE),
    ).fetchone()
    if (
        row is None
        or row[:6] != ("postgres", DATABASE, True, True, "off", True)
        or row[6] != expected_server_version_num
        or row[7] != "/var/lib/postgresql/data"
        or row[8] != "/var/lib/postgresql/data/pg_hba.conf"
        or row[9] != expected_system_identifier
        or not isinstance(row[12], int)
        or row[12] <= 0
        or row[16] != 2
        or not isinstance(row[17], int)
        or not 0 <= row[17] <= 2
    ):
        raise WatchdogError("WATCHDOG_SERVER_BINDING_MISMATCH")
    dormant = (
        row[13] is False and row[14] is True
        and row[15] in {"", "infinity"} and row[17] == 0
    )
    active = (
        row[13] is True
        and row[14] is False
        and isinstance(row[15], str)
        and row[15] not in {"", "infinity"}
        and 0 <= row[17] <= 2
    )
    if not dormant and not active:
        authority = "INCONSISTENT"
    elif dormant:
        authority = "DORMANT"
    else:
        authority = "ACTIVE_LEASE"
    valid_until = None
    if active:
        try:
            valid_until = dt.datetime.fromisoformat(row[15])
        except ValueError as exc:
            raise WatchdogError("WATCHDOG_LEASE_EXPIRY_INVALID") from exc
        if valid_until.tzinfo is None:
            raise WatchdogError("WATCHDOG_LEASE_EXPIRY_INVALID")
    return {
        "serverVersionNum": row[6],
        "systemIdentifier": row[9],
        "postmasterStartTime": row[10],
        "serverNow": row[11],
        "roleOid": row[12],
        "login": row[13],
        "passwordAbsent": row[14],
        "validUntil": valid_until,
        "connectionLimit": row[16],
        "sessions": row[17],
        "authority": authority,
    }


def _validate_runtime_bundle(
    container: dict[str, Any],
    expected_system_identifier: str,
    *,
    container_name: str,
    expected_image_id: str,
    expected_volume_name: str,
    expected_server_version_num: int,
    allow_contract_container: bool,
) -> None:
    pgdata_fd, state_fd, journal, pending, ownership_rebind = _open_bundle(container)
    try:
        _validate_journal(
            journal,
            allowed_container_ids={journal.get("containerId", "")},
            allowed_image_ids={expected_image_id},
            expected_system_identifier=expected_system_identifier,
        )
    finally:
        os.close(state_fd)
        os.close(pgdata_fd)
    if journal["containerId"] != container["containerId"]:
        raise WatchdogError("WATCHDOG_JOURNAL_CONTAINER_BINDING_MISMATCH")
    if (
        journal["containerPid"] != container["containerPid"]
        or pending is not None
        or ownership_rebind
    ):
        result = rebind_runtime(
            container_name=container_name,
            expected_image_id=expected_image_id,
            expected_volume_name=expected_volume_name,
            previous_container_id=container["containerId"],
            previous_image_id=expected_image_id,
            expected_server_version_num=expected_server_version_num,
            expected_system_identifier=expected_system_identifier,
            apply=True,
            allow_contract_container=allow_contract_container,
            host_lock_held=True,
        )
        if result["status"] not in {
            "RUNTIME_REBOUND_VERIFIED",
            "RUNTIME_REBIND_RECOVERED_VERIFIED",
            "RUNTIME_REBIND_TEMP_CLEANED_VERIFIED",
            "RUNTIME_REBIND_INVALID_TEMP_CLEANED_VERIFIED",
            "ALREADY_RUNTIME_BOUND",
        }:
            raise WatchdogError("WATCHDOG_PID_REBIND_FAILED")
    pgdata_fd, state_fd, rebound, pending, ownership_rebind = _open_bundle(container)
    try:
        _validate_journal(
            rebound,
            allowed_container_ids={container["containerId"]},
            allowed_image_ids={expected_image_id},
            expected_system_identifier=expected_system_identifier,
        )
        if (
            rebound["containerPid"] != container["containerPid"]
            or pending is not None
            or ownership_rebind
        ):
            raise WatchdogError("WATCHDOG_JOURNAL_PID_BINDING_MISMATCH")
    finally:
        os.close(state_fd)
        os.close(pgdata_fd)


def _runtime_lock_holders(conn: Any) -> list[dict[str, Any]]:
    class_id = RUNTIME_ADVISORY_LOCK_KEY >> 32
    object_id = RUNTIME_ADVISORY_LOCK_KEY & 0xFFFFFFFF
    rows = conn.execute(
        "SELECT a.pid,a.usename,a.application_name,a.client_addr IS NULL,a.state "
        "FROM pg_locks l JOIN pg_stat_activity a ON a.pid=l.pid "
        "WHERE l.locktype='advisory' AND l.database="
        "(SELECT oid FROM pg_database WHERE datname=current_database()) "
        "AND l.classid=%s AND l.objid=%s AND l.objsubid=1 AND l.granted "
        "ORDER BY a.pid",
        (class_id, object_id),
    ).fetchall()
    return [
        {
            "pid": row[0],
            "user": row[1],
            "applicationName": row[2],
            "unixSocket": row[3],
            "state": row[4],
        }
        for row in rows
    ]


def _valid_holder(holder: dict[str, Any]) -> bool:
    return (
        holder.get("user") == "postgres"
        and holder.get("unixSocket") is True
        and isinstance(holder.get("pid"), int)
        and re.fullmatch(
            rf"{LOCK_APPLICATION_PREFIX}-[0-9a-f]{{32}}",
            str(holder.get("applicationName", "")),
        )
        is not None
    )


def _acquire_runtime_lock(conn: Any) -> bool:
    return conn.execute(
        "SELECT pg_try_advisory_lock(%s)", (RUNTIME_ADVISORY_LOCK_KEY,)
    ).fetchone()[0] is True


def _terminate_holders_and_take_lock(
    conn: Any, holders: list[dict[str, Any]]
) -> None:
    if not holders:
        raise WatchdogError("WATCHDOG_RUNTIME_LOCK_DISAPPEARED_UNCERTAIN")
    for holder in holders:
        pid = holder.get("pid")
        if not isinstance(pid, int) or pid <= 0:
            raise WatchdogError("WATCHDOG_RUNTIME_LOCK_HOLDER_INVALID")
        if conn.execute(
            "SELECT pg_terminate_backend(%s,5000)", (pid,)
        ).fetchone()[0] is not True:
            raise WatchdogError("WATCHDOG_RUNTIME_LOCK_TERMINATION_FAILED")
    if not _acquire_runtime_lock(conn):
        raise WatchdogError("WATCHDOG_RUNTIME_LOCK_TAKEOVER_FAILED")


def _force_dormant(conn: Any) -> None:
    command = sql.SQL(
        "ALTER ROLE {} NOLOGIN PASSWORD NULL VALID UNTIL 'infinity'"
    ).format(sql.Identifier(ROLE))
    mutation_error = False
    try:
        conn.execute(command)
    except BaseException:
        mutation_error = True
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
            raise WatchdogError("WATCHDOG_CREDENTIAL_REVOKE_UNCERTAIN") from exc
    pids = conn.execute(
        "SELECT pid FROM pg_stat_activity WHERE usename=%s "
        "AND pid<>pg_backend_pid() ORDER BY pid",
        (ROLE,),
    ).fetchall()
    for (pid,) in pids:
        if conn.execute("SELECT pg_terminate_backend(%s,5000)", (pid,)).fetchone()[0] is not True:
            raise WatchdogError("WATCHDOG_SESSION_TERMINATION_FAILED")
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
        raise WatchdogError("WATCHDOG_CREDENTIAL_REVOKE_UNCERTAIN")
    if mutation_error and post not in {
        (False, True, "", 0), (False, True, "infinity", 0)
    }:
        raise WatchdogError("WATCHDOG_CREDENTIAL_REVOKE_UNCERTAIN")


def _verify_role(conn: Any, *, expected_login: bool) -> dict[str, Any]:
    report = inspect_role(conn.info.dsn, expected_login=expected_login)
    if (
        report.get("status") != "match"
        or report.get("hbaIsolationStatus") != "EXACT"
        or report.get("hbaFileSha256") != EXPECTED_DEPLOYED_HBA_SHA256
        or report.get("loginState") != ("ENABLED" if expected_login else "DISABLED")
        or (
            report.get("credentialState")
            != ("PRESENT" if expected_login else "ABSENT")
        )
    ):
        raise WatchdogError("WATCHDOG_ROLE_OR_HBA_POSTVERIFY_FAILED")
    return report


def watchdog_once(
    *,
    container_name: str,
    expected_image_id: str,
    expected_volume_name: str,
    expected_server_version_num: int,
    expected_system_identifier: str,
    allow_contract_container: bool = False,
    require_dormant: bool = False,
) -> dict[str, Any]:
    if (
        type(expected_server_version_num) is not int
        or expected_server_version_num // 10000 != 17
    ):
        raise WatchdogError("EXPECTED_SERVER_VERSION_INVALID")
    if not allow_contract_container and (
        container_name != PRODUCTION_CONTAINER
        or expected_volume_name != PRODUCTION_VOLUME
        or expected_system_identifier != PRODUCTION_SYSTEM_IDENTIFIER
    ):
        raise WatchdogError("PRODUCTION_TARGET_MISMATCH")

    with _host_lock(HOST_LOCK_PATH):
        container = inspect_container(
            container_name,
            expected_image_id=expected_image_id,
            expected_volume_name=expected_volume_name,
            allow_contract_container=allow_contract_container,
        )
        try:
            _validate_runtime_bundle(
                container,
                expected_system_identifier,
                container_name=container_name,
                expected_image_id=expected_image_id,
                expected_volume_name=expected_volume_name,
                expected_server_version_num=expected_server_version_num,
                allow_contract_container=allow_contract_container,
            )
        except BaseException as bundle_exc:
            try:
                with admin_connection(container["containerPid"]) as conn:
                    conn.execute("SET log_statement='none'")
                    conn.execute("SET log_min_duration_statement=-1")
                    conn.execute("SET log_min_error_statement='panic'")
                    state = _role_state(
                        conn,
                        expected_server_version_num=expected_server_version_num,
                        expected_system_identifier=expected_system_identifier,
                    )
                    if not _acquire_runtime_lock(conn):
                        _terminate_holders_and_take_lock(
                            conn, _runtime_lock_holders(conn)
                        )
                    _force_dormant(conn)
                    state = _role_state(
                        conn,
                        expected_server_version_num=expected_server_version_num,
                        expected_system_identifier=expected_system_identifier,
                    )
                    if state["authority"] != "DORMANT":
                        raise WatchdogError(
                            "WATCHDOG_BUNDLE_FAILURE_RECONCILE_UNCERTAIN"
                        )
                    _verify_role(conn, expected_login=False)
            except BaseException as reconcile_exc:
                raise WatchdogError(
                    "WATCHDOG_BUNDLE_FAILURE_RECONCILE_UNCERTAIN"
                ) from reconcile_exc
            raise WatchdogError(
                "WATCHDOG_BUNDLE_INVALID_AUTHORITY_REVOKED"
            ) from bundle_exc
        with admin_connection(container["containerPid"]) as conn:
            conn.execute("SET log_statement='none'")
            conn.execute("SET log_min_duration_statement=-1")
            conn.execute("SET log_min_error_statement='panic'")
            state = _role_state(
                conn,
                expected_server_version_num=expected_server_version_num,
                expected_system_identifier=expected_system_identifier,
            )
            acquired = _acquire_runtime_lock(conn)
            if not acquired:
                holders = _runtime_lock_holders(conn)
                holder_valid = len(holders) == 1 and _valid_holder(holders[0])
                if state["authority"] == "DORMANT" and holder_valid:
                    if require_dormant:
                        _terminate_holders_and_take_lock(conn, holders)
                        _verify_role(conn, expected_login=False)
                        status = "DORMANT_RUNTIME_LOCK_CLEARED_VERIFIED"
                    else:
                        _verify_role(conn, expected_login=False)
                        status = "DORMANT_RUNTIME_OPERATION_DEFERRED"
                elif state["authority"] == "ACTIVE_LEASE" and holder_valid:
                    remaining = (state["validUntil"] - state["serverNow"]).total_seconds()
                    if require_dormant:
                        _terminate_holders_and_take_lock(conn, holders)
                        _force_dormant(conn)
                        _verify_role(conn, expected_login=False)
                        status = "REQUIRED_DORMANT_AUTHORITY_REVOKED_VERIFIED"
                    elif not -EXPIRY_GRACE_SECONDS <= remaining <= MAX_TTL_SECONDS:
                        _terminate_holders_and_take_lock(conn, holders)
                        _force_dormant(conn)
                        _verify_role(conn, expected_login=False)
                        status = "INVALID_EXPIRY_AUTHORITY_REVOKED_VERIFIED"
                    elif remaining <= 0:
                        _terminate_holders_and_take_lock(conn, holders)
                        _force_dormant(conn)
                        _verify_role(conn, expected_login=False)
                        status = "EXPIRED_AUTHORITY_REVOKED_VERIFIED"
                    else:
                        _verify_role(conn, expected_login=True)
                        status = "ACTIVE_LEASE_SUPERVISED"
                else:
                    _terminate_holders_and_take_lock(conn, holders)
                    _force_dormant(conn)
                    _verify_role(conn, expected_login=False)
                    status = "UNTRUSTED_AUTHORITY_REVOKED_VERIFIED"
            else:
                if state["authority"] == "DORMANT":
                    _verify_role(conn, expected_login=False)
                    status = "DORMANT_VERIFIED"
                else:
                    _force_dormant(conn)
                    state = _role_state(
                        conn,
                        expected_server_version_num=expected_server_version_num,
                        expected_system_identifier=expected_system_identifier,
                    )
                    if state["authority"] != "DORMANT":
                        raise WatchdogError("WATCHDOG_RECONCILE_POSTVERIFY_FAILED")
                    _verify_role(conn, expected_login=False)
                    status = "ABANDONED_AUTHORITY_REVOKED_VERIFIED"
        after = inspect_container(
            container_name,
            expected_image_id=expected_image_id,
            expected_volume_name=expected_volume_name,
            allow_contract_container=allow_contract_container,
        )
        if after != container:
            raise WatchdogError("CONTAINER_CHANGED_DURING_WATCHDOG_RUN")
        return {
            "schemaVersion": "obsidian-b64-snapshot-reader-watchdog.v1",
            "status": status,
            "watchdogReady": True,
            "container": container,
            "serverVersionNum": expected_server_version_num,
            "systemIdentifier": expected_system_identifier,
            "roleLoginState": "ENABLED" if status == "ACTIVE_LEASE_SUPERVISED" else "DISABLED",
            "credentialState": "PRESENT" if status == "ACTIVE_LEASE_SUPERVISED" else "ABSENT",
            "dormantRequired": require_dormant,
            "customerRowsRead": False,
            "hbaChanged": False,
            "authorityIncreased": False,
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--container", default=PRODUCTION_CONTAINER)
    parser.add_argument("--expected-image-id", required=True)
    parser.add_argument("--expected-volume-name", default=PRODUCTION_VOLUME)
    parser.add_argument("--expected-server-version-num", required=True, type=int)
    parser.add_argument(
        "--expected-system-identifier", default=PRODUCTION_SYSTEM_IDENTIFIER
    )
    parser.add_argument("--allow-contract-container", action="store_true")
    parser.add_argument("--require-dormant", action="store_true")
    args = parser.parse_args()
    try:
        result = watchdog_once(
            container_name=args.container,
            expected_image_id=args.expected_image_id,
            expected_volume_name=args.expected_volume_name,
            expected_server_version_num=args.expected_server_version_num,
            expected_system_identifier=args.expected_system_identifier,
            allow_contract_container=args.allow_contract_container,
            require_dormant=args.require_dormant,
        )
        print(json.dumps(result, sort_keys=True))
        return 0
    except BaseException as exc:
        print(
            json.dumps(
                {
                    "schemaVersion": "obsidian-b64-snapshot-reader-watchdog.v1",
                    "status": "FAILED_UNCERTAIN_NO_AUTHORITY_INCREASE",
                    "watchdogReady": False,
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
