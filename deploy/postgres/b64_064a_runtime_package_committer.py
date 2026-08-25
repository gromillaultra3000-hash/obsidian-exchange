#!/usr/bin/env python3
"""Atomically commit one verified 064A package without starting activation.

This command has no arguments and no configurable paths.  It must execute from
the immutable release bound into the signed activation plan.  It re-verifies
the fresh two-party decision, exact production target and dormant state before
publishing the recovery package, four empty activation roots, recovery marker
and launch marker.  The launcher is intentionally never started here.
"""
from __future__ import annotations

import ctypes
import errno
import fcntl
import hashlib
import json
import os
import re
import secrets
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Mapping

import b64_064a_activation_entrypoint as activation
import b64_064a_activation_launcher as launcher
import b64_snapshot_reader_watchdog as watchdog


ROUTE = activation.ROUTE
RELEASE_BASE = Path(
    "/opt/obsidian-exchange/releases/e0-e0.3-b5.3-064a"
)
COORDINATION_ROOT = Path("/root/064A-activation-signing-active")
RECOVERY_PARENT = watchdog.RECOVERY_PARENT
ACTIVATION_ROOT = activation.PRODUCTION_ACTIVATION_ROOT
PYTHON = Path("/opt/obsidian-exchange/relay-venv/bin/python")
LOCK_PATH = Path("/run/lock/obsidian-b64-064a-package-commit.lock")
MINIMUM_COMMIT_WINDOW_SECONDS = 300
MAX_INPUT_BYTES = 1024 * 1024
MAX_SUBPROCESS_BYTES = 64 * 1024
STATE_NAMES = ("journal", "resources", "workspace", "proxy")
COORDINATION_FILES = {
    "activation-plan.json", "decision-unsigned.json", "decision.json",
    "keyring.json", "owner-signature.json", "reviewer-signature.json",
}
UNIT_FILES = (
    "obsidian-b64-064a-activation.service",
    "obsidian-b64-snapshot-reader-watchdog.service",
    "obsidian-postgres.service",
)
RENAME_NOREPLACE = 1
FaultHook = Callable[[str], None]


class CommitError(activation.ActivationError):
    """Closed reason code suitable for the secret-free commit receipt."""


def _reason(exc: BaseException) -> str:
    if (isinstance(exc, (
            CommitError, activation.ActivationError,
            watchdog.WatchdogError, launcher.LauncherError,
    )) and re.fullmatch(r"[A-Z0-9_]+", str(exc))):
        return str(exc)
    return "RUNTIME_PACKAGE_COMMIT_UNEXPECTED_FAILURE"


