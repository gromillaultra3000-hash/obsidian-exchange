#!/usr/bin/env python3
"""Archive one terminal 064A run and clear its exact runtime paths.

The command accepts only explicit confirmation of a run nonce and decision
digest.  It verifies a signed cleanup-recovery package, an exact terminal
RECONCILED_HOLD journal, absent resources and dormant database authority.  It
then atomically moves (never copies-and-deletes) the four runtime components
into a root-only archive on the same filesystem.  A durable staging manifest
makes every crash prefix resumable without re-enabling or retrying activation.
"""
from __future__ import annotations

import argparse
import contextlib
import ctypes
import errno
import fcntl
import hashlib
import json
import os
import re
import stat
import sys
from pathlib import Path
from typing import Any, Callable, Mapping

import b64_064a_activation_entrypoint as activation
import b64_064a_activation_executor as executor_module
import b64_064a_activation_launcher as launcher
import b64_snapshot_reader_watchdog as watchdog


ROUTE = activation.ROUTE
RELEASE_BASE = Path("/opt/obsidian-exchange/releases/e0-e0.3-b5.3-064a")
SIGNED_ARTIFACT_RELEASE = (
    RELEASE_BASE / "c6c3eaba1b78b06235741ce88e003162c35d4bcb"
)
BACKUP_BASE = Path("/var/backups/obsidian-exchange")
ARCHIVE_PARENT = BACKUP_BASE / "b64-064a-terminal-evidence-v1"
RECOVERY_PARENT = watchdog.RECOVERY_PARENT
ACTIVATION_ROOT = activation.PRODUCTION_ACTIVATION_ROOT
ARCHIVE_LOCK = Path("/run/lock/obsidian-b64-064a-terminal-archive.lock")
MANIFEST_NAME = "TERMINAL-MANIFEST.json"
ARCHIVE_SCHEMA = "b64-064a-terminal-evidence-archive.v1"
MAX_FILE_BYTES = 1024 * 1024
RENAME_NOREPLACE = 1
FaultHook = Callable[[str], None]

COMPONENTS = {
    "activation-state": lambda: ACTIVATION_ROOT,
    "launch-request.json": lambda: (
        RECOVERY_PARENT / launcher.LAUNCH_REQUEST_NAME
    ),
    "recovery-request.json": lambda: (
        RECOVERY_PARENT / watchdog.RECOVERY_REQUEST_NAME
    ),
    "recovery-package": lambda: (
        RECOVERY_PARENT / watchdog.RECOVERY_PACKAGE_NAME
    ),
}


class ArchiveError(activation.ActivationError):
    """Closed reason code safe for the operator receipt."""


def _reason(exc: BaseException) -> str:
    if (isinstance(exc, (
            ArchiveError, activation.ActivationError,
            executor_module.ExecutorError, watchdog.WatchdogError,
            launcher.LauncherError,
    )) and re.fullmatch(r"[A-Z0-9_]+", str(exc))):
        return str(exc)
    return "TERMINAL_ARCHIVE_UNEXPECTED_FAILURE"


def _canonical(value: Any) -> bytes:
    try:
        return activation._canonical(value)
    except activation.ActivationError as exc:
        raise ArchiveError(str(exc)) from exc


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _token(value: Any, code: str) -> str:
    if (type(value) is not str or not 16 <= len(value) <= 64
            or re.fullmatch(r"[A-Za-z0-9_-]+", value) is None):
        raise ArchiveError(code)
    return value


def _digest(value: Any, code: str) -> str:
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ArchiveError(code)
    return value


def _metadata(info: os.stat_result) -> dict[str, int]:
    return {
        "uid": info.st_uid,
        "gid": info.st_gid,
        "mode": stat.S_IMODE(info.st_mode),
        "size": info.st_size,
        "nlink": info.st_nlink,
    }


