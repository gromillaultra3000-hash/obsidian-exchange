#!/usr/bin/env python3
"""Fail-closed boot and abnormal-exit reconciliation for the B64 reader.

The watchdog uses only the container-local PostgreSQL admin socket.  It owns no
password and never enables LOGIN.  A valid short lease is deferred while its
exact advisory-lock holder and server expiry are present; every orphaned or
expired authority state is reduced to NOLOGIN/PASSWORD NULL and zero sessions.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import errno
import fcntl
import hashlib
import json
import os
import re
import stat
from pathlib import Path
from typing import Any, Mapping

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
ACTIVATION_INTERLOCK_PATH = (
    "/run/lock/obsidian-b64-production-activation.lock"
)
RECOVERY_PARENT = Path("/etc/obsidian-exchange")
RECOVERY_REQUEST_NAME = "b64-064a-recovery-request.v1.json"
RECOVERY_PACKAGE_NAME = "b64-064a-recovery-package.v1"
RECOVERY_REQUEST_SCHEMA = "b64-064a-watchdog-recovery-request.v1"
RECOVERY_PACKAGE_SCHEMA = "b64-064a-watchdog-recovery-package.v1"
RECOVERY_ACTION = "RECONCILE_EXISTING_INCOMPLETE_ONLY"
ACTIVATION_ROUTE = "E0/E0.3/B5.3/064A"
ACTIVATION_JOURNAL_SCHEMA = "b64-064a-production-activation-journal.v2"
ACTIVATION_RECEIPT_SCHEMA = "b64-064a-production-activation-receipt.v2"
PRODUCTION_ACTIVATION_ROOT = Path(
    "/var/lib/obsidian-exchange/b64-064a-activation"
)
PRODUCTION_JOURNAL_ROOT = PRODUCTION_ACTIVATION_ROOT / "journal"
PRODUCTION_RESOURCE_JOURNAL_ROOT = PRODUCTION_ACTIVATION_ROOT / "resources"
PRODUCTION_WORKSPACE_ROOT = PRODUCTION_ACTIVATION_ROOT / "workspace"
PRODUCTION_PROXY_ROOT = PRODUCTION_ACTIVATION_ROOT / "proxy"
RECOVERY_FILES = {
    "keyring.json": 1024 * 1024,
    "decision.json": 1024 * 1024,
    "activation-plan.json": 1024 * 1024,
}
RECOVERY_MANIFEST_NAME = "manifest.json"
EXACT_DORMANT_STATUSES = {
    "DORMANT_VERIFIED",
    "DORMANT_RUNTIME_LOCK_CLEARED_VERIFIED",
    "INVALID_EXPIRY_AUTHORITY_REVOKED_VERIFIED",
    "EXPIRED_AUTHORITY_REVOKED_VERIFIED",
    "REQUIRED_DORMANT_AUTHORITY_REVOKED_VERIFIED",
    "UNTRUSTED_AUTHORITY_REVOKED_VERIFIED",
    "ABANDONED_AUTHORITY_REVOKED_VERIFIED",
}


class WatchdogError(RebindError):
    """Closed watchdog reason code safe for journald."""


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _digest(value: Any, code: str) -> str:
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise WatchdogError(code)
    return value


def _safe_directory_metadata(metadata: os.stat_result, *, mode: int) -> bool:
    return (
        stat.S_ISDIR(metadata.st_mode)
        and metadata.st_uid == 0 and metadata.st_gid == 0
        and stat.S_IMODE(metadata.st_mode) == mode
    )


def _file_binding(metadata: os.stat_result) -> tuple[Any, ...]:
    return (
        metadata.st_dev, metadata.st_ino, metadata.st_size,
        metadata.st_mtime_ns, metadata.st_ctime_ns, metadata.st_mode,
        metadata.st_uid, metadata.st_gid, metadata.st_nlink,
    )


def _open_recovery_parent() -> int | None:
    try:
        descriptor = os.open(
            RECOVERY_PARENT,
            os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
        )
    except OSError as exc:
        if exc.errno == errno.ENOENT:
            return None
        raise WatchdogError("WATCHDOG_RECOVERY_PARENT_UNSAFE") from exc
    metadata = os.fstat(descriptor)
    if (not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != 0 or metadata.st_gid != 0
            or stat.S_IMODE(metadata.st_mode) & 0o022):
        os.close(descriptor)
        raise WatchdogError("WATCHDOG_RECOVERY_PARENT_UNSAFE")
    return descriptor


def _read_bound_file(
    directory_fd: int, name: str, *, mode: int, maximum: int,
    missing_ok: bool = False,
) -> bytes | None:
    descriptor = -1
    try:
        descriptor = os.open(
            name,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            dir_fd=directory_fd,
        )
    except OSError as exc:
        if missing_ok and exc.errno == errno.ENOENT:
            return None
        raise WatchdogError("WATCHDOG_RECOVERY_FILE_UNSAFE") from exc
    try:
        before = os.fstat(descriptor)
        if (not stat.S_ISREG(before.st_mode)
                or before.st_uid != 0 or before.st_gid != 0
                or stat.S_IMODE(before.st_mode) != mode
                or before.st_nlink != 1
                or not 1 <= before.st_size <= maximum):
            raise WatchdogError("WATCHDOG_RECOVERY_FILE_UNSAFE")
        raw = b""
        while len(raw) < before.st_size:
            chunk = os.read(descriptor, before.st_size - len(raw))
            if not chunk:
                raise WatchdogError("WATCHDOG_RECOVERY_FILE_SHORT_READ")
            raw += chunk
        if os.read(descriptor, 1):
            raise WatchdogError("WATCHDOG_RECOVERY_FILE_GREW")
        after = os.fstat(descriptor)
        if _file_binding(after) != _file_binding(before):
            raise WatchdogError("WATCHDOG_RECOVERY_FILE_CHANGED")
        return raw
    finally:
        os.close(descriptor)


def _decode_object(raw: bytes, code: str) -> dict[str, Any]:
    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate JSON member")
            value[key] = item
        return value

    try:
        value = json.loads(
            raw.decode("utf-8"), object_pairs_hook=unique_object,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise WatchdogError(code) from exc
    if not isinstance(value, dict):
        raise WatchdogError(code)
    return value


def _validate_recovery_binding(value: Mapping[str, Any], *, schema: str) -> None:
    expected = {
        "schemaVersion", "route", "environment", "runNonce", "action",
        "automaticRetryAllowed", "expectedKeyringSha256", "planSha256",
        "decisionSha256",
    }
    if (not isinstance(value, Mapping) or not expected.issubset(value)
            or value.get("schemaVersion") != schema
            or value.get("route") != ACTIVATION_ROUTE
            or value.get("environment") != "PRODUCTION"
            or type(value.get("runNonce")) is not str
            or re.fullmatch(r"[A-Za-z0-9_-]{16,64}", value["runNonce"])
            is None
            or value.get("action") != RECOVERY_ACTION
            or value.get("automaticRetryAllowed") is not False):
        raise WatchdogError("WATCHDOG_RECOVERY_BINDING_INVALID")
    _digest(
        value.get("expectedKeyringSha256"),
        "WATCHDOG_RECOVERY_KEYRING_DIGEST_INVALID",
    )
    _digest(value.get("planSha256"), "WATCHDOG_RECOVERY_PLAN_DIGEST_INVALID")
    _digest(
        value.get("decisionSha256"),
        "WATCHDOG_RECOVERY_DECISION_DIGEST_INVALID",
    )


def _load_recovery_package() -> dict[str, Any] | None:
    """Read the fixed request and exact read-only package snapshot.

    The request is the external trust/commit marker.  A package directory may
    be staged before it, but it is never interpreted until the fixed request
    exists.
    """
    parent_fd = _open_recovery_parent()
    if parent_fd is None:
        return None
    package_fd = -1
    try:
        request_raw = _read_bound_file(
            parent_fd, RECOVERY_REQUEST_NAME, mode=0o400,
            maximum=64 * 1024, missing_ok=True,
        )
        if request_raw is None:
            try:
                probe = os.open(
                    RECOVERY_PACKAGE_NAME,
                    os.O_RDONLY | os.O_DIRECTORY
                    | getattr(os, "O_NOFOLLOW", 0)
                    | getattr(os, "O_CLOEXEC", 0),
                    dir_fd=parent_fd,
                )
            except OSError as exc:
                if exc.errno == errno.ENOENT:
                    return None
                raise WatchdogError(
                    "WATCHDOG_RECOVERY_PACKAGE_UNSAFE"
                ) from exc
            else:
                metadata = os.fstat(probe)
                os.close(probe)
                if not _safe_directory_metadata(metadata, mode=0o500):
                    raise WatchdogError("WATCHDOG_RECOVERY_PACKAGE_UNSAFE")
                return {"stagedWithoutRequest": True}
        request = _decode_object(
            request_raw, "WATCHDOG_RECOVERY_REQUEST_INVALID"
        )
        if set(request) != {
                "schemaVersion", "route", "environment", "runNonce",
                "action", "automaticRetryAllowed",
                "expectedKeyringSha256", "planSha256", "decisionSha256",
                "manifestSha256"}:
            raise WatchdogError("WATCHDOG_RECOVERY_REQUEST_INVALID")
        _validate_recovery_binding(request, schema=RECOVERY_REQUEST_SCHEMA)
        _digest(
            request.get("manifestSha256"),
            "WATCHDOG_RECOVERY_MANIFEST_DIGEST_INVALID",
        )
        try:
            package_fd = os.open(
                RECOVERY_PACKAGE_NAME,
                os.O_RDONLY | os.O_DIRECTORY
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0),
                dir_fd=parent_fd,
            )
        except OSError as exc:
            raise WatchdogError("WATCHDOG_RECOVERY_PACKAGE_MISSING") from exc
        if not _safe_directory_metadata(os.fstat(package_fd), mode=0o500):
            raise WatchdogError("WATCHDOG_RECOVERY_PACKAGE_UNSAFE")
        expected_entries = {RECOVERY_MANIFEST_NAME, *RECOVERY_FILES}
        if set(os.listdir(package_fd)) != expected_entries:
            raise WatchdogError("WATCHDOG_RECOVERY_PACKAGE_ENTRY_SET_INVALID")
        manifest_raw = _read_bound_file(
            package_fd, RECOVERY_MANIFEST_NAME, mode=0o400,
            maximum=64 * 1024,
        )
        assert manifest_raw is not None
        if _sha256(manifest_raw) != request["manifestSha256"]:
            raise WatchdogError("WATCHDOG_RECOVERY_MANIFEST_DIGEST_MISMATCH")
        manifest = _decode_object(
            manifest_raw, "WATCHDOG_RECOVERY_MANIFEST_INVALID"
        )
        if set(manifest) != {
                "schemaVersion", "route", "environment", "runNonce",
                "action", "automaticRetryAllowed",
                "expectedKeyringSha256", "planSha256", "decisionSha256",
                "files"}:
            raise WatchdogError("WATCHDOG_RECOVERY_MANIFEST_INVALID")
        _validate_recovery_binding(manifest, schema=RECOVERY_PACKAGE_SCHEMA)
        for key in (
                "route", "environment", "runNonce", "action",
                "automaticRetryAllowed", "expectedKeyringSha256",
                "planSha256", "decisionSha256"):
            if manifest.get(key) != request.get(key):
                raise WatchdogError("WATCHDOG_RECOVERY_REQUEST_PACKAGE_MISMATCH")
        files = manifest.get("files")
        if not isinstance(files, Mapping) or set(files) != set(RECOVERY_FILES):
            raise WatchdogError("WATCHDOG_RECOVERY_FILE_MANIFEST_INVALID")
        artifacts: dict[str, bytes] = {}
        for name, maximum in RECOVERY_FILES.items():
            binding = files.get(name)
            if (not isinstance(binding, Mapping)
                    or set(binding) != {"sha256", "size"}
                    or type(binding.get("size")) is not int
                    or not 1 <= binding["size"] <= maximum):
                raise WatchdogError("WATCHDOG_RECOVERY_FILE_MANIFEST_INVALID")
            _digest(
                binding.get("sha256"),
                "WATCHDOG_RECOVERY_FILE_DIGEST_INVALID",
            )
            raw = _read_bound_file(
                package_fd, name, mode=0o400, maximum=maximum,
            )
            assert raw is not None
            if (len(raw) != binding["size"]
                    or _sha256(raw) != binding["sha256"]):
                raise WatchdogError("WATCHDOG_RECOVERY_FILE_BINDING_MISMATCH")
            artifacts[name] = raw
        if set(os.listdir(package_fd)) != expected_entries:
            raise WatchdogError("WATCHDOG_RECOVERY_PACKAGE_CHANGED")
        if not _safe_directory_metadata(os.fstat(package_fd), mode=0o500):
            raise WatchdogError("WATCHDOG_RECOVERY_PACKAGE_CHANGED")
        return {
            "stagedWithoutRequest": False,
            "request": request, "manifest": manifest, **artifacts,
        }
    finally:
        if package_fd >= 0:
            os.close(package_fd)
        os.close(parent_fd)


def _scan_activation_journals_snapshot() -> dict[str, dict[str, Any]]:
    """Inspect exact outer journals without creating the activation root."""
    try:
        root_fd = os.open(
            PRODUCTION_ACTIVATION_ROOT,
            os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
        )
    except OSError as exc:
        if exc.errno == errno.ENOENT:
            return {}
        raise WatchdogError("WATCHDOG_ACTIVATION_ROOT_UNSAFE") from exc
    journal_fd = -1
    try:
        if not _safe_directory_metadata(os.fstat(root_fd), mode=0o700):
            raise WatchdogError("WATCHDOG_ACTIVATION_ROOT_UNSAFE")
        try:
            journal_fd = os.open(
                "journal",
                os.O_RDONLY | os.O_DIRECTORY
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0),
                dir_fd=root_fd,
            )
        except OSError as exc:
            if exc.errno == errno.ENOENT:
                return {}
            raise WatchdogError("WATCHDOG_ACTIVATION_JOURNAL_ROOT_UNSAFE") \
                from exc
        if not _safe_directory_metadata(os.fstat(journal_fd), mode=0o700):
            raise WatchdogError("WATCHDOG_ACTIVATION_JOURNAL_ROOT_UNSAFE")
        journals: dict[str, dict[str, Any]] = {}
        locks: set[str] = set()
        busy_locks: set[str] = set()
        receipts: dict[str, tuple[str, dict[str, Any]]] = {}
        foreign_entries: set[str] = set()
        entries_before = set(os.listdir(journal_fd))
        for name in entries_before:
            journal_match = re.fullmatch(r"([A-Za-z0-9_-]{16,64})\.json", name)
            lock_match = re.fullmatch(r"\.([A-Za-z0-9_-]{16,64})\.lock", name)
            receipt_match = re.fullmatch(
                r"([A-Za-z0-9_-]{16,64})\.receipt\.json", name
            )
            if lock_match:
                lock_fd = -1
                try:
                    lock_fd = os.open(
                        name,
                        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                        | getattr(os, "O_CLOEXEC", 0),
                        dir_fd=journal_fd,
                    )
                    metadata = os.fstat(lock_fd)
                    if (not stat.S_ISREG(metadata.st_mode)
                            or metadata.st_uid != 0 or metadata.st_gid != 0
                            or stat.S_IMODE(metadata.st_mode) != 0o600
                            or metadata.st_nlink != 1
                            or metadata.st_size > 64 * 1024):
                        raise WatchdogError(
                            "WATCHDOG_ACTIVATION_LOCK_UNSAFE"
                        )
                    try:
                        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        busy_locks.add(lock_match.group(1))
                    else:
                        fcntl.flock(lock_fd, fcntl.LOCK_UN)
                except OSError:
                    raise WatchdogError("WATCHDOG_ACTIVATION_LOCK_UNSAFE")
                finally:
                    if lock_fd >= 0:
                        os.close(lock_fd)
            elif receipt_match:
                receipt_raw = _read_bound_file(
                    journal_fd, name, mode=0o600, maximum=1024 * 1024,
                )
                assert receipt_raw is not None
                if not receipt_raw.endswith(b"\n"):
                    raise WatchdogError(
                        "WATCHDOG_ACTIVATION_RECEIPT_INVALID"
                    )
                receipt_value = _decode_object(
                    receipt_raw,
                    "WATCHDOG_ACTIVATION_RECEIPT_INVALID",
                )
                receipts[receipt_match.group(1)] = (
                    _sha256(receipt_raw[:-1]), receipt_value,
                )
            elif journal_match:
                raw = _read_bound_file(
                    journal_fd, name, mode=0o600, maximum=64 * 1024,
                )
                assert raw is not None
                value = _decode_object(
                    raw, "WATCHDOG_ACTIVATION_JOURNAL_INVALID"
                )
                nonce = journal_match.group(1)
                if (set(value) != {
                        "schemaVersion", "route", "runNonce", "planSha256",
                        "decisionSha256", "state", "attempt", "retryAllowed",
                        "receiptSha256", "reasonCode"}
                        or value.get("schemaVersion")
                        != ACTIVATION_JOURNAL_SCHEMA
                        or value.get("route") != ACTIVATION_ROUTE
                        or value.get("runNonce") != nonce
                        or value.get("state") not in {
                            "CLAIMED", "RUNNING", "CLOSED", "HOLD",
                            "RECONCILED_HOLD"}
                        or value.get("attempt") != 1
                        or value.get("retryAllowed") is not False):
                    raise WatchdogError(
                        "WATCHDOG_ACTIVATION_JOURNAL_INVALID"
                    )
                _digest(
                    value.get("planSha256"),
                    "WATCHDOG_ACTIVATION_JOURNAL_DIGEST_INVALID",
                )
                _digest(
                    value.get("decisionSha256"),
                    "WATCHDOG_ACTIVATION_JOURNAL_DIGEST_INVALID",
                )
                receipt_sha = value.get("receiptSha256")
                if receipt_sha is not None:
                    _digest(
                        receipt_sha,
                        "WATCHDOG_ACTIVATION_JOURNAL_DIGEST_INVALID",
                    )
                if nonce in journals:
                    raise WatchdogError(
                        "WATCHDOG_ACTIVATION_JOURNAL_DUPLICATE"
                    )
                journals[nonce] = value
            else:
                foreign_entries.add(name)
            if lock_match:
                locks.add(lock_match.group(1))
        entries_after = set(os.listdir(journal_fd))
        if busy_locks:
            # A launcher owns its nonce lock before it creates or atomically
            # replaces the journal.  Treat every such snapshot as live work,
            # never as corruption and never as cleanup authority.
            raise WatchdogError("WATCHDOG_ACTIVATION_DISCOVERY_DEFERRED")
        if foreign_entries:
            raise WatchdogError("WATCHDOG_ACTIVATION_JOURNAL_FOREIGN_ENTRY")
        if entries_after != entries_before:
            raise WatchdogError("WATCHDOG_ACTIVATION_JOURNAL_CHANGED")
        if locks != set(journals):
            raise WatchdogError("WATCHDOG_ACTIVATION_LOCK_BINDING_MISMATCH")
        if not set(receipts).issubset(journals):
            raise WatchdogError(
                "WATCHDOG_ACTIVATION_RECEIPT_BINDING_MISMATCH"
            )
        for nonce, journal in journals.items():
            closed = journal["state"] == "CLOSED"
            receipt = receipts.get(nonce)
            if (closed and (receipt is None
                    or journal["receiptSha256"] != receipt[0])):
                raise WatchdogError(
                    "WATCHDOG_ACTIVATION_RECEIPT_BINDING_MISMATCH"
                )
            if not closed and journal["receiptSha256"] is not None:
                raise WatchdogError(
                    "WATCHDOG_ACTIVATION_RECEIPT_BINDING_MISMATCH"
                )
            if receipt is not None and not closed:
                value = receipt[1]
                if (journal["state"] not in {
                        "RUNNING", "HOLD", "RECONCILED_HOLD"}
                        or value.get("schemaVersion")
                        != ACTIVATION_RECEIPT_SCHEMA
                        or value.get("route") != ACTIVATION_ROUTE
                        or value.get("environment") != "PRODUCTION"
                        or value.get("runNonce") != nonce
                        or value.get("planSha256")
                        != journal["planSha256"]
                        or value.get("decisionSha256")
                        != journal["decisionSha256"]
                        or value.get("status")
                        != "COMPLETED_DORMANT_VERIFIED"):
                    raise WatchdogError(
                        "WATCHDOG_ACTIVATION_RESIDUAL_RECEIPT_INVALID"
                    )
        incomplete = [
            nonce for nonce, value in journals.items()
            if value["state"] in {"CLAIMED", "RUNNING", "HOLD"}
        ]
        if len(incomplete) > 1:
            raise WatchdogError("WATCHDOG_MULTIPLE_INCOMPLETE_ACTIVATIONS")
        return journals
    finally:
        if journal_fd >= 0:
            os.close(journal_fd)
        os.close(root_fd)


def _scan_activation_journals() -> dict[str, dict[str, Any]]:
    """Require one exact snapshot, retrying one concurrent atomic transition."""
    try:
        return _scan_activation_journals_snapshot()
    except WatchdogError as first:
        if str(first) == "WATCHDOG_ACTIVATION_DISCOVERY_DEFERRED":
            raise
        try:
            return _scan_activation_journals_snapshot()
        except WatchdogError as second:
            raise second from first


@contextlib.contextmanager
def _activation_interlock_status(path: str = ACTIVATION_INTERLOCK_PATH):
    """Hold the idle side of the activation lock, or report a live owner.

    Keeping the descriptor open for the complete watchdog pass closes the
    check/use race: either this pass owns the lock and a new activation cannot
    start, or the activation owns it and this pass may supervise only an
    otherwise-valid short lease.
    """
    descriptor = -1
    activation_live = False
    try:
        descriptor = os.open(
            path,
            os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            0o600,
        )
        metadata = os.fstat(descriptor)
        if (not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != os.geteuid()
                or stat.S_IMODE(metadata.st_mode) != 0o600
                or metadata.st_nlink != 1):
            raise WatchdogError("WATCHDOG_ACTIVATION_INTERLOCK_UNSAFE")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            activation_live = True
        yield activation_live
    except OSError as exc:
        raise WatchdogError(
            "WATCHDOG_ACTIVATION_INTERLOCK_UNAVAILABLE"
        ) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


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

    with _host_lock(HOST_LOCK_PATH), _activation_interlock_status() as activation_live:
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
                    if require_dormant and not activation_live:
                        _terminate_holders_and_take_lock(conn, holders)
                        _verify_role(conn, expected_login=False)
                        status = "DORMANT_RUNTIME_LOCK_CLEARED_VERIFIED"
                    elif require_dormant:
                        _verify_role(conn, expected_login=False)
                        status = "DORMANT_ACTIVATION_CLEANUP_DEFERRED"
                    else:
                        _verify_role(conn, expected_login=False)
                        status = "DORMANT_RUNTIME_OPERATION_DEFERRED"
                elif state["authority"] == "ACTIVE_LEASE" and holder_valid:
                    remaining = (state["validUntil"] - state["serverNow"]).total_seconds()
                    if not -EXPIRY_GRACE_SECONDS <= remaining <= MAX_TTL_SECONDS:
                        _terminate_holders_and_take_lock(conn, holders)
                        _force_dormant(conn)
                        _verify_role(conn, expected_login=False)
                        status = "INVALID_EXPIRY_AUTHORITY_REVOKED_VERIFIED"
                    elif remaining <= 0:
                        _terminate_holders_and_take_lock(conn, holders)
                        _force_dormant(conn)
                        _verify_role(conn, expected_login=False)
                        status = "EXPIRED_AUTHORITY_REVOKED_VERIFIED"
                    elif require_dormant and not activation_live:
                        _terminate_holders_and_take_lock(conn, holders)
                        _force_dormant(conn)
                        _verify_role(conn, expected_login=False)
                        status = "REQUIRED_DORMANT_AUTHORITY_REVOKED_VERIFIED"
                    else:
                        _verify_role(conn, expected_login=True)
                        status = (
                            "ACTIVE_LEASE_ACTIVATION_INTERLOCK_SUPERVISED"
                            if require_dormant else "ACTIVE_LEASE_SUPERVISED"
                        )
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
        active_statuses = {
            "ACTIVE_LEASE_SUPERVISED",
            "ACTIVE_LEASE_ACTIVATION_INTERLOCK_SUPERVISED",
        }
        return {
            "schemaVersion": "obsidian-b64-snapshot-reader-watchdog.v1",
            "status": status,
            "watchdogReady": True,
            "container": container,
            "serverVersionNum": expected_server_version_num,
            "systemIdentifier": expected_system_identifier,
            "roleLoginState": "ENABLED" if status in active_statuses else "DISABLED",
            "credentialState": "PRESENT" if status in active_statuses else "ABSENT",
            "activeSessions": state["sessions"] if status in active_statuses else 0,
            "dormantRequired": require_dormant,
            "activationInterlockHeld": activation_live,
            "customerRowsRead": False,
            "hbaChanged": False,
            "authorityIncreased": False,
        }


def _require_exact_dormant(result: Mapping[str, Any], *, phase: str) -> None:
    if (result.get("status") not in EXACT_DORMANT_STATUSES
            or result.get("watchdogReady") is not True
            or result.get("dormantRequired") is not True
            or result.get("activationInterlockHeld") is not False
            or result.get("roleLoginState") != "DISABLED"
            or result.get("credentialState") != "ABSENT"
            or result.get("activeSessions") != 0
            or result.get("customerRowsRead") is not False
            or result.get("authorityIncreased") is not False):
        raise WatchdogError(f"WATCHDOG_{phase}_DORMANT_REQUIRED")


def _live_activation_defer(result: Mapping[str, Any]) -> bool:
    if (result.get("watchdogReady") is not True
            or result.get("activationInterlockHeld") is not True
            or result.get("customerRowsRead") is not False
            or result.get("authorityIncreased") is not False):
        return False
    if result.get("status") == \
            "ACTIVE_LEASE_ACTIVATION_INTERLOCK_SUPERVISED":
        return (
            result.get("roleLoginState") == "ENABLED"
            and result.get("credentialState") == "PRESENT"
        )
    return (
        result.get("status") in (
            EXACT_DORMANT_STATUSES | {"DORMANT_ACTIVATION_CLEANUP_DEFERRED"}
        )
        and result.get("roleLoginState") == "DISABLED"
        and result.get("credentialState") == "ABSENT"
        and result.get("activeSessions") == 0
    )


def watchdog_with_cleanup_recovery(
    *, container_name: str, expected_image_id: str,
    expected_volume_name: str, expected_server_version_num: int,
    expected_system_identifier: str,
) -> dict[str, Any]:
    """Run fixed-path, once-only cleanup recovery between dormant passes."""
    arguments = {
        "container_name": container_name,
        "expected_image_id": expected_image_id,
        "expected_volume_name": expected_volume_name,
        "expected_server_version_num": expected_server_version_num,
        "expected_system_identifier": expected_system_identifier,
        "allow_contract_container": False,
        "require_dormant": True,
    }
    pre = watchdog_once(**arguments)
    if _live_activation_defer(pre):
        return {
            **pre,
            "status": "WATCHDOG_RECOVERY_DEFERRED_LIVE_ACTIVATION",
            "preWatchdogStatus": pre["status"],
            "recoveryStatus": "DEFERRED_LIVE_ACTIVATION",
            "automaticRetryAllowed": False, "actionAllowed": False,
        }
    _require_exact_dormant(pre, phase="PRE_RECOVERY")
    try:
        # Hold the idle side while the exact snapshot is taken.  Production
        # launchers acquire this global interlock before creating/locking a
        # nonce journal, so no atomic journal transition can begin mid-scan.
        with _activation_interlock_status() as discovery_live:
            if discovery_live:
                raise WatchdogError(
                    "WATCHDOG_ACTIVATION_DISCOVERY_DEFERRED"
                )
            journals = _scan_activation_journals()
    except WatchdogError as exc:
        if str(exc) != "WATCHDOG_ACTIVATION_DISCOVERY_DEFERRED":
            raise
        return {
            **pre,
            "status": "WATCHDOG_RECOVERY_DEFERRED_LIVE_ACTIVATION",
            "preWatchdogStatus": pre["status"],
            "recoveryStatus": "DEFERRED_LIVE_ACTIVATION",
            "automaticRetryAllowed": False, "actionAllowed": False,
        }
    incomplete = {
        nonce: value for nonce, value in journals.items()
        if value["state"] in {"CLAIMED", "RUNNING", "HOLD"}
    }
    package = _load_recovery_package()
    if package is None or package.get("stagedWithoutRequest") is True:
        if incomplete:
            raise WatchdogError(
                "WATCHDOG_INCOMPLETE_ACTIVATION_RECOVERY_REQUEST_ABSENT"
            )
        return {
            **pre,
            "status": (
                "DORMANT_VERIFIED_RECOVERY_PACKAGE_STAGED"
                if package is not None else
                "DORMANT_VERIFIED_NO_RECOVERY_REQUEST"
            ),
            "preWatchdogStatus": pre["status"],
            "recoveryStatus": "NO_ACTION",
            "automaticRetryAllowed": False,
            "actionAllowed": False,
        }
    request = package["request"]
    request_nonce = request["runNonce"]
    if incomplete and request_nonce not in incomplete:
        raise WatchdogError("WATCHDOG_RECOVERY_INCOMPLETE_JOURNAL_MISMATCH")
    journal = journals.get(request_nonce)
    if journal is None:
        post = watchdog_once(**arguments)
        if _live_activation_defer(post):
            return {
                **post,
                "status": "WATCHDOG_RECOVERY_POST_DEFERRED_LIVE_ACTIVATION",
                "preWatchdogStatus": pre["status"],
                "postWatchdogStatus": post["status"],
                "recoveryStatus": "EXACT_JOURNAL_ABSENT_NO_ACTION",
                "automaticRetryAllowed": False, "actionAllowed": False,
            }
        _require_exact_dormant(post, phase="POST_RECOVERY")
        return {
            **post,
            "status": "DORMANT_VERIFIED_RECOVERY_NOT_REQUIRED",
            "preWatchdogStatus": pre["status"],
            "postWatchdogStatus": post["status"],
            "recoveryStatus": "EXACT_JOURNAL_ABSENT_NO_ACTION",
            "automaticRetryAllowed": False, "actionAllowed": False,
        }
    if (journal["planSha256"] != request["planSha256"]
            or journal["decisionSha256"] != request["decisionSha256"]):
        raise WatchdogError("WATCHDOG_RECOVERY_JOURNAL_BINDING_MISMATCH")
    if journal["state"] == "HOLD":
        raise WatchdogError("WATCHDOG_RECOVERY_HOLD_MANUAL_REQUIRED")
    if journal["state"] in {"CLOSED", "RECONCILED_HOLD"}:
        post = watchdog_once(**arguments)
        if _live_activation_defer(post):
            return {
                **post,
                "status": "WATCHDOG_RECOVERY_POST_DEFERRED_LIVE_ACTIVATION",
                "preWatchdogStatus": pre["status"],
                "postWatchdogStatus": post["status"],
                "recoveryStatus": journal["state"],
                "automaticRetryAllowed": False, "actionAllowed": False,
            }
        _require_exact_dormant(post, phase="POST_RECOVERY")
        return {
            **post,
            "status": "DORMANT_VERIFIED_RECOVERY_TERMINAL_NO_ACTION",
            "preWatchdogStatus": pre["status"],
            "postWatchdogStatus": post["status"],
            "recoveryStatus": journal["state"],
            "automaticRetryAllowed": False, "actionAllowed": False,
        }
    import b64_064a_activation_entrypoint as activation
    import b64_064a_activation_executor as activation_executor

    try:
        trusted_now, _clock_evidence = \
            activation.supervisor._trusted_now_epoch()
    except activation.supervisor.SupervisorError as exc:
        raise WatchdogError("WATCHDOG_RECOVERY_TRUSTED_TIME_UNAVAILABLE") from exc
    except BaseException as exc:
        raise WatchdogError("WATCHDOG_RECOVERY_TRUSTED_TIME_UNAVAILABLE") from exc
    try:
        recovery = activation.verify_cleanup_recovery(
            keyring_raw=package["keyring.json"],
            decision_raw=package["decision.json"],
            activation_plan_raw=package["activation-plan.json"],
            expected_keyring_sha256=request["expectedKeyringSha256"],
            expected_environment="PRODUCTION", now_epoch=trusted_now,
        )
    except activation.ActivationError as exc:
        raise WatchdogError(
            f"WATCHDOG_RECOVERY_{activation._reason(exc)}"
        ) from exc
    except BaseException as exc:
        raise WatchdogError("WATCHDOG_RECOVERY_VERIFICATION_FAILED") from exc
    if type(recovery) is not activation.VerifiedRecovery:
        raise WatchdogError("WATCHDOG_RECOVERY_CAPABILITY_INVALID")
    if (recovery.run_nonce != request_nonce
            or recovery.keyring_sha256 != request["expectedKeyringSha256"]
            or recovery.plan_sha256 != request["planSha256"]
            or recovery.decision_sha256 != request["decisionSha256"]):
        raise WatchdogError("WATCHDOG_RECOVERY_VERIFIED_BINDING_MISMATCH")
    target = recovery.target
    container = pre.get("container")
    if (not isinstance(target, Mapping) or not isinstance(container, Mapping)
            or target.get("containerName") != container_name
            or target.get("containerId") != container.get("containerId")
            or target.get("imageId") != expected_image_id
            or target.get("systemIdentifier")
            != expected_system_identifier):
        raise WatchdogError("WATCHDOG_RECOVERY_TARGET_BINDING_MISMATCH")
    try:
        executor = activation_executor.BoundRecoveryExecutor(
            container=container_name, container_id=container["containerId"],
            image_id=expected_image_id,
            system_identifier=expected_system_identifier,
            workspace_parent=activation.PRODUCTION_WORKSPACE_ROOT,
            proxy_parent=activation.PRODUCTION_PROXY_ROOT,
            resource_journal_root=activation.PRODUCTION_RESOURCE_JOURNAL_ROOT,
        )
    except activation.ActivationError as exc:
        raise WatchdogError(
            f"WATCHDOG_RECOVERY_{activation._reason(exc)}"
        ) from exc
    except BaseException as exc:
        raise WatchdogError("WATCHDOG_RECOVERY_EXECUTOR_CONSTRUCTION_FAILED") \
            from exc
    try:
        recovered = activation.reconcile_incomplete(
            authorization=recovery,
            journal_root=activation.PRODUCTION_JOURNAL_ROOT,
            activation_plan_raw=package["activation-plan.json"],
            executor=executor, reconcile=executor.attest_dormant,
            verify_dormant=executor.attest_dormant,
            automatic_no_retry=True,
        )
    except BaseException as exc:
        # Preserve the primary recovery reason.  This best-effort pass gives
        # an in-process dormant reconciliation opportunity; a hard kill still
        # leaves the durable HOLD marker for the next timer tick.
        failure_post = None
        try:
            failure_post = watchdog_once(**arguments)
        except BaseException:
            pass
        if isinstance(exc, activation.ActivationError):
            reason = activation._reason(exc)
            if (reason == "ACTIVATION_INTERLOCK_HELD"
                    and failure_post is not None
                    and _live_activation_defer(failure_post)):
                return {
                    **failure_post,
                    "status": "WATCHDOG_RECOVERY_DEFERRED_LIVE_ACTIVATION",
                    "preWatchdogStatus": pre["status"],
                    "postWatchdogStatus": failure_post["status"],
                    "recoveryStatus": "DEFERRED_LIVE_ACTIVATION",
                    "automaticRetryAllowed": False, "actionAllowed": False,
                }
            raise WatchdogError(f"WATCHDOG_RECOVERY_{reason}") from exc
        raise WatchdogError("WATCHDOG_RECOVERY_EXECUTION_FAILED") from exc
    if (recovered.get("status") != "ACTIVATION_RECONCILED_HOLD"
            or recovered.get("automaticRetryAllowed") is not False
            or recovered.get("actionAllowed") is not False):
        raise WatchdogError("WATCHDOG_RECOVERY_RESULT_INVALID")
    post = watchdog_once(**arguments)
    if _live_activation_defer(post):
        return {
            **post,
            "status": "WATCHDOG_RECOVERY_POST_DEFERRED_LIVE_ACTIVATION",
            "preWatchdogStatus": pre["status"],
            "postWatchdogStatus": post["status"],
            "recoveryStatus": recovered["status"],
            "recoveryRunNonce": recovered["runNonce"],
            "automaticRetryAllowed": False, "actionAllowed": False,
        }
    _require_exact_dormant(post, phase="POST_RECOVERY")
    return {
        **post,
        "status": "DORMANT_VERIFIED_RECOVERY_RECONCILED_HOLD",
        "preWatchdogStatus": pre["status"],
        "postWatchdogStatus": post["status"],
        "recoveryStatus": recovered["status"],
        "recoveryRunNonce": recovered["runNonce"],
        "automaticRetryAllowed": False, "actionAllowed": False,
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
    parser.add_argument("--cleanup-recovery", action="store_true")
    args = parser.parse_args()
    try:
        if args.cleanup_recovery:
            if args.allow_contract_container or not args.require_dormant:
                raise WatchdogError("WATCHDOG_RECOVERY_CLI_SCOPE_INVALID")
            result = watchdog_with_cleanup_recovery(
                container_name=args.container,
                expected_image_id=args.expected_image_id,
                expected_volume_name=args.expected_volume_name,
                expected_server_version_num=args.expected_server_version_num,
                expected_system_identifier=args.expected_system_identifier,
            )
        else:
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