def _canonical(value: Any) -> bytes:
    try:
        return activation._canonical(value)
    except activation.ActivationError as exc:
        raise CommitError(str(exc)) from exc


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _metadata_identity(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev, value.st_ino, value.st_mode, value.st_uid,
        value.st_gid, value.st_nlink, value.st_size, value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _verify_runtime_identity() -> Path:
    """Require this process and every imported runtime module in one release."""
    if os.geteuid() != 0 or sys.argv != [sys.argv[0]]:
        raise CommitError("RUNTIME_COMMIT_FIXED_ROOT_COMMAND_REQUIRED")
    script = Path(__file__).resolve()
    try:
        release = script.parents[2]
    except IndexError as exc:
        raise CommitError("RUNTIME_COMMIT_RELEASE_IDENTITY_INVALID") from exc
    if (release.parent != RELEASE_BASE
            or re.fullmatch(r"[0-9a-f]{40}", release.name) is None):
        raise CommitError("RUNTIME_COMMIT_RELEASE_IDENTITY_INVALID")
    try:
        release_info = os.lstat(release)
        script_info = os.lstat(script)
    except OSError as exc:
        raise CommitError("RUNTIME_COMMIT_RELEASE_UNSAFE") from exc
    if (not stat.S_ISDIR(release_info.st_mode)
            or stat.S_ISLNK(release_info.st_mode)
            or release_info.st_uid != 0 or release_info.st_gid != 0
            or stat.S_IMODE(release_info.st_mode) != 0o555
            or not stat.S_ISREG(script_info.st_mode)
            or script_info.st_uid != 0 or script_info.st_gid != 0
            or stat.S_IMODE(script_info.st_mode) & 0o022
            or script_info.st_nlink != 1):
        raise CommitError("RUNTIME_COMMIT_RELEASE_UNSAFE")
    expected_modules = {
        activation: "b64_064a_activation_entrypoint.py",
        launcher: "b64_064a_activation_launcher.py",
        watchdog: "b64_snapshot_reader_watchdog.py",
    }
    for module, name in expected_modules.items():
        if Path(module.__file__).resolve() != release / "deploy/postgres" / name:
            raise CommitError("RUNTIME_COMMIT_MODULE_RELEASE_MISMATCH")
    for path in activation.ARTIFACT_PATHS.values():
        try:
            path.resolve().relative_to(release)
        except ValueError as exc:
            raise CommitError("RUNTIME_COMMIT_ARTIFACT_RELEASE_MISMATCH") \
                from exc
    for name in UNIT_FILES:
        installed = Path("/etc/systemd/system") / name
        try:
            installed_raw, _ = activation._artifact_bytes_and_sha256(installed)
        except activation.ActivationError as exc:
            raise CommitError("RUNTIME_COMMIT_UNIT_UNSAFE") from exc
        release_references = set(re.findall(
            rb"/opt/obsidian-exchange/releases/e0-e0\.3-b5\.3-064a/"
            rb"([0-9a-f]{40})/", installed_raw,
        ))
        if release_references != {release.name.encode("ascii")}:
            raise CommitError("RUNTIME_COMMIT_UNIT_RELEASE_MISMATCH")
    return release


def _open_root_directory(path: Path, *, exact_mode: int | None = None) -> int:
    if not path.is_absolute():
        raise CommitError("RUNTIME_COMMIT_PARENT_UNSAFE")
    try:
        descriptor = os.open(
            path, os.O_RDONLY | os.O_DIRECTORY
            | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
        )
        info = os.fstat(descriptor)
    except OSError as exc:
        raise CommitError("RUNTIME_COMMIT_PARENT_UNSAFE") from exc
    mode = stat.S_IMODE(info.st_mode)
    if (not stat.S_ISDIR(info.st_mode)
            or info.st_uid != 0 or info.st_gid != 0
            or mode & 0o022
            or (exact_mode is not None and mode != exact_mode)):
        os.close(descriptor)
        raise CommitError("RUNTIME_COMMIT_PARENT_UNSAFE")
    return descriptor


def _read_coordination_file(parent_fd: int, name: str) -> bytes:
    descriptor = -1
    try:
        descriptor = os.open(
            name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0), dir_fd=parent_fd,
        )
        before = os.fstat(descriptor)
        if (not stat.S_ISREG(before.st_mode)
                or before.st_uid != 0 or before.st_gid != 0
                or stat.S_IMODE(before.st_mode) != 0o600
                or before.st_nlink != 1
                or not 1 <= before.st_size <= MAX_INPUT_BYTES):
            raise CommitError("RUNTIME_COMMIT_COORDINATION_FILE_UNSAFE")
        chunks: list[bytes] = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(descriptor, min(65536, remaining))
            if not chunk:
                raise CommitError("RUNTIME_COMMIT_COORDINATION_SHORT_READ")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            raise CommitError("RUNTIME_COMMIT_COORDINATION_GREW")
        after = os.fstat(descriptor)
        if _metadata_identity(before) != _metadata_identity(after):
            raise CommitError("RUNTIME_COMMIT_COORDINATION_CHANGED")
        return b"".join(chunks)
    except OSError as exc:
        raise CommitError("RUNTIME_COMMIT_COORDINATION_FILE_UNSAFE") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _load_coordination() -> dict[str, bytes]:
    parent_fd = _open_root_directory(COORDINATION_ROOT, exact_mode=0o700)
    try:
        if set(os.listdir(parent_fd)) != COORDINATION_FILES:
            raise CommitError("RUNTIME_COMMIT_COORDINATION_ENTRY_SET_INVALID")
        result = {
            name: _read_coordination_file(parent_fd, name)
            for name in (
                "keyring.json", "activation-plan.json", "decision.json",
            )
        }
        if set(os.listdir(parent_fd)) != COORDINATION_FILES:
            raise CommitError("RUNTIME_COMMIT_COORDINATION_CHANGED")
        return result
    finally:
        os.close(parent_fd)