def _verify_runtime_identity() -> Path:
    if os.geteuid() != 0:
        raise ArchiveError("TERMINAL_ARCHIVE_ROOT_REQUIRED")
    script = Path(__file__).resolve()
    try:
        release = script.parents[2]
    except IndexError as exc:
        raise ArchiveError("TERMINAL_ARCHIVE_RELEASE_IDENTITY_INVALID") \
            from exc
    if (release.parent != RELEASE_BASE
            or re.fullmatch(r"[0-9a-f]{40}", release.name) is None):
        raise ArchiveError("TERMINAL_ARCHIVE_RELEASE_IDENTITY_INVALID")
    try:
        release_info = os.lstat(release)
        script_info = os.lstat(script)
    except OSError as exc:
        raise ArchiveError("TERMINAL_ARCHIVE_RELEASE_UNSAFE") from exc
    if (not stat.S_ISDIR(release_info.st_mode)
            or release_info.st_uid != 0 or release_info.st_gid != 0
            or stat.S_IMODE(release_info.st_mode) != 0o555
            or not stat.S_ISREG(script_info.st_mode)
            or script_info.st_uid != 0 or script_info.st_gid != 0
            or stat.S_IMODE(script_info.st_mode) & 0o022
            or script_info.st_nlink != 1):
        raise ArchiveError("TERMINAL_ARCHIVE_RELEASE_UNSAFE")
    expected_modules = {
        activation: "b64_064a_activation_entrypoint.py",
        executor_module: "b64_064a_activation_executor.py",
        launcher: "b64_064a_activation_launcher.py",
        watchdog: "b64_snapshot_reader_watchdog.py",
    }
    for module, name in expected_modules.items():
        if Path(module.__file__).resolve() != release / "deploy/postgres" / name:
            raise ArchiveError("TERMINAL_ARCHIVE_MODULE_RELEASE_MISMATCH")
    for unit_name in (
        "obsidian-b64-064a-activation.service",
        "obsidian-b64-snapshot-reader-watchdog.service",
        "obsidian-postgres.service",
    ):
        try:
            raw, _digest_value = activation._artifact_bytes_and_sha256(
                Path("/etc/systemd/system") / unit_name,
            )
        except activation.ActivationError as exc:
            raise ArchiveError("TERMINAL_ARCHIVE_UNIT_UNSAFE") from exc
        if f"/{release.name}/".encode("ascii") not in raw:
            raise ArchiveError("TERMINAL_ARCHIVE_UNIT_RELEASE_MISMATCH")
    return release


def _open_directory(
    path: Path, *, mode: int, uid: int = 0, gid: int = 0,
) -> int:
    try:
        descriptor = os.open(
            path, os.O_RDONLY | os.O_DIRECTORY
            | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
        )
        info = os.fstat(descriptor)
    except OSError as exc:
        raise ArchiveError("TERMINAL_ARCHIVE_DIRECTORY_UNSAFE") from exc
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != uid
            or info.st_gid != gid or stat.S_IMODE(info.st_mode) != mode):
        os.close(descriptor)
        raise ArchiveError("TERMINAL_ARCHIVE_DIRECTORY_UNSAFE")
    return descriptor


def _historical_artifact_paths(release: Path) -> dict[str, Path]:
    """Resolve the signed plan's files from its exact immutable release.

    The terminal run predates a post-failure fix to the runtime package
    committer.  Recovery must therefore verify the historical signature
    against the bytes it actually bound, while this archiver and all active
    runtime modules remain pinned to the current operational release.
    """
    descriptor = _open_directory(SIGNED_ARTIFACT_RELEASE, mode=0o555)
    os.close(descriptor)
    paths: dict[str, Path] = {}
    for key, current in activation.ARTIFACT_PATHS.items():
        try:
            relative = current.relative_to(release)
        except ValueError as exc:
            raise ArchiveError(
                "TERMINAL_ARCHIVE_ARTIFACT_PATH_UNBOUND"
            ) from exc
        if relative.is_absolute() or ".." in relative.parts:
            raise ArchiveError("TERMINAL_ARCHIVE_ARTIFACT_PATH_UNBOUND")
        paths[key] = SIGNED_ARTIFACT_RELEASE / relative
    if set(paths) != activation.ARTIFACT_KEYS:
        raise ArchiveError("TERMINAL_ARCHIVE_ARTIFACT_SET_INVALID")
    return paths


@contextlib.contextmanager
def _signed_artifact_closure(release: Path):
    original = activation.ARTIFACT_PATHS
    activation.ARTIFACT_PATHS = _historical_artifact_paths(release)
    try:
        yield
    finally:
        activation.ARTIFACT_PATHS = original


def _acquire_lock() -> int:
    descriptor = -1
    try:
        descriptor = os.open(
            ARCHIVE_LOCK, os.O_RDWR | os.O_CREAT
            | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
            0o600,
        )
        info = os.fstat(descriptor)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0
                or info.st_gid != 0 or stat.S_IMODE(info.st_mode) != 0o600
                or info.st_nlink != 1):
            raise ArchiveError("TERMINAL_ARCHIVE_LOCK_UNSAFE")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ArchiveError("TERMINAL_ARCHIVE_ALREADY_RUNNING") from exc
        return descriptor
    except BaseException:
        if descriptor >= 0:
            os.close(descriptor)
        raise


def _ensure_archive_parent() -> int:
    base_fd = _open_directory(BACKUP_BASE, mode=0o755)
    try:
        try:
            os.mkdir(ARCHIVE_PARENT.name, 0o700, dir_fd=base_fd)
            os.fsync(base_fd)
        except FileExistsError:
            pass
    finally:
        os.close(base_fd)
    return _open_directory(ARCHIVE_PARENT, mode=0o700)


def _read_file(path: Path, *, mode: int, allow_empty: bool = False) -> bytes:
    descriptor = -1
    try:
        descriptor = os.open(
            path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
        )
        before = os.fstat(descriptor)
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != 0
                or before.st_gid != 0 or stat.S_IMODE(before.st_mode) != mode
                or before.st_nlink != 1
                or before.st_size > MAX_FILE_BYTES
                or (not allow_empty and before.st_size < 1)):
            raise ArchiveError("TERMINAL_ARCHIVE_FILE_UNSAFE")
        raw = b""
        while len(raw) < before.st_size:
            chunk = os.read(descriptor, before.st_size - len(raw))
            if not chunk:
                raise ArchiveError("TERMINAL_ARCHIVE_FILE_SHORT_READ")
            raw += chunk
        if os.read(descriptor, 1):
            raise ArchiveError("TERMINAL_ARCHIVE_FILE_GREW")
        after = os.fstat(descriptor)
        if ((before.st_dev, before.st_ino, before.st_mode, before.st_uid,
             before.st_gid, before.st_nlink, before.st_size,
             before.st_mtime_ns, before.st_ctime_ns)
                != (after.st_dev, after.st_ino, after.st_mode, after.st_uid,
                    after.st_gid, after.st_nlink, after.st_size,
                    after.st_mtime_ns, after.st_ctime_ns)):
            raise ArchiveError("TERMINAL_ARCHIVE_FILE_CHANGED")
        return raw
    except OSError as exc:
        raise ArchiveError("TERMINAL_ARCHIVE_FILE_UNSAFE") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _atomic_write(parent_fd: int, name: str, raw: bytes, *, mode: int) -> None:
    descriptor = -1
    try:
        descriptor = os.open(
            name, os.O_WRONLY | os.O_CREAT | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
            mode, dir_fd=parent_fd,
        )
        view = memoryview(raw)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise ArchiveError("TERMINAL_ARCHIVE_WRITE_FAILED")
            view = view[written:]
        os.fsync(descriptor)
    except OSError as exc:
        raise ArchiveError("TERMINAL_ARCHIVE_WRITE_FAILED") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    os.fsync(parent_fd)


def _rename_noreplace(source: Path, target: Path) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    renameat2 = getattr(libc, "renameat2", None)
    if renameat2 is None:
        raise ArchiveError("TERMINAL_ARCHIVE_ATOMIC_RENAME_UNAVAILABLE")
    renameat2.argtypes = [
        ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p,
        ctypes.c_uint,
    ]
    renameat2.restype = ctypes.c_int
    if renameat2(
        -100, os.fsencode(source), -100, os.fsencode(target), RENAME_NOREPLACE,
    ) != 0:
        code = ctypes.get_errno()
        if code == errno.EEXIST:
            raise ArchiveError("TERMINAL_ARCHIVE_TARGET_EXISTS")
        if code in {errno.ENOSYS, errno.EINVAL, errno.EOPNOTSUPP, errno.EXDEV}:
            raise ArchiveError("TERMINAL_ARCHIVE_ATOMIC_RENAME_UNAVAILABLE")
        raise ArchiveError("TERMINAL_ARCHIVE_RENAME_FAILED")


def _dormant() -> dict[str, Any]:
    report = watchdog.watchdog_once(
        container_name=activation.PRODUCTION_CONTAINER,
        expected_image_id=activation.PRODUCTION_IMAGE_ID,
        expected_volume_name=watchdog.PRODUCTION_VOLUME,
        expected_server_version_num=170011,
        expected_system_identifier=activation.PRODUCTION_SYSTEM_IDENTIFIER,
        allow_contract_container=False, require_dormant=True,
    )
    watchdog._require_exact_dormant(report, phase="TERMINAL_ARCHIVE")
    return report