def _fixed_subprocess(arguments: list[str], *, timeout: int) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            arguments, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
            close_fds=True, timeout=timeout, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CommitError("RUNTIME_COMMIT_FIXED_VERIFIER_UNAVAILABLE") from exc
    if (completed.returncode != 0 or completed.stderr
            or not 1 <= len(completed.stdout) <= MAX_SUBPROCESS_BYTES
            or completed.stdout.count(b"\n") > 1):
        raise CommitError("RUNTIME_COMMIT_FIXED_VERIFIER_REJECTED")
    try:
        value = activation._decode_json(completed.stdout.rstrip(b"\n"))
    except activation.ActivationError as exc:
        raise CommitError("RUNTIME_COMMIT_FIXED_VERIFIER_REJECTED") from exc
    return value


def _dormant_tuple(release: Path) -> dict[str, Any]:
    report = _fixed_subprocess([
        str(PYTHON), "-E",
        str(release / "deploy/postgres/b64_snapshot_reader_watchdog.py"),
        "--expected-image-id", activation.PRODUCTION_IMAGE_ID,
        "--expected-server-version-num", "170011", "--require-dormant",
    ], timeout=60)
    container = report.get("container")
    if (report.get("status") != "DORMANT_VERIFIED"
            or report.get("watchdogReady") is not True
            or report.get("roleLoginState") != "DISABLED"
            or report.get("credentialState") != "ABSENT"
            or report.get("activeSessions") != 0
            or report.get("customerRowsRead") is not False
            or report.get("authorityIncreased") is not False
            or report.get("systemIdentifier")
            != activation.PRODUCTION_SYSTEM_IDENTIFIER
            or not isinstance(container, Mapping)
            or container.get("health") != "healthy"
            or container.get("imageId") != activation.PRODUCTION_IMAGE_ID
            or container.get("restartCount") != 0
            or type(container.get("containerPid")) is not int
            or container["containerPid"] <= 1
            or re.fullmatch(
                r"[0-9a-f]{64}", str(container.get("containerId", "")),
            ) is None):
        raise CommitError("RUNTIME_COMMIT_PRODUCTION_NOT_DORMANT")
    return {
        "containerName": activation.PRODUCTION_CONTAINER,
        "containerId": container["containerId"],
        "imageId": container["imageId"],
        "systemIdentifier": report["systemIdentifier"],
    }


def _trusted_now() -> int:
    try:
        value, _evidence = activation.supervisor._trusted_now_epoch()
    except activation.supervisor.SupervisorError as exc:
        raise CommitError(str(exc)) from exc
    return value


def _load_and_verify(release: Path) -> tuple[dict[str, bytes], Any]:
    inputs = _load_coordination()
    try:
        keyring = activation._decode_json(inputs["keyring.json"])
    except activation.ActivationError as exc:
        raise CommitError(str(exc)) from exc
    expected_keyring = keyring.get("keyringSha256")
    if (type(expected_keyring) is not str
            or re.fullmatch(r"[0-9a-f]{64}", expected_keyring) is None):
        raise CommitError("RUNTIME_COMMIT_KEYRING_DIGEST_INVALID")
    now = _trusted_now()
    try:
        verified = activation.verify_activation_decision(
            keyring_raw=inputs["keyring.json"],
            decision_raw=inputs["decision.json"],
            activation_plan_raw=inputs["activation-plan.json"],
            expected_keyring_sha256=expected_keyring,
            expected_environment="PRODUCTION", now_epoch=now,
        )
    except activation.ActivationError as exc:
        raise CommitError(str(exc)) from exc
    if verified.expires_at_epoch - now < MINIMUM_COMMIT_WINDOW_SECONDS:
        raise CommitError("INSUFFICIENT_DECISION_WINDOW_REMAINING")
    observed = _dormant_tuple(release)
    target = verified.target
    if any(observed[name] != target.get(name) for name in observed):
        raise CommitError("RUNTIME_COMMIT_PRODUCTION_TARGET_MISMATCH")
    return inputs, verified