def _verified_recovery(
    package: Mapping[str, Any], *, release: Path, nonce: str,
    decision_sha256: str,
) -> Any:
    request = package.get("request")
    if (package.get("stagedWithoutRequest") is not False
            or not isinstance(request, Mapping)
            or request.get("runNonce") != nonce
            or request.get("decisionSha256") != decision_sha256):
        raise ArchiveError("TERMINAL_ARCHIVE_RECOVERY_BINDING_MISMATCH")
    now, _evidence = activation.supervisor._trusted_now_epoch()
    with _signed_artifact_closure(release):
        recovery = activation.verify_cleanup_recovery(
            keyring_raw=package["keyring.json"],
            decision_raw=package["decision.json"],
            activation_plan_raw=package["activation-plan.json"],
            expected_keyring_sha256=request["expectedKeyringSha256"],
            expected_environment="PRODUCTION", now_epoch=now,
        )
    if (type(recovery) is not activation.VerifiedRecovery
            or recovery.run_nonce != nonce
            or recovery.decision_sha256 != decision_sha256
            or recovery.plan_sha256 != request["planSha256"]):
        raise ArchiveError("TERMINAL_ARCHIVE_VERIFIED_BINDING_MISMATCH")
    launch = launcher._load_launch_request()
    if any(launch[name] != request[target] for name, target in {
        "runNonce": "runNonce",
        "decisionSha256": "decisionSha256",
        "planSha256": "planSha256",
        "expectedKeyringSha256": "expectedKeyringSha256",
        "recoveryManifestSha256": "manifestSha256",
    }.items()):
        raise ArchiveError("TERMINAL_ARCHIVE_LAUNCH_BINDING_MISMATCH")
    return recovery