def _acquire_lock() -> int:
    descriptor = -1
    try:
        descriptor = os.open(
            LOCK_PATH, os.O_RDWR | os.O_CREAT
            | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
            0o600,
        )
        info = os.fstat(descriptor)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0
                or info.st_gid != 0 or stat.S_IMODE(info.st_mode) != 0o600
                or info.st_nlink != 1):
            raise CommitError("RUNTIME_COMMIT_LOCK_UNSAFE")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise CommitError("RUNTIME_COMMIT_ALREADY_RUNNING") from exc
        return descriptor
    except BaseException as exc:
        if descriptor >= 0:
            os.close(descriptor)
        if isinstance(exc, CommitError):
            raise
        raise CommitError("RUNTIME_COMMIT_LOCK_UNSAFE") from exc


def _assert_absent(parent_fd: int, name: str) -> None:
    try:
        os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    except OSError as exc:
        raise CommitError("RUNTIME_COMMIT_TARGET_UNSAFE") from exc
    raise CommitError("RUNTIME_COMMIT_TARGET_ALREADY_EXISTS")


def _stage_file(parent_fd: int, name: str, raw: bytes, *, mode: int) -> None:
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
                raise CommitError("RUNTIME_COMMIT_STAGE_WRITE_FAILED")
            view = view[written:]
        os.fsync(descriptor)
        info = os.fstat(descriptor)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0
                or info.st_gid != 0 or stat.S_IMODE(info.st_mode) != mode
                or info.st_nlink != 1 or info.st_size != len(raw)):
            raise CommitError("RUNTIME_COMMIT_STAGE_METADATA_INVALID")
    except OSError as exc:
        raise CommitError("RUNTIME_COMMIT_STAGE_WRITE_FAILED") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _publish_directory_noreplace(
    source_parent_fd: int, source: str, target_parent_fd: int, target: str,
    *, published: dict[str, bool], publication_key: str,
) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    renameat2 = getattr(libc, "renameat2", None)
    if renameat2 is None:
        raise CommitError("ATOMIC_DIRECTORY_PUBLICATION_UNAVAILABLE")
    renameat2.argtypes = [
        ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p,
        ctypes.c_uint,
    ]
    renameat2.restype = ctypes.c_int
    if renameat2(
        source_parent_fd, os.fsencode(source), target_parent_fd,
        os.fsencode(target), RENAME_NOREPLACE,
    ) != 0:
        code = ctypes.get_errno()
        if code == errno.EEXIST:
            raise CommitError("RUNTIME_COMMIT_TARGET_ALREADY_EXISTS")
        if code in {errno.ENOSYS, errno.EINVAL, errno.EOPNOTSUPP}:
            raise CommitError("ATOMIC_DIRECTORY_PUBLICATION_UNAVAILABLE")
        raise CommitError("RUNTIME_COMMIT_DIRECTORY_PUBLICATION_FAILED")
    published[publication_key] = True
    try:
        os.fsync(source_parent_fd)
        if target_parent_fd != source_parent_fd:
            os.fsync(target_parent_fd)
    except OSError as exc:
        raise CommitError("RUNTIME_COMMIT_DIRECTORY_PUBLICATION_FAILED") \
            from exc


def _publish_file_noreplace(
    parent_fd: int, temporary: str, final: str, *,
    published: dict[str, bool], publication_key: str,
) -> None:
    try:
        os.link(
            temporary, final, src_dir_fd=parent_fd, dst_dir_fd=parent_fd,
            follow_symlinks=False,
        )
        published[publication_key] = True
        os.unlink(temporary, dir_fd=parent_fd)
        os.fsync(parent_fd)
    except OSError as exc:
        raise CommitError("RUNTIME_COMMIT_MARKER_PUBLICATION_FAILED") from exc


def _remove_file(parent_fd: int, name: str) -> None:
    try:
        os.unlink(name, dir_fd=parent_fd)
    except FileNotFoundError:
        return


def _remove_package(parent_fd: int, name: str) -> None:
    try:
        package_fd = os.open(
            name, os.O_RDONLY | os.O_DIRECTORY
            | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
            dir_fd=parent_fd,
        )
    except FileNotFoundError:
        return
    try:
        info = os.fstat(package_fd)
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != 0
                or info.st_gid != 0
                or stat.S_IMODE(info.st_mode) not in {0o500, 0o700}):
            raise CommitError("RUNTIME_COMMIT_ROLLBACK_PACKAGE_CHANGED")
        os.fchmod(package_fd, 0o700)
        entries = set(os.listdir(package_fd))
        expected = {watchdog.RECOVERY_MANIFEST_NAME, *watchdog.RECOVERY_FILES}
        if not entries.issubset(expected):
            raise CommitError("RUNTIME_COMMIT_ROLLBACK_PACKAGE_CHANGED")
        for entry in entries:
            _remove_file(package_fd, entry)
    finally:
        os.close(package_fd)
    os.rmdir(name, dir_fd=parent_fd)


def _remove_state(parent_fd: int, name: str) -> None:
    try:
        state_fd = os.open(
            name, os.O_RDONLY | os.O_DIRECTORY
            | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
            dir_fd=parent_fd,
        )
    except FileNotFoundError:
        return
    try:
        entries = set(os.listdir(state_fd))
        if not entries.issubset(STATE_NAMES):
            raise CommitError("RUNTIME_COMMIT_ROLLBACK_STATE_CHANGED")
        for entry in entries:
            child_fd = os.open(
                entry, os.O_RDONLY | os.O_DIRECTORY
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0), dir_fd=state_fd,
            )
            try:
                if os.listdir(child_fd):
                    raise CommitError("RUNTIME_COMMIT_ROLLBACK_STATE_CHANGED")
            finally:
                os.close(child_fd)
            os.rmdir(entry, dir_fd=state_fd)
    finally:
        os.close(state_fd)
    os.rmdir(name, dir_fd=parent_fd)


def _cleanup_staged(
    recovery_fd: int, activation_parent_fd: int, names: Mapping[str, str],
) -> None:
    for name in (names["recovery_tmp"], names["launch_tmp"]):
        try:
            _remove_file(recovery_fd, name)
        except OSError:
            pass
    try:
        _remove_package(recovery_fd, names["package_tmp"])
    except OSError:
        pass
    try:
        _remove_state(activation_parent_fd, names["state_tmp"])
    except OSError:
        pass


def _rollback(
    recovery_fd: int, activation_parent_fd: int, names: Mapping[str, str],
    published: Mapping[str, bool],
) -> None:
    try:
        if published["launch"]:
            _remove_file(recovery_fd, launcher.LAUNCH_REQUEST_NAME)
        if published["recovery"]:
            _remove_file(recovery_fd, watchdog.RECOVERY_REQUEST_NAME)
        if published["state"]:
            _remove_state(activation_parent_fd, ACTIVATION_ROOT.name)
        if published["package"]:
            _remove_package(recovery_fd, watchdog.RECOVERY_PACKAGE_NAME)
        _cleanup_staged(recovery_fd, activation_parent_fd, names)
        os.fsync(recovery_fd)
        os.fsync(activation_parent_fd)
    except BaseException as exc:
        raise CommitError("RUNTIME_COMMIT_ROLLBACK_FAILED") from exc


def _payloads(
    inputs: Mapping[str, bytes], verified: Any,
) -> tuple[dict[str, bytes], bytes, bytes, bytes]:
    artifacts = {
        "keyring.json": inputs["keyring.json"],
        "decision.json": inputs["decision.json"],
        "activation-plan.json": inputs["activation-plan.json"],
    }
    binding = {
        "route": ROUTE,
        "environment": "PRODUCTION",
        "runNonce": verified.run_nonce,
        "action": watchdog.RECOVERY_ACTION,
        "automaticRetryAllowed": False,
        "expectedKeyringSha256": verified.keyring_sha256,
        "planSha256": verified.plan_sha256,
        "decisionSha256": verified.decision_sha256,
    }
    manifest = {
        "schemaVersion": watchdog.RECOVERY_PACKAGE_SCHEMA,
        **binding,
        "files": {
            name: {"sha256": _sha(raw), "size": len(raw)}
            for name, raw in artifacts.items()
        },
    }
    manifest_raw = _canonical(manifest) + b"\n"
    manifest_sha = _sha(manifest_raw)
    recovery_raw = _canonical({
        "schemaVersion": watchdog.RECOVERY_REQUEST_SCHEMA,
        **binding,
        "manifestSha256": manifest_sha,
    }) + b"\n"
    launch_raw = _canonical({
        "schemaVersion": launcher.LAUNCH_REQUEST_SCHEMA,
        "route": ROUTE,
        "environment": "PRODUCTION",
        "runNonce": verified.run_nonce,
        "action": launcher.LAUNCH_ACTION,
        "operatorCommitOnly": True,
        "grantsAuthority": False,
        "automaticRetryAllowed": False,
        "expectedKeyringSha256": verified.keyring_sha256,
        "planSha256": verified.plan_sha256,
        "decisionSha256": verified.decision_sha256,
        "recoveryManifestSha256": manifest_sha,
    }) + b"\n"
    return artifacts, manifest_raw, recovery_raw, launch_raw