def _terminal_state(recovery: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    journal = activation.ActivationJournal(
        activation.PRODUCTION_JOURNAL_ROOT, recovery,
    ).inspect()
    if (journal.get("state") != "RECONCILED_HOLD"
            or journal.get("retryAllowed") is not False
            or journal.get("receiptSha256") is not None):
        raise ArchiveError("TERMINAL_ARCHIVE_JOURNAL_NOT_RECONCILED_HOLD")
    resources = executor_module.ExecutorResourceJournal(
        root=activation.PRODUCTION_RESOURCE_JOURNAL_ROOT,
        run_nonce=recovery.run_nonce, environment="PRODUCTION",
        target=recovery.target, plan_sha256=recovery.plan_sha256,
        decision_sha256=recovery.decision_sha256,
        derived_plan_sha256=recovery.derived_execution_plan_sha256,
        workspace_parent=activation.PRODUCTION_WORKSPACE_ROOT,
    ).inspect_optional()
    if (not isinstance(resources, Mapping)
            or resources.get("state") != "RECONCILED_HOLD"
            or resources.get("credentialIssued") is not False
            or resources.get("credentialReconciled") is not True
            or any(resources.get(name) is not True for name in (
                "workspaceAbsent", "proxyAbsent", "dumpAbsent",
                "restoreAbsent",
            ))):
        raise ArchiveError("TERMINAL_ARCHIVE_RESOURCES_NOT_RECONCILED_HOLD")
    if (not executor_module._path_entry_absent(
            activation.PRODUCTION_WORKSPACE_ROOT / resources["workspaceName"])
            or not executor_module._path_entry_absent(
                activation.PRODUCTION_PROXY_ROOT / resources["proxyName"])
            or executor_module._inspect_container(resources["dumpName"])
            is not None
            or executor_module._inspect_container(resources["restoreName"])
            is not None):
        raise ArchiveError("TERMINAL_ARCHIVE_RESOURCES_PRESENT")
    return journal, dict(resources)


def _component_sources() -> dict[str, Path]:
    return {name: factory() for name, factory in COMPONENTS.items()}


def _collect_files(nonce: str) -> dict[str, dict[str, Any]]:
    entries = _expected_files(
        nonce=nonce, activation_root=ACTIVATION_ROOT,
        recovery_parent=RECOVERY_PARENT,
    )
    result: dict[str, dict[str, Any]] = {}
    for relative, (path, mode, allow_empty) in entries.items():
        raw = _read_file(path, mode=mode, allow_empty=allow_empty)
        result[relative] = {
            "sha256": _sha(raw), "size": len(raw), "mode": mode,
        }
    return result


def _expected_files(
    *, nonce: str, activation_root: Path, recovery_parent: Path,
) -> dict[str, tuple[Path, int, bool]]:
    package = recovery_parent / watchdog.RECOVERY_PACKAGE_NAME
    return {
        "recovery-package/keyring.json": (package / "keyring.json", 0o400, False),
        "recovery-package/decision.json": (package / "decision.json", 0o400, False),
        "recovery-package/activation-plan.json": (
            package / "activation-plan.json", 0o400, False,
        ),
        "recovery-package/manifest.json": (
            package / watchdog.RECOVERY_MANIFEST_NAME, 0o400, False,
        ),
        "recovery-request.json": (
            recovery_parent / watchdog.RECOVERY_REQUEST_NAME, 0o400, False,
        ),
        "launch-request.json": (
            recovery_parent / launcher.LAUNCH_REQUEST_NAME, 0o400, False,
        ),
        f"activation-state/journal/{nonce}.json": (
            activation_root / "journal" / f"{nonce}.json", 0o600, False,
        ),
        f"activation-state/journal/.{nonce}.lock": (
            activation_root / "journal" / f".{nonce}.lock", 0o600, True,
        ),
        f"activation-state/resources/{nonce}.resources.json": (
            activation_root / "resources" / f"{nonce}.resources.json",
            0o600, False,
        ),
    }


def _validate_component_trees(nonce: str) -> None:
    root_fd = _open_directory(ACTIVATION_ROOT, mode=0o700)
    try:
        if set(os.listdir(root_fd)) != {"journal", "resources", "workspace", "proxy"}:
            raise ArchiveError("TERMINAL_ARCHIVE_STATE_ENTRY_SET_INVALID")
    finally:
        os.close(root_fd)
    for name, expected in {
        "journal": {f"{nonce}.json", f".{nonce}.lock"},
        "resources": {f"{nonce}.resources.json"},
        "workspace": set(), "proxy": set(),
    }.items():
        descriptor = _open_directory(ACTIVATION_ROOT / name, mode=0o700)
        try:
            if set(os.listdir(descriptor)) != expected:
                raise ArchiveError("TERMINAL_ARCHIVE_STATE_ENTRY_SET_INVALID")
        finally:
            os.close(descriptor)


def _manifest(
    *, release: Path, recovery: Any, journal: Mapping[str, Any],
    resources: Mapping[str, Any], dormant: Mapping[str, Any],
) -> bytes:
    container = dormant.get("container")
    if not isinstance(container, Mapping):
        raise ArchiveError("TERMINAL_ARCHIVE_DORMANT_TUPLE_INVALID")
    try:
        _raw, archiver_sha256 = activation._artifact_bytes_and_sha256(
            release / "deploy/postgres/b64_064a_terminal_evidence_archiver.py",
        )
    except activation.ActivationError as exc:
        raise ArchiveError("TERMINAL_ARCHIVE_IMPLEMENTATION_UNSAFE") from exc
    unsigned = {
        "schemaVersion": ARCHIVE_SCHEMA,
        "route": ROUTE,
        "runNonce": recovery.run_nonce,
        "decisionSha256": recovery.decision_sha256,
        "planSha256": recovery.plan_sha256,
        "keyringSha256": recovery.keyring_sha256,
        "implementationCommit": release.name,
        "archiverSha256": archiver_sha256,
        "signedArtifactReleaseCommit": SIGNED_ARTIFACT_RELEASE.name,
        "terminalState": journal["state"],
        "terminalReason": journal["reasonCode"],
        "resourceState": resources["state"],
        "credentialIssued": resources["credentialIssued"],
        "credentialReconciled": resources["credentialReconciled"],
        "workspaceAbsent": resources["workspaceAbsent"],
        "proxyAbsent": resources["proxyAbsent"],
        "dumpAbsent": resources["dumpAbsent"],
        "restoreAbsent": resources["restoreAbsent"],
        "roleLoginState": dormant["roleLoginState"],
        "credentialState": dormant["credentialState"],
        "activeSessions": dormant["activeSessions"],
        "containerId": container["containerId"],
        "containerPid": container["containerPid"],
        "imageId": container["imageId"],
        "systemIdentifier": dormant["systemIdentifier"],
        "files": _collect_files(recovery.run_nonce),
        "sourceComponents": sorted(COMPONENTS),
        "customerRowsRead": False,
        "hbaChanged": False,
        "authorityIncreased": False,
        "automaticRetryAllowed": False,
        "activationRetryAllowed": False,
    }
    value = {**unsigned, "manifestSha256": _sha(_canonical(unsigned))}
    return _canonical(value) + b"\n"


def _decode_manifest(raw: bytes, *, nonce: str, decision_sha256: str) -> dict[str, Any]:
    try:
        value = watchdog._decode_object(raw.rstrip(b"\n"), "TERMINAL_ARCHIVE_MANIFEST_INVALID")
    except watchdog.WatchdogError as exc:
        raise ArchiveError("TERMINAL_ARCHIVE_MANIFEST_INVALID") from exc
    digest = value.get("manifestSha256")
    unsigned = {key: item for key, item in value.items() if key != "manifestSha256"}
    if (value.get("schemaVersion") != ARCHIVE_SCHEMA
            or value.get("route") != ROUTE
            or value.get("runNonce") != nonce
            or value.get("decisionSha256") != decision_sha256
            or type(value.get("implementationCommit")) is not str
            or re.fullmatch(
                r"[0-9a-f]{40}", value["implementationCommit"],
            ) is None
            or type(value.get("archiverSha256")) is not str
            or re.fullmatch(r"[0-9a-f]{64}", value["archiverSha256"]) is None
            or value.get("signedArtifactReleaseCommit")
            != SIGNED_ARTIFACT_RELEASE.name
            or digest != _sha(_canonical(unsigned))
            or value.get("terminalState") != "RECONCILED_HOLD"
            or value.get("resourceState") != "RECONCILED_HOLD"
            or value.get("credentialIssued") is not False
            or value.get("credentialReconciled") is not True
            or value.get("automaticRetryAllowed") is not False
            or value.get("activationRetryAllowed") is not False
            or value.get("sourceComponents") != sorted(COMPONENTS)
            or not isinstance(value.get("files"), Mapping)):
        raise ArchiveError("TERMINAL_ARCHIVE_MANIFEST_INVALID")
    return value


def _archive_names(nonce: str) -> tuple[Path, Path]:
    return (
        ARCHIVE_PARENT / f".b64-064a-terminal-{nonce}.staging",
        ARCHIVE_PARENT / f"b64-064a-terminal-{nonce}",
    )


def _archive_leaf(
    archive_root: Path, relative: str, *, mode: int, allow_empty: bool,
) -> bytes:
    return _read_file(
        archive_root / relative, mode=mode, allow_empty=allow_empty,
    )


def _verify_component_trees(archive_root: Path, nonce: str) -> None:
    activation_root = archive_root / "activation-state"
    root_fd = _open_directory(activation_root, mode=0o700)
    try:
        if set(os.listdir(root_fd)) != {"journal", "resources", "workspace", "proxy"}:
            raise ArchiveError("TERMINAL_ARCHIVE_STATE_ENTRY_SET_INVALID")
    finally:
        os.close(root_fd)
    for name, expected in {
        "journal": {f"{nonce}.json", f".{nonce}.lock"},
        "resources": {f"{nonce}.resources.json"},
        "workspace": set(), "proxy": set(),
    }.items():
        descriptor = _open_directory(activation_root / name, mode=0o700)
        try:
            if set(os.listdir(descriptor)) != expected:
                raise ArchiveError("TERMINAL_ARCHIVE_STATE_ENTRY_SET_INVALID")
        finally:
            os.close(descriptor)
    package_fd = _open_directory(
        archive_root / "recovery-package", mode=0o500,
    )
    try:
        if set(os.listdir(package_fd)) != {
            "keyring.json", "decision.json", "activation-plan.json",
            watchdog.RECOVERY_MANIFEST_NAME,
        }:
            raise ArchiveError("TERMINAL_ARCHIVE_PACKAGE_ENTRY_SET_INVALID")
    finally:
        os.close(package_fd)


def _verify_archive(
    archive_root: Path, *, nonce: str, decision_sha256: str,
    root_mode: int,
) -> dict[str, Any]:
    root_fd = _open_directory(archive_root, mode=root_mode)
    try:
        if set(os.listdir(root_fd)) != {*COMPONENTS, MANIFEST_NAME}:
            raise ArchiveError("TERMINAL_ARCHIVE_ENTRY_SET_INVALID")
    finally:
        os.close(root_fd)
    manifest_raw = _read_file(archive_root / MANIFEST_NAME, mode=0o400)
    manifest = _decode_manifest(
        manifest_raw, nonce=nonce, decision_sha256=decision_sha256,
    )
    _verify_component_trees(archive_root, nonce)
    expected_files = _expected_files(
        nonce=nonce, activation_root=archive_root / "activation-state",
        recovery_parent=archive_root,
    )
    if set(manifest["files"]) != set(expected_files):
        raise ArchiveError("TERMINAL_ARCHIVE_FILE_ENTRY_SET_INVALID")
    for relative, binding in manifest["files"].items():
        _path, expected_mode, allow_empty = expected_files[relative]
        if (not isinstance(relative, str) or not isinstance(binding, Mapping)
                or set(binding) != {"sha256", "size", "mode"}
                or type(binding.get("size")) is not int
                or type(binding.get("mode")) is not int
                or binding["mode"] != expected_mode):
            raise ArchiveError("TERMINAL_ARCHIVE_FILE_BINDING_INVALID")
        raw = _archive_leaf(
            archive_root, relative, mode=expected_mode,
            allow_empty=allow_empty,
        )
        if (len(raw) != binding["size"] or _sha(raw) != binding["sha256"]):
            raise ArchiveError("TERMINAL_ARCHIVE_FILE_BINDING_MISMATCH")
    return manifest


def _normalize_component_for_move(
    component: str, path: Path, *, at_source: bool,
) -> None:
    """Validate a component and seal the read-only package after movement.

    Linux requires write permission on a directory whose ``..`` entry changes
    during a cross-parent rename.  The recovery package is normally 0500, so a
    crash-safe move uses 0700 only as a root-owned staging transition.  A
    resumed run accepts and completes either side of that exact transition.
    """
    try:
        info = os.lstat(path)
    except OSError as exc:
        raise ArchiveError("TERMINAL_ARCHIVE_COMPONENT_UNSAFE") from exc
    expected_type = stat.S_ISREG if component.endswith(".json") else stat.S_ISDIR
    allowed_modes = {
        "activation-state": {0o700},
        "launch-request.json": {0o400},
        "recovery-request.json": {0o400},
        "recovery-package": {0o500, 0o700},
    }[component]
    if (not expected_type(info.st_mode) or info.st_uid != 0 or info.st_gid != 0
            or stat.S_IMODE(info.st_mode) not in allowed_modes
            or (stat.S_ISREG(info.st_mode) and info.st_nlink != 1)):
        raise ArchiveError("TERMINAL_ARCHIVE_COMPONENT_UNSAFE")
    if component != "recovery-package":
        return
    required_mode = 0o700 if at_source else 0o500
    if stat.S_IMODE(info.st_mode) != required_mode:
        try:
            os.chmod(path, required_mode, follow_symlinks=False)
            descriptor = _open_directory(path, mode=required_mode)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        except OSError as exc:
            raise ArchiveError("TERMINAL_ARCHIVE_COMPONENT_SEAL_FAILED") from exc


def _path_exists(path: Path) -> bool:
    try:
        path.lstat()
        return True
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise ArchiveError("TERMINAL_ARCHIVE_PATH_UNSAFE") from exc


def _publish_archive(
    *, nonce: str, decision_sha256: str, manifest_raw: bytes,
    fault: FaultHook | None = None,
) -> tuple[Path, dict[str, Any], bool]:
    parent_fd = _ensure_archive_parent()
    staging, final = _archive_names(nonce)
    try:
        if _path_exists(final):
            manifest = _verify_archive(
                final, nonce=nonce, decision_sha256=decision_sha256,
                root_mode=0o500,
            )
            if any(_path_exists(path) for path in _component_sources().values()):
                raise ArchiveError("TERMINAL_ARCHIVE_FINAL_WITH_RUNTIME_PATHS")
            return final, manifest, True
        if not _path_exists(staging):
            os.mkdir(staging.name, 0o700, dir_fd=parent_fd)
            os.fsync(parent_fd)
            staging_fd = _open_directory(staging, mode=0o700)
            try:
                _atomic_write(staging_fd, MANIFEST_NAME, manifest_raw, mode=0o400)
            finally:
                os.close(staging_fd)
            if fault is not None:
                fault("after_manifest")
        else:
            existing = _read_file(staging / MANIFEST_NAME, mode=0o400)
            if existing != manifest_raw:
                raise ArchiveError("TERMINAL_ARCHIVE_STAGING_MANIFEST_MISMATCH")
        staging_fd = _open_directory(staging, mode=0o700)
        archive_device = os.fstat(parent_fd).st_dev
        try:
            for component, source in _component_sources().items():
                target = staging / component
                source_exists = _path_exists(source)
                target_exists = _path_exists(target)
                if source_exists == target_exists:
                    raise ArchiveError("TERMINAL_ARCHIVE_COMPONENT_LOCATION_INVALID")
                observed = source if source_exists else target
                if observed.lstat().st_dev != archive_device:
                    raise ArchiveError("TERMINAL_ARCHIVE_FILESYSTEM_MISMATCH")
                _normalize_component_for_move(
                    component, observed, at_source=source_exists,
                )
                if source_exists:
                    _rename_noreplace(source, target)
                    os.fsync(staging_fd)
                    source_parent_fd = os.open(
                        source.parent, os.O_RDONLY | os.O_DIRECTORY
                        | getattr(os, "O_NOFOLLOW", 0),
                    )
                    try:
                        os.fsync(source_parent_fd)
                    finally:
                        os.close(source_parent_fd)
                    _normalize_component_for_move(
                        component, target, at_source=False,
                    )
                    os.fsync(staging_fd)
                    if fault is not None:
                        fault(f"after_{component}_move")
            manifest = _verify_archive(
                staging, nonce=nonce, decision_sha256=decision_sha256,
                root_mode=0o700,
            )
            os.chmod(staging, 0o500, follow_symlinks=False)
            os.fsync(staging_fd)
            _rename_noreplace(staging, final)
            os.fsync(parent_fd)
            if fault is not None:
                fault("after_archive_publish")
        finally:
            os.close(staging_fd)
        manifest = _verify_archive(
            final, nonce=nonce, decision_sha256=decision_sha256,
            root_mode=0o500,
        )
        return final, manifest, False
    finally:
        os.close(parent_fd)


def archive_terminal_evidence(
    *, confirm_run_nonce: str, confirm_decision_sha256: str,
    fault: FaultHook | None = None,
) -> dict[str, Any]:
    nonce = _token(confirm_run_nonce, "TERMINAL_ARCHIVE_NONCE_INVALID")
    decision_sha256 = _digest(
        confirm_decision_sha256, "TERMINAL_ARCHIVE_DECISION_DIGEST_INVALID",
    )
    release = _verify_runtime_identity()
    pre = _dormant()
    lock_fd = _acquire_lock()
    execution_lock = -1
    try:
        with watchdog._activation_interlock_status() as activation_live:
            if activation_live:
                raise ArchiveError("TERMINAL_ARCHIVE_ACTIVATION_LIVE")
            staging, final = _archive_names(nonce)
            if _path_exists(final):
                manifest_raw = _read_file(final / MANIFEST_NAME, mode=0o400)
            elif _path_exists(staging):
                manifest_raw = _read_file(staging / MANIFEST_NAME, mode=0o400)
            else:
                package = watchdog._load_recovery_package()
                if package is None:
                    raise ArchiveError("TERMINAL_ARCHIVE_RECOVERY_PACKAGE_MISSING")
                recovery = _verified_recovery(
                    package, release=release, nonce=nonce,
                    decision_sha256=decision_sha256,
                )
                journal_object = activation.ActivationJournal(
                    activation.PRODUCTION_JOURNAL_ROOT, recovery,
                )
                execution_lock = journal_object.acquire_execution_lock()
                journal, resources = _terminal_state(recovery)
                _validate_component_trees(nonce)
                attestor = executor_module.BoundRecoveryExecutor(
                    container=activation.PRODUCTION_CONTAINER,
                    container_id=recovery.target["containerId"],
                    image_id=activation.PRODUCTION_IMAGE_ID,
                    system_identifier=activation.PRODUCTION_SYSTEM_IDENTIFIER,
                    workspace_parent=activation.PRODUCTION_WORKSPACE_ROOT,
                    proxy_parent=activation.PRODUCTION_PROXY_ROOT,
                    resource_journal_root=(
                        activation.PRODUCTION_RESOURCE_JOURNAL_ROOT
                    ),
                )
                dormant_attestation = attestor.attest_dormant()
                if (dormant_attestation.get("loginState") != "DISABLED"
                        or dormant_attestation.get("credentialState") != "ABSENT"
                        or dormant_attestation.get("activeSessions") != 0):
                    raise ArchiveError("TERMINAL_ARCHIVE_DORMANT_ATTESTATION_FAILED")
                manifest_raw = _manifest(
                    release=release, recovery=recovery, journal=journal,
                    resources=resources, dormant=pre,
                )
            archive, manifest, already = _publish_archive(
                nonce=nonce, decision_sha256=decision_sha256,
                manifest_raw=manifest_raw, fault=fault,
            )
    finally:
        if execution_lock >= 0:
            os.close(execution_lock)
        os.close(lock_fd)
    post = _dormant()
    return {
        "schemaVersion": "b64-064a-terminal-evidence-archive-receipt.v1",
        "route": ROUTE,
        "status": (
            "TERMINAL_EVIDENCE_ALREADY_ARCHIVED_RUNTIME_ABSENT"
            if already else "TERMINAL_EVIDENCE_ARCHIVED_RUNTIME_ABSENT"
        ),
        "runNonce": nonce,
        "decisionSha256": decision_sha256,
        "archivePath": str(archive),
        "archiveManifestSha256": manifest["manifestSha256"],
        "terminalState": manifest["terminalState"],
        "runtimePathsAbsent": all(
            not _path_exists(path) for path in _component_sources().values()
        ),
        "preWatchdogStatus": pre["status"],
        "postWatchdogStatus": post["status"],
        "customerRowsRead": False,
        "hbaChanged": False,
        "authorityIncreased": False,
        "automaticRetryAllowed": False,
        "activationRetryAllowed": False,
        "actionAllowed": False,
    }


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    value.add_argument("--confirm-run-nonce", required=True)
    value.add_argument("--confirm-decision-sha256", required=True)
    return value


def main() -> int:
    os.umask(0o077)
    args = parser().parse_args()
    try:
        result = archive_terminal_evidence(
            confirm_run_nonce=args.confirm_run_nonce,
            confirm_decision_sha256=args.confirm_decision_sha256,
        )
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0
    except BaseException as exc:
        print(json.dumps({
            "schemaVersion": "b64-064a-terminal-evidence-archive-receipt.v1",
            "route": ROUTE,
            "status": "NO_GO",
            "reason": _reason(exc),
            "runtimePathsState": "ABSENT_OR_UNCHANGED_OR_RESUMABLE_STAGING",
            "customerRowsRead": False,
            "hbaChanged": False,
            "authorityIncreased": False,
            "automaticRetryAllowed": False,
            "activationRetryAllowed": False,
            "actionAllowed": False,
        }, sort_keys=True, separators=(",", ":")))
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