def _stage_package(
    recovery_fd: int, name: str, artifacts: Mapping[str, bytes],
    manifest_raw: bytes,
) -> None:
    os.mkdir(name, 0o700, dir_fd=recovery_fd)
    package_fd = os.open(
        name, os.O_RDONLY | os.O_DIRECTORY
        | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
        dir_fd=recovery_fd,
    )
    try:
        for entry, raw in artifacts.items():
            _stage_file(package_fd, entry, raw, mode=0o400)
        _stage_file(
            package_fd, watchdog.RECOVERY_MANIFEST_NAME,
            manifest_raw, mode=0o400,
        )
        os.fsync(package_fd)
    finally:
        os.close(package_fd)
    os.chmod(name, 0o500, dir_fd=recovery_fd, follow_symlinks=False)
    os.fsync(recovery_fd)


def _stage_state(activation_parent_fd: int, name: str) -> None:
    os.mkdir(name, 0o700, dir_fd=activation_parent_fd)
    state_fd = os.open(
        name, os.O_RDONLY | os.O_DIRECTORY
        | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
        dir_fd=activation_parent_fd,
    )
    try:
        for entry in STATE_NAMES:
            os.mkdir(entry, 0o700, dir_fd=state_fd)
        os.fsync(state_fd)
    finally:
        os.close(state_fd)
    os.fsync(activation_parent_fd)


def _postverify(inputs: Mapping[str, bytes], verified: Any, release: Path) -> None:
    package = watchdog._load_recovery_package()
    request = launcher._load_launch_request()
    if (package is None or package.get("stagedWithoutRequest") is not False
            or any(package.get(name) != raw for name, raw in {
                "keyring.json": inputs["keyring.json"],
                "decision.json": inputs["decision.json"],
                "activation-plan.json": inputs["activation-plan.json"],
            }.items())
            or request["runNonce"] != verified.run_nonce
            or request["expectedKeyringSha256"] != verified.keyring_sha256
            or request["planSha256"] != verified.plan_sha256
            or request["decisionSha256"] != verified.decision_sha256):
        raise CommitError("RUNTIME_COMMIT_POSTVERIFY_BINDING_MISMATCH")
    activation._require_empty_production_activation_state()
    now = _trusted_now()
    try:
        observed = activation.verify_activation_decision(
            keyring_raw=package["keyring.json"],
            decision_raw=package["decision.json"],
            activation_plan_raw=package["activation-plan.json"],
            expected_keyring_sha256=verified.keyring_sha256,
            expected_environment="PRODUCTION", now_epoch=now,
        )
    except activation.ActivationError as exc:
        raise CommitError(str(exc)) from exc
    if (observed.run_nonce != verified.run_nonce
            or observed.plan_sha256 != verified.plan_sha256
            or observed.decision_sha256 != verified.decision_sha256):
        raise CommitError("RUNTIME_COMMIT_POSTVERIFY_BINDING_MISMATCH")
    dormant = _dormant_tuple(release)
    if any(dormant[name] != verified.target.get(name) for name in dormant):
        raise CommitError("RUNTIME_COMMIT_PRODUCTION_TARGET_MISMATCH")


def commit_runtime_package(
    *, fault: FaultHook | None = None,
) -> dict[str, Any]:
    release = _verify_runtime_identity()
    lock_fd = _acquire_lock()
    recovery_fd = -1
    activation_parent_fd = -1
    try:
        inputs, verified = _load_and_verify(release)
        recovery_fd = _open_root_directory(RECOVERY_PARENT)
        activation_parent_fd = _open_root_directory(ACTIVATION_ROOT.parent)
        for name in (
            watchdog.RECOVERY_PACKAGE_NAME,
            watchdog.RECOVERY_REQUEST_NAME,
            launcher.LAUNCH_REQUEST_NAME,
        ):
            _assert_absent(recovery_fd, name)
        _assert_absent(activation_parent_fd, ACTIVATION_ROOT.name)
        artifacts, manifest_raw, recovery_raw, launch_raw = _payloads(
            inputs, verified,
        )
        token = secrets.token_hex(12)
        names = {
            "package_tmp": f".{watchdog.RECOVERY_PACKAGE_NAME}.tmp-{token}",
            "state_tmp": f".{ACTIVATION_ROOT.name}.tmp-{token}",
            "recovery_tmp": f".{watchdog.RECOVERY_REQUEST_NAME}.tmp-{token}",
            "launch_tmp": f".{launcher.LAUNCH_REQUEST_NAME}.tmp-{token}",
        }
        published = {
            "package": False, "state": False,
            "recovery": False, "launch": False,
        }
        try:
            _stage_package(
                recovery_fd, names["package_tmp"], artifacts, manifest_raw,
            )
            _stage_state(activation_parent_fd, names["state_tmp"])
            _stage_file(
                recovery_fd, names["recovery_tmp"], recovery_raw, mode=0o400,
            )
            _stage_file(
                recovery_fd, names["launch_tmp"], launch_raw, mode=0o400,
            )
            os.fsync(recovery_fd)
            if fault is not None:
                fault("after_staging")
            _publish_directory_noreplace(
                recovery_fd, names["package_tmp"], recovery_fd,
                watchdog.RECOVERY_PACKAGE_NAME, published=published,
                publication_key="package",
            )
            if fault is not None:
                fault("after_package_publish")
            _publish_directory_noreplace(
                activation_parent_fd, names["state_tmp"],
                activation_parent_fd, ACTIVATION_ROOT.name,
                published=published, publication_key="state",
            )
            if fault is not None:
                fault("after_state_publish")
            _publish_file_noreplace(
                recovery_fd, names["recovery_tmp"],
                watchdog.RECOVERY_REQUEST_NAME, published=published,
                publication_key="recovery",
            )
            if fault is not None:
                fault("after_recovery_request_publish")
            _publish_file_noreplace(
                recovery_fd, names["launch_tmp"],
                launcher.LAUNCH_REQUEST_NAME, published=published,
                publication_key="launch",
            )
            if fault is not None:
                fault("after_launch_request_publish")
            _postverify(inputs, verified, release)
            if fault is not None:
                fault("after_postverify")
        except BaseException:
            _rollback(
                recovery_fd, activation_parent_fd, names, published,
            )
            raise
        return {
            "schemaVersion": "b64-064a-runtime-package-commit-receipt.v1",
            "route": ROUTE,
            "status": "RUNTIME_PACKAGE_COMMITTED_LAUNCHER_NOT_STARTED",
            "runNonce": verified.run_nonce,
            "expectedKeyringSha256": verified.keyring_sha256,
            "planSha256": verified.plan_sha256,
            "decisionSha256": verified.decision_sha256,
            "recoveryManifestSha256": _sha(manifest_raw),
            "runtimePackageCommitted": True,
            "runtimePathsState": "COMMITTED_VERIFIED",
            "emptyActivationStateCreated": True,
            "launcherStarted": False,
            "automaticRetryAllowed": False,
            "actionAllowed": False,
        }
    finally:
        if activation_parent_fd >= 0:
            os.close(activation_parent_fd)
        if recovery_fd >= 0:
            os.close(recovery_fd)
        os.close(lock_fd)


def main() -> int:
    os.umask(0o077)
    try:
        receipt = commit_runtime_package()
        code = 0
    except BaseException as exc:
        rollback_uncertain = str(exc) == "RUNTIME_COMMIT_ROLLBACK_FAILED"
        receipt = {
            "schemaVersion": "b64-064a-runtime-package-commit-receipt.v1",
            "route": ROUTE,
            "status": "NO_GO",
            "reason": _reason(exc),
            "runtimePackageCommitted": None if rollback_uncertain else False,
            "runtimePathsState": (
                "UNKNOWN_REQUIRES_MANUAL_INSPECTION"
                if rollback_uncertain else "ABSENT_OR_UNCHANGED"
            ),
            "launcherStarted": False,
            "automaticRetryAllowed": False,
            "actionAllowed": False,
        }
        code = 3
    print(json.dumps(receipt, sort_keys=True, separators=(",", ":")))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
