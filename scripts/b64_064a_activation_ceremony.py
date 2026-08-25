#!/usr/bin/env python3
"""Fresh two-party v3 signing ceremony for one production 064A activation.

Online commands are fixed to one root-only coordination directory, the exact
deployed immutable release and the fixed production container.  They create no
runtime request, touch no activation state and start no service.  ``sign`` is
the only offline command; it accepts an encrypted key on the signer device and
returns one detached signature.
"""
from __future__ import annotations

import argparse
import base64
import errno
import getpass
import hashlib
import io
import json
import os
import re
import secrets
import stat
import subprocess
import sys
import tarfile
from pathlib import Path
from typing import Any, Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey, Ed25519PublicKey,
)


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "deploy/postgres"))
import b64_064a_activation_entrypoint as activation  # noqa: E402


IMPLEMENTATION_COMMIT = "8231d1ec61345118b184163e912abb63712fea0a"
RELEASE_ROOT = Path(
    "/opt/obsidian-exchange/releases/e0-e0.3-b5.3-064a"
) / IMPLEMENTATION_COMMIT
PYTHON = Path("/opt/obsidian-exchange/relay-venv/bin/python")
COORDINATION_ROOT = Path("/root/064A-activation-signing-active")
PUBLIC_KEY_SCHEMA = "b64-064a-evidence-public-key.v1"
DETACHED_SIGNATURE_SCHEMA = \
    "b64-064a-production-activation-detached-signature.v1"
DECISION_LIFETIME_SECONDS = activation.MAX_DECISION_LIFETIME_SECONDS
MINIMUM_ASSEMBLY_WINDOW_SECONDS = 300
MAX_FILE_BYTES = 1024 * 1024
MAX_SUBPROCESS_BYTES = 64 * 1024
MAX_ARCHIVE_BYTES = 2 * 1024 * 1024
SERVER_FILES = {
    "activation-plan.json", "decision-unsigned.json", "decision.json",
    "keyring.json", "owner-signature.json", "reviewer-signature.json",
}
UNIT_FILES = (
    "obsidian-b64-064a-activation.service",
    "obsidian-b64-snapshot-reader-watchdog.service",
    "obsidian-postgres.service",
)
OFFLINE_KIT_FILES = (
    "deploy/postgres/b64_064a_activation_entrypoint.py",
    "deploy/postgres/b64_064a_hardened_refresh.py",
    "deploy/postgres/b64_064a_runtime_package_committer.py",
    "deploy/postgres/b64_dump_restore_supervisor.py",
    "docs/e0-3-bot-b5-3-064a-activation-trust-registry.v1.json",
    "docs/e0-3-bot-b5-3-064a-hardened-refresh-plan.v1.json",
    "scripts/b64_064a_activation_ceremony.py",
)
OFFLINE_KIT_SCHEMA = "b64-064a-production-activation-offline-kit.v1"
SIGNING_REQUEST_SCHEMA = \
    "b64-064a-production-activation-signing-request.v1"


class CeremonyError(RuntimeError):
    """Closed reason code suitable for a secret-free receipt."""


def _reason(exc: BaseException) -> str:
    if (isinstance(exc, (CeremonyError, activation.ActivationError,
                         activation.supervisor.SupervisorError))
            and re.fullmatch(r"[A-Z0-9_]+", str(exc))):
        return str(exc)
    return "UNEXPECTED_ACTIVATION_CEREMONY_FAILURE"


def _canonical(value: Any) -> bytes:
    try:
        return activation._canonical(value)
    except activation.ActivationError as exc:
        raise CeremonyError(str(exc)) from exc


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in items:
        if key in value:
            raise CeremonyError("DUPLICATE_JSON_KEY")
        value[key] = item
    return value


def _decode_json(raw: bytes) -> dict[str, Any]:
    try:
        value = json.loads(
            raw.decode("utf-8"), object_pairs_hook=_pairs,
            parse_float=lambda _: (_ for _ in ()).throw(
                CeremonyError("FLOAT_FORBIDDEN")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CeremonyError("INVALID_JSON") from exc
    if not isinstance(value, dict):
        raise CeremonyError("INVALID_JSON_ROOT")
    _canonical(value)
    return value


def _token(value: Any, code: str) -> str:
    if (type(value) is not str or not 1 <= len(value) <= 128
            or re.fullmatch(r"[A-Za-z0-9_-]+", value) is None):
        raise CeremonyError(code)
    return value


def _metadata_identity(info: os.stat_result) -> tuple[int, ...]:
    return (
        info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
        info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns,
    )


def _open_private_parent(path: Path) -> int:
    if (not path.is_absolute() or path.name in {"", ".", ".."}
            or ".." in path.parts):
        raise CeremonyError("PATH_NOT_ABSOLUTE_OR_SAFE")
    try:
        descriptor = os.open(
            path.parent,
            os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
        )
        info = os.fstat(descriptor)
    except OSError as exc:
        raise CeremonyError("UNSAFE_PARENT") from exc
    if (info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o700):
        os.close(descriptor)
        raise CeremonyError("UNSAFE_PARENT")
    return descriptor


def _read_from_parent(
    parent_fd: int, name: str, *, private: bool = False,
) -> bytes:
    if re.fullmatch(r"[A-Za-z0-9_.-]+", name) is None:
        raise CeremonyError("UNSAFE_INPUT_NAME")
    try:
        descriptor = os.open(
            name,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            dir_fd=parent_fd,
        )
    except OSError as exc:
        raise CeremonyError("UNSAFE_INPUT") from exc
    try:
        before = os.fstat(descriptor)
        mode = stat.S_IMODE(before.st_mode)
        if (not stat.S_ISREG(before.st_mode)
                or before.st_uid != os.getuid() or before.st_nlink != 1
                or not 1 <= before.st_size <= MAX_FILE_BYTES
                or (private and mode != 0o600)
                or (not private and mode & 0o022)):
            raise CeremonyError("UNSAFE_INPUT")
        chunks: list[bytes] = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(descriptor, min(65536, remaining))
            if not chunk:
                raise CeremonyError("INPUT_SHORT_READ")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            raise CeremonyError("INPUT_GREW")
        after = os.fstat(descriptor)
        if _metadata_identity(before) != _metadata_identity(after):
            raise CeremonyError("INPUT_CHANGED")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _read_path(path_text: str, *, private: bool = False) -> bytes:
    path = Path(path_text)
    parent_fd = _open_private_parent(path)
    try:
        return _read_from_parent(parent_fd, path.name, private=private)
    finally:
        os.close(parent_fd)


def _atomic_write_parent(parent_fd: int, name: str, raw: bytes) -> str:
    if re.fullmatch(r"[A-Za-z0-9_.-]+", name) is None:
        raise CeremonyError("UNSAFE_OUTPUT_NAME")
    if not 1 <= len(raw) <= MAX_FILE_BYTES:
        raise CeremonyError("OUTPUT_SIZE_INVALID")
    temporary = f".{name}.tmp-{secrets.token_hex(12)}"
    descriptor = -1
    published = False
    try:
        try:
            os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise CeremonyError("OUTPUT_ALREADY_EXISTS_OR_UNSAFE")
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
            0o600, dir_fd=parent_fd,
        )
        view = memoryview(raw)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise CeremonyError("OUTPUT_WRITE_FAILED")
            view = view[written:]
        os.fsync(descriptor)
        info = os.fstat(descriptor)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_nlink != 1
                or stat.S_IMODE(info.st_mode) != 0o600
                or info.st_size != len(raw)):
            raise CeremonyError("OUTPUT_METADATA_INVALID")
        os.close(descriptor)
        descriptor = -1
        os.link(
            temporary, name,
            src_dir_fd=parent_fd, dst_dir_fd=parent_fd,
            follow_symlinks=False,
        )
        published = True
        os.unlink(temporary, dir_fd=parent_fd)
        os.fsync(parent_fd)
    except BaseException:
        if descriptor >= 0:
            os.close(descriptor)
        if published:
            try:
                os.unlink(name, dir_fd=parent_fd)
            except OSError:
                pass
        try:
            os.unlink(temporary, dir_fd=parent_fd)
        except OSError:
            pass
        raise
    return _sha(raw)


def _atomic_write_path(path_text: str, raw: bytes) -> str:
    path = Path(path_text)
    parent_fd = _open_private_parent(path)
    try:
        return _atomic_write_parent(parent_fd, path.name, raw)
    finally:
        os.close(parent_fd)


def _write_offline_path(path_text: str, raw: bytes) -> str:
    """Write one signer result without requiring filesystem hard links.

    Android app-private filesystems may reject hard links even for files owned
    by the calling app.  Offline output is therefore created exclusively at
    its final name inside the already verified private directory.  A caller
    must observe the successful receipt before transferring the result; a
    failed write is removed and an existing name is never replaced.
    """
    path = Path(path_text)
    parent_fd = _open_private_parent(path)
    descriptor = -1
    created = False
    try:
        if re.fullmatch(r"[A-Za-z0-9_.-]+", path.name) is None:
            raise CeremonyError("UNSAFE_OUTPUT_NAME")
        if not 1 <= len(raw) <= MAX_FILE_BYTES:
            raise CeremonyError("OUTPUT_SIZE_INVALID")
        try:
            os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise CeremonyError("OUTPUT_ALREADY_EXISTS_OR_UNSAFE")
        try:
            descriptor = os.open(
                path.name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0),
                0o600, dir_fd=parent_fd,
            )
            created = True
            view = memoryview(raw)
            while view:
                written = os.write(descriptor, view)
                if written <= 0:
                    raise CeremonyError("OUTPUT_WRITE_FAILED")
                view = view[written:]
            os.fsync(descriptor)
            info = os.fstat(descriptor)
        except OSError as exc:
            raise CeremonyError("OUTPUT_WRITE_FAILED") from exc
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_nlink != 1
                or stat.S_IMODE(info.st_mode) != 0o600
                or info.st_size != len(raw)):
            raise CeremonyError("OUTPUT_METADATA_INVALID")
        os.close(descriptor)
        descriptor = -1
        os.fsync(parent_fd)
        return _sha(raw)
    except BaseException:
        if descriptor >= 0:
            os.close(descriptor)
        if created:
            try:
                os.unlink(path.name, dir_fd=parent_fd)
                os.fsync(parent_fd)
            except OSError:
                pass
        raise
    finally:
        os.close(parent_fd)


def _sha256sums(files: Mapping[str, bytes]) -> bytes:
    return "".join(
        f"{_sha(files[name])}  {name}\n" for name in sorted(files)
    ).encode("ascii")


def _deterministic_tar(files: Mapping[str, bytes]) -> bytes:
    if (not files or any(
            re.fullmatch(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*", name)
            is None or name.startswith("/") or ".." in name.split("/")
            or not 1 <= len(raw) <= MAX_FILE_BYTES
            for name, raw in files.items())):
        raise CeremonyError("INVALID_ARCHIVE_PAYLOAD")
    output = io.BytesIO()
    with tarfile.open(
        fileobj=output, mode="w", format=tarfile.PAX_FORMAT,
    ) as archive:
        for name in sorted(files):
            raw = files[name]
            info = tarfile.TarInfo(name)
            info.size = len(raw)
            info.mode = 0o600
            info.uid = 0
            info.gid = 0
            info.mtime = 0
            info.uname = "root"
            info.gname = "root"
            archive.addfile(info, io.BytesIO(raw))
    value = output.getvalue()
    if not 1 <= len(value) <= MAX_ARCHIVE_BYTES:
        raise CeremonyError("ARCHIVE_SIZE_INVALID")
    return value


def _artifact_raw(path: Path) -> bytes:
    try:
        raw, _digest = activation._artifact_bytes_and_sha256(path)
    except activation.ActivationError as exc:
        raise CeremonyError(str(exc)) from exc
    return raw


def _require_online_root() -> int:
    if os.geteuid() != 0:
        raise CeremonyError("ONLINE_COMMAND_REQUIRES_ROOT")
    try:
        descriptor = os.open(
            COORDINATION_ROOT,
            os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
        )
        info = os.fstat(descriptor)
        entries = set(os.listdir(descriptor))
    except OSError as exc:
        raise CeremonyError("COORDINATION_ROOT_UNSAFE") from exc
    if (info.st_uid != 0 or info.st_gid != 0
            or stat.S_IMODE(info.st_mode) != 0o700
            or not entries.issubset(SERVER_FILES)):
        os.close(descriptor)
        raise CeremonyError("COORDINATION_ROOT_UNSAFE")
    return descriptor


def _read_server(name: str) -> bytes:
    descriptor = _require_online_root()
    try:
        return _read_from_parent(descriptor, name, private=True)
    finally:
        os.close(descriptor)


def _write_server(name: str, raw: bytes) -> str:
    descriptor = _require_online_root()
    try:
        return _atomic_write_parent(descriptor, name, raw)
    finally:
        os.close(descriptor)


def _server_json(name: str) -> dict[str, Any]:
    return _decode_json(_read_server(name))


def _trusted_now() -> int:
    try:
        value, _evidence = activation.supervisor._trusted_now_epoch()
    except activation.supervisor.SupervisorError as exc:
        raise CeremonyError(str(exc)) from exc
    return value


def _subprocess_environment() -> dict[str, str]:
    return {"PATH": "/usr/bin:/bin", "LC_ALL": "C"}


def _fixed_subprocess(arguments: list[str], *, timeout: int) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            arguments, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, env=_subprocess_environment(),
            close_fds=True, timeout=timeout, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CeremonyError("FIXED_VERIFIER_UNAVAILABLE") from exc
    if (completed.returncode != 0 or completed.stderr
            or not 1 <= len(completed.stdout) <= MAX_SUBPROCESS_BYTES
            or completed.stdout.count(b"\n") > 1):
        raise CeremonyError("FIXED_VERIFIER_REJECTED")
    return _decode_json(completed.stdout.rstrip(b"\n"))


def _release_file(relative: str) -> Path:
    return RELEASE_ROOT / relative


def _verify_release_and_pins() -> dict[str, str]:
    if IMPLEMENTATION_COMMIT == "IMPLEMENTATION_COMMIT":
        raise CeremonyError("IMPLEMENTATION_COMMIT_NOT_PINNED")
    try:
        release = os.lstat(RELEASE_ROOT)
    except OSError as exc:
        raise CeremonyError("DEPLOYED_RELEASE_MISSING") from exc
    if (not stat.S_ISDIR(release.st_mode) or stat.S_ISLNK(release.st_mode)
            or release.st_uid != 0 or release.st_gid != 0
            or stat.S_IMODE(release.st_mode) != 0o555
            or RELEASE_ROOT.name != IMPLEMENTATION_COMMIT):
        raise CeremonyError("DEPLOYED_RELEASE_UNSAFE")
    artifacts: dict[str, str] = {}
    for key, current_path in activation.ARTIFACT_PATHS.items():
        try:
            relative = current_path.relative_to(activation.PROJECT_ROOT)
            _raw, deployed_sha = activation._artifact_bytes_and_sha256(
                RELEASE_ROOT / relative
            )
            _current_raw, current_sha = \
                activation._artifact_bytes_and_sha256(current_path)
        except (ValueError, activation.ActivationError) as exc:
            raise CeremonyError("DEPLOYED_RELEASE_ARTIFACT_UNSAFE") from exc
        if deployed_sha != current_sha:
            raise CeremonyError("DEPLOYED_RELEASE_ARTIFACT_DRIFT")
        artifacts[key] = deployed_sha
    for unit_name in UNIT_FILES:
        installed = Path("/etc/systemd/system") / unit_name
        current = ROOT / "deploy/systemd" / unit_name
        try:
            installed_raw, _installed_sha = \
                activation._artifact_bytes_and_sha256(installed)
            current_raw, _current_sha = \
                activation._artifact_bytes_and_sha256(current)
        except activation.ActivationError as exc:
            raise CeremonyError("DEPLOYED_UNIT_UNSAFE") from exc
        if (installed_raw != current_raw
                or f"/{IMPLEMENTATION_COMMIT}/".encode() not in installed_raw):
            raise CeremonyError("DEPLOYED_UNIT_PIN_MISMATCH")
    return artifacts


def _production_tuple() -> dict[str, Any]:
    watchdog = _release_file(
        "deploy/postgres/b64_snapshot_reader_watchdog.py"
    )
    report = _fixed_subprocess([
        str(PYTHON), "-E", str(watchdog),
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
            or type(container.get("startedAt")) is not str
            or re.fullmatch(
                r"[0-9a-f]{64}", str(container.get("containerId", ""))
            ) is None):
        raise CeremonyError("PRODUCTION_DORMANT_TUPLE_INVALID")
    return {
        "containerName": activation.PRODUCTION_CONTAINER,
        "containerId": container["containerId"],
        "imageId": container["imageId"],
        "containerPid": container["containerPid"],
        "startedAt": container["startedAt"],
        "restartCount": container["restartCount"],
        "systemIdentifier": report["systemIdentifier"],
    }


def _load_keyring(
    raw: bytes, *, now_epoch: int,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    value = _decode_json(raw)
    digest = value.get("keyringSha256")
    if type(digest) is not str:
        raise CeremonyError("INVALID_KEYRING_DIGEST")
    try:
        keyring, registry, _semantic_sha = activation._load_keyring(
            raw, expected_sha256=digest, now_epoch=now_epoch,
            expected_environment="PRODUCTION",
        )
    except activation.ActivationError as exc:
        raise CeremonyError(str(exc)) from exc
    return keyring, registry


def _load_plan(raw: bytes) -> tuple[dict[str, Any], str]:
    try:
        plan = activation.validate_plan(
            _decode_json(raw), expected_environment="PRODUCTION",
        )
    except activation.ActivationError as exc:
        raise CeremonyError(str(exc)) from exc
    return plan, _sha(_canonical(plan))


def _unsigned_decision(
    value: Mapping[str, Any], *, keyring: Mapping[str, Any],
    plan: Mapping[str, Any],
) -> dict[str, Any]:
    unsigned_keys = (
        "schemaVersion", "route", "decision", "environment",
        "activationPlanSha256", "keyringSha256", "issuedAtEpoch",
        "expiresAtEpoch", "nonce", "limits", "authority",
    )
    if not isinstance(value, Mapping) or set(value) != {
            *unsigned_keys, "decisionSha256"}:
        raise CeremonyError("INVALID_UNSIGNED_DECISION_SHAPE")
    unsigned = {key: value[key] for key in unsigned_keys}
    if (unsigned["schemaVersion"] != activation.DECISION_SCHEMA
            or unsigned["route"] != activation.ROUTE
            or unsigned["decision"]
            != "AUTHORIZE_ONE_BOUNDED_READ_ONLY_REFRESH"
            or unsigned["environment"] != "PRODUCTION"
            or unsigned["activationPlanSha256"] != _sha(_canonical(plan))
            or unsigned["keyringSha256"] != keyring["keyringSha256"]
            or unsigned["nonce"] != plan["runNonce"]
            or not activation._exact(unsigned["limits"], activation.LIMITS)
            or not activation._exact(
                unsigned["authority"], activation.PRODUCTION_AUTHORITY,
            )):
        raise CeremonyError("ACTIVATION_DECISION_BINDING_MISMATCH")
    issued = unsigned["issuedAtEpoch"]
    expires = unsigned["expiresAtEpoch"]
    if (type(issued) is not int or type(expires) is not int or issued <= 0
            or not issued < expires
            <= issued + activation.MAX_DECISION_LIFETIME_SECONDS
            or plan["createdAtEpoch"] > issued
            or issued - plan["createdAtEpoch"]
            > activation.MAX_PLAN_AGE_SECONDS
            or issued < keyring["issuedAtEpoch"]
            or expires > keyring["expiresAtEpoch"]):
        raise CeremonyError("ACTIVATION_DECISION_TIME_INVALID")
    decision_sha = _sha(_canonical(unsigned))
    if value.get("decisionSha256") != decision_sha:
        raise CeremonyError("ACTIVATION_DECISION_DIGEST_MISMATCH")
    return json.loads(_canonical(unsigned))


def _assert_tuple_matches_plan(
    observed: Mapping[str, Any], plan: Mapping[str, Any],
) -> None:
    target = plan["target"]
    if (observed.get("containerName") != target["containerName"]
            or observed.get("containerId") != target["containerId"]
            or observed.get("imageId") != target["imageId"]
            or observed.get("systemIdentifier") != target["systemIdentifier"]):
        raise CeremonyError("PRODUCTION_TARGET_CHANGED_DURING_CEREMONY")


def _public_profile(value: Mapping[str, Any]) -> tuple[dict[str, Any], bytes]:
    if (not isinstance(value, Mapping) or set(value) != {
            "schemaVersion", "route", "keyId", "identityId",
            "trustDomain", "role", "algorithm", "publicKeyEncoding",
            "publicKeyB64",
    } or value.get("schemaVersion") != PUBLIC_KEY_SCHEMA
            or value.get("route") != activation.ROUTE
            or value.get("role") not in activation.SIGNER_ROLES
            or value.get("algorithm") != "Ed25519"
            or value.get("publicKeyEncoding")
            != "base64url-unpadded-raw32"):
        raise CeremonyError("INVALID_PUBLIC_KEY_ENTRY")
    profile = dict(value)
    _token(profile["identityId"], "INVALID_IDENTITY_ID")
    _token(profile["trustDomain"], "INVALID_TRUST_DOMAIN")
    try:
        public_raw = activation.supervisor._decode_public_key(
            profile["publicKeyB64"]
        )
    except activation.supervisor.SupervisorError as exc:
        raise CeremonyError(str(exc)) from exc
    if profile["keyId"] != activation.supervisor._key_id(public_raw):
        raise CeremonyError("PUBLIC_KEY_ID_MISMATCH")
    return profile, public_raw


def _profile_from_trust_entry(entry: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schemaVersion": PUBLIC_KEY_SCHEMA,
        "route": activation.ROUTE,
        "keyId": entry["sourceEvidenceKeyId"],
        "identityId": entry["identityId"],
        "trustDomain": entry["trustDomain"],
        "role": entry["role"],
        "algorithm": "Ed25519",
        "publicKeyEncoding": "base64url-unpadded-raw32",
        "publicKeyB64": entry["publicKeyB64"],
    }


def _passphrase(descriptor: int | None) -> bytes:
    if descriptor is None:
        value = getpass.getpass("Private-key passphrase: ").encode("utf-8")
    else:
        value = os.read(descriptor, 4097).rstrip(b"\r\n")
        if len(value) > 4096:
            raise CeremonyError("PASSPHRASE_TOO_LONG")
    if len(value) < 16:
        raise CeremonyError("PASSPHRASE_TOO_SHORT")
    return value


def command_build_keyring(_args: argparse.Namespace) -> dict[str, Any]:
    _verify_release_and_pins()
    now = _trusted_now()
    trust = activation._load_activation_trust_registry()
    keys = sorted(({
        "keyId": entry["keyId"],
        "identityId": entry["identityId"],
        "trustDomain": entry["trustDomain"],
        "role": entry["role"],
        "status": entry["status"],
        "publicKeyB64": entry["publicKeyB64"],
    } for entry in trust["keys"]), key=lambda item: item["keyId"])
    unsigned = {
        "schemaVersion": activation.ACTIVATION_KEYRING_SCHEMA,
        "route": activation.ROUTE,
        "trustEnvironment": activation.ACTIVATION_TRUST_ENVIRONMENT,
        "registryVersion": trust["registryVersion"],
        "issuedAtEpoch": now,
        "expiresAtEpoch": now
        + activation.supervisor.MAX_KEYRING_LIFETIME_SECONDS,
        "revokedKeys": trust["revokedKeys"],
        "keys": keys,
    }
    keyring = {
        **unsigned,
        "keyringSha256": _sha(_canonical(unsigned)),
    }
    raw = _canonical(keyring) + b"\n"
    _load_keyring(raw, now_epoch=now)
    return {
        "keyringSha256": keyring["keyringSha256"],
        "registryVersion": keyring["registryVersion"],
        "trustRegistrySha256": trust["registrySha256"],
        "outputSha256": _write_server("keyring.json", raw),
        "productionAuthorityComplete": False,
        "actionAllowed": False,
    }


def command_build_offline_kit(args: argparse.Namespace) -> dict[str, Any]:
    _verify_release_and_pins()
    trust = activation._load_activation_trust_registry()
    files = {
        name: _artifact_raw(ROOT / name) for name in OFFLINE_KIT_FILES
    }
    for entry in trust["keys"]:
        name = (
            "owner-public.json" if entry["role"] == "ACCOUNTABLE_OWNER"
            else "reviewer-public.json"
        )
        files[name] = _canonical(_profile_from_trust_entry(entry)) + b"\n"
    files["README.txt"] = (
        "OBSIDIAN 064A PRODUCTION ACTIVATION V3 - OFFLINE SIGNING KIT\n"
        "This archive contains no private key, passphrase, credential, "
        "runtime request, or completed authority.\n"
        "Verify the archive SHA-256 received out-of-band and SHA256SUMS "
        "after extraction into a private 0700 directory.\n"
        "For each fresh request, independently inspect decision-unsigned.json "
        "and confirm its decisionSha256 before signing.\n"
        "Run scripts/b64_064a_activation_ceremony.py sign only on the "
        "offline signer device with that signer's encrypted Ed25519 key.\n"
        "Never copy the encrypted private key or passphrase to the server.\n"
    ).encode("utf-8")
    manifest_unsigned = {
        "schemaVersion": OFFLINE_KIT_SCHEMA,
        "route": activation.ROUTE,
        "implementationCommit": IMPLEMENTATION_COMMIT,
        "trustRegistrySha256": trust["registrySha256"],
        "sourceEvidenceKeyringSha256": trust["source"][
            "evidenceKeyringSha256"
        ],
        "filesSha256": {
            name: _sha(raw) for name, raw in sorted(files.items())
        },
        "containsPrivateKey": False,
        "containsPassphrase": False,
        "containsCredential": False,
        "containsRuntimeRequest": False,
        "productionAuthorityComplete": False,
    }
    manifest = {
        **manifest_unsigned,
        "manifestSha256": _sha(_canonical(manifest_unsigned)),
    }
    files["KIT-MANIFEST.json"] = _canonical(manifest) + b"\n"
    files["SHA256SUMS"] = _sha256sums(files)
    archive = _deterministic_tar(files)
    return {
        "status": "SECRET_FREE_OFFLINE_KIT_CREATED",
        "implementationCommit": IMPLEMENTATION_COMMIT,
        "trustRegistrySha256": trust["registrySha256"],
        "archiveSha256": _atomic_write_path(args.out, archive),
        "archiveBytes": len(archive),
        "fileCount": len(files),
        "productionAuthorityComplete": False,
        "runtimeRequestsCreated": False,
        "launcherStarted": False,
        "actionAllowed": False,
    }


def command_create_plan(_args: argparse.Namespace) -> dict[str, Any]:
    artifacts = _verify_release_and_pins()
    now = _trusted_now()
    observed = _production_tuple()
    plan = activation.build_plan(
        environment="PRODUCTION",
        run_nonce=_b64(secrets.token_bytes(24)),
        created_at_epoch=now,
        container_id=observed["containerId"],
        image_id=observed["imageId"],
        system_identifier=observed["systemIdentifier"],
        artifacts_sha256=artifacts,
    )
    activation.verify_artifact_closure(plan)
    raw = _canonical(plan) + b"\n"
    return {
        "planSha256": _sha(_canonical(plan)),
        "runNonce": plan["runNonce"],
        "createdAtEpoch": plan["createdAtEpoch"],
        "containerId": observed["containerId"],
        "implementationCommit": IMPLEMENTATION_COMMIT,
        "outputSha256": _write_server("activation-plan.json", raw),
        "productionAuthorityComplete": False,
        "actionAllowed": False,
    }


def command_create_decision(_args: argparse.Namespace) -> dict[str, Any]:
    _verify_release_and_pins()
    now = _trusted_now()
    keyring_raw = _read_server("keyring.json")
    plan_raw = _read_server("activation-plan.json")
    keyring, _registry = _load_keyring(keyring_raw, now_epoch=now)
    plan, plan_sha = _load_plan(plan_raw)
    _assert_tuple_matches_plan(_production_tuple(), plan)
    if (plan["createdAtEpoch"] > now
            or now - plan["createdAtEpoch"]
            > activation.MAX_PLAN_AGE_SECONDS):
        raise CeremonyError("ACTIVATION_PLAN_NOT_FRESH")
    unsigned = {
        "schemaVersion": activation.DECISION_SCHEMA,
        "route": activation.ROUTE,
        "decision": "AUTHORIZE_ONE_BOUNDED_READ_ONLY_REFRESH",
        "environment": "PRODUCTION",
        "activationPlanSha256": plan_sha,
        "keyringSha256": keyring["keyringSha256"],
        "issuedAtEpoch": now,
        "expiresAtEpoch": now + DECISION_LIFETIME_SECONDS,
        "nonce": plan["runNonce"],
        "limits": dict(activation.LIMITS),
        "authority": dict(activation.PRODUCTION_AUTHORITY),
    }
    decision = {
        **unsigned,
        "decisionSha256": _sha(_canonical(unsigned)),
    }
    _unsigned_decision(decision, keyring=keyring, plan=plan)
    return {
        "decisionSha256": decision["decisionSha256"],
        "runNonce": plan["runNonce"],
        "expiresAtEpoch": decision["expiresAtEpoch"],
        "signatureDomain": "OBSIDIAN_B64_064A_PRODUCTION_ACTIVATION_V3",
        "outputSha256": _write_server(
            "decision-unsigned.json", _canonical(decision) + b"\n",
        ),
        "productionAuthorityComplete": False,
        "actionAllowed": False,
    }


def command_export_signing_request(args: argparse.Namespace) -> dict[str, Any]:
    _verify_release_and_pins()
    now = _trusted_now()
    keyring_raw = _read_server("keyring.json")
    plan_raw = _read_server("activation-plan.json")
    decision_raw = _read_server("decision-unsigned.json")
    keyring, _registry = _load_keyring(keyring_raw, now_epoch=now)
    plan, plan_sha = _load_plan(plan_raw)
    decision = _decode_json(decision_raw)
    _unsigned_decision(decision, keyring=keyring, plan=plan)
    _assert_tuple_matches_plan(_production_tuple(), plan)
    if decision["expiresAtEpoch"] - now < MINIMUM_ASSEMBLY_WINDOW_SECONDS:
        raise CeremonyError("INSUFFICIENT_DECISION_WINDOW_REMAINING")
    files = {
        "activation-plan.json": plan_raw,
        "decision-unsigned.json": decision_raw,
        "keyring.json": keyring_raw,
    }
    manifest_unsigned = {
        "schemaVersion": SIGNING_REQUEST_SCHEMA,
        "route": activation.ROUTE,
        "implementationCommit": IMPLEMENTATION_COMMIT,
        "runNonce": plan["runNonce"],
        "planSha256": plan_sha,
        "decisionSha256": decision["decisionSha256"],
        "keyringSha256": keyring["keyringSha256"],
        "issuedAtEpoch": decision["issuedAtEpoch"],
        "expiresAtEpoch": decision["expiresAtEpoch"],
        "filesSha256": {
            name: _sha(raw) for name, raw in sorted(files.items())
        },
        "containsPrivateKey": False,
        "containsPassphrase": False,
        "containsCredential": False,
        "containsRuntimeRequest": False,
        "productionAuthorityComplete": False,
    }
    manifest = {
        **manifest_unsigned,
        "manifestSha256": _sha(_canonical(manifest_unsigned)),
    }
    files["REQUEST-MANIFEST.json"] = _canonical(manifest) + b"\n"
    files["SHA256SUMS"] = _sha256sums(files)
    archive = _deterministic_tar(files)
    return {
        "status": "FRESH_SECRET_FREE_SIGNING_REQUEST_CREATED",
        "runNonce": plan["runNonce"],
        "decisionSha256": decision["decisionSha256"],
        "expiresAtEpoch": decision["expiresAtEpoch"],
        "archiveSha256": _atomic_write_path(args.out, archive),
        "archiveBytes": len(archive),
        "fileCount": len(files),
        "productionAuthorityComplete": False,
        "runtimeRequestsCreated": False,
        "launcherStarted": False,
        "actionAllowed": False,
    }


def command_sign(args: argparse.Namespace) -> dict[str, Any]:
    keyring_raw = _read_path(args.keyring)
    plan_raw = _read_path(args.activation_plan)
    decision = _decode_json(_read_path(args.decision))
    issued = decision.get("issuedAtEpoch", 0)
    keyring, registry = _load_keyring(keyring_raw, now_epoch=issued)
    plan, plan_sha = _load_plan(plan_raw)
    unsigned = _unsigned_decision(decision, keyring=keyring, plan=plan)
    if args.confirm_decision_sha256 != decision["decisionSha256"]:
        raise CeremonyError("DECISION_DIGEST_CONFIRMATION_MISMATCH")
    role = _token(args.role, "INVALID_ROLE")
    profiles = [
        (key_id, profile) for key_id, profile in registry.items()
        if profile["role"] == role
    ]
    if role not in activation.SIGNER_ROLES or len(profiles) != 1:
        raise CeremonyError("INVALID_ROLE_PROFILE")
    key_id, keyring_profile = profiles[0]
    public_profile, public_raw = _public_profile(
        _decode_json(_read_path(args.public_profile))
    )
    if (public_profile["role"] != role
            or public_profile["identityId"]
            != keyring_profile["identityId"]
            or public_profile["trustDomain"]
            != keyring_profile["trustDomain"]
            or public_profile["publicKeyB64"]
            != keyring_profile["publicKeyB64"]
            or activation.activation_key_id(public_raw) != key_id):
        raise CeremonyError("PUBLIC_PROFILE_KEYRING_MISMATCH")
    try:
        private_key = serialization.load_pem_private_key(
            _read_path(args.private_key, private=True),
            password=_passphrase(args.passphrase_fd),
        )
    except (TypeError, ValueError) as exc:
        raise CeremonyError("PRIVATE_KEY_DECRYPTION_FAILED") from exc
    if (not isinstance(private_key, Ed25519PrivateKey)
            or private_key.public_key().public_bytes_raw() != public_raw):
        raise CeremonyError("PRIVATE_KEY_PROFILE_MISMATCH")
    signature = private_key.sign(
        activation.SIGNATURE_DOMAIN + _canonical(unsigned)
    )
    detached = {
        "schemaVersion": DETACHED_SIGNATURE_SCHEMA,
        "route": activation.ROUTE,
        "activationPlanSha256": plan_sha,
        "decisionSha256": decision["decisionSha256"],
        "keyringSha256": keyring["keyringSha256"],
        "runNonce": plan["runNonce"],
        "role": role,
        "keyId": key_id,
        "identityId": keyring_profile["identityId"],
        "signatureB64": _b64(signature),
    }
    return {
        "decisionSha256": decision["decisionSha256"],
        "runNonce": plan["runNonce"],
        "role": role,
        "signatureFileSha256": _write_offline_path(
            args.out, _canonical(detached) + b"\n",
        ),
        "productionAuthoritySignature": True,
        "productionAuthorityComplete": False,
        "actionAllowed": False,
    }


def _detached(
    value: Mapping[str, Any], *, decision: Mapping[str, Any],
    keyring: Mapping[str, Any], plan: Mapping[str, Any], role: str,
) -> dict[str, Any]:
    if (not isinstance(value, Mapping) or set(value) != {
            "schemaVersion", "route", "activationPlanSha256",
            "decisionSha256", "keyringSha256", "runNonce", "role",
            "keyId", "identityId", "signatureB64",
    } or value.get("schemaVersion") != DETACHED_SIGNATURE_SCHEMA
            or value.get("route") != activation.ROUTE
            or value.get("activationPlanSha256") != _sha(_canonical(plan))
            or value.get("decisionSha256") != decision["decisionSha256"]
            or value.get("keyringSha256") != keyring["keyringSha256"]
            or value.get("runNonce") != plan["runNonce"]
            or value.get("role") != role):
        raise CeremonyError("DETACHED_SIGNATURE_BINDING_MISMATCH")
    return {key: value[key] for key in (
        "role", "keyId", "identityId", "signatureB64",
    )}


def _verify_detached_signature(
    detached: Mapping[str, Any], *, unsigned: Mapping[str, Any],
    registry: Mapping[str, Mapping[str, Any]],
) -> None:
    profile = registry.get(detached["keyId"])
    if (not isinstance(profile, Mapping)
            or profile.get("role") != detached["role"]
            or profile.get("identityId") != detached["identityId"]):
        raise CeremonyError("DETACHED_SIGNATURE_SIGNER_MISMATCH")
    try:
        public_key = Ed25519PublicKey.from_public_bytes(
            activation.supervisor._decode_public_key(profile["publicKeyB64"])
        )
        signature = activation.supervisor._decode_signature(
            detached["signatureB64"]
        )
        public_key.verify(
            signature, activation.SIGNATURE_DOMAIN + _canonical(unsigned)
        )
    except (InvalidSignature, ValueError,
            activation.supervisor.SupervisorError) as exc:
        raise CeremonyError("INVALID_DETACHED_ACTIVATION_SIGNATURE") from exc


def command_import_signature(args: argparse.Namespace) -> dict[str, Any]:
    _verify_release_and_pins()
    now = _trusted_now()
    keyring, registry = _load_keyring(
        _read_server("keyring.json"), now_epoch=now,
    )
    plan, _plan_sha = _load_plan(_read_server("activation-plan.json"))
    decision = _server_json("decision-unsigned.json")
    unsigned = _unsigned_decision(decision, keyring=keyring, plan=plan)
    if decision["expiresAtEpoch"] - now < MINIMUM_ASSEMBLY_WINDOW_SECONDS:
        raise CeremonyError("INSUFFICIENT_DECISION_WINDOW_REMAINING")
    _assert_tuple_matches_plan(_production_tuple(), plan)
    role = _token(args.role, "INVALID_ROLE")
    if role not in activation.SIGNER_ROLES:
        raise CeremonyError("INVALID_ROLE")
    value = _decode_json(_read_path(args.signature))
    detached = _detached(
        value, decision=decision, keyring=keyring, plan=plan, role=role,
    )
    _verify_detached_signature(
        detached, unsigned=unsigned, registry=registry,
    )
    name = (
        "owner-signature.json" if role == "ACCOUNTABLE_OWNER"
        else "reviewer-signature.json"
    )
    raw = _canonical(value) + b"\n"
    return {
        "status": "FRESH_DETACHED_SIGNATURE_IMPORTED",
        "role": role,
        "decisionSha256": decision["decisionSha256"],
        "runNonce": plan["runNonce"],
        "signatureFileSha256": _write_server(name, raw),
        "productionAuthoritySignature": True,
        "productionAuthorityComplete": False,
        "runtimeRequestsCreated": False,
        "launcherStarted": False,
        "actionAllowed": False,
    }


def _verify_with_immutable_entrypoint(
    *, keyring_sha256: str, decision_path: Path, now: int,
    plan: Mapping[str, Any], decision: Mapping[str, Any],
) -> dict[str, Any]:
    receipt = _fixed_subprocess([
        str(PYTHON), "-E",
        str(_release_file("deploy/postgres/b64_064a_activation_entrypoint.py")),
        "--verify-package",
        "--keyring", str(COORDINATION_ROOT / "keyring.json"),
        "--decision", str(decision_path),
        "--activation-plan",
        str(COORDINATION_ROOT / "activation-plan.json"),
        "--expected-keyring-sha256", keyring_sha256,
        "--environment", "PRODUCTION", "--now", str(now),
    ], timeout=60)
    expected = {
        "receiptStatus": "OK",
        "route": activation.ROUTE,
        "status": "ACTIVATION_PACKAGE_VERIFIED_EXECUTOR_ABSENT",
        "environment": "PRODUCTION",
        "runNonce": plan["runNonce"],
        "planSha256": _sha(_canonical(plan)),
        "decisionSha256": decision["decisionSha256"],
        "productionExecutionAdapterPresent": False,
        "authorizationConsumed": False,
        "automaticRetryAllowed": False,
        "actionAllowed": False,
    }
    if receipt != expected:
        raise CeremonyError("IMMUTABLE_VERIFIER_RECEIPT_MISMATCH")
    return receipt


def command_assemble_decision(_args: argparse.Namespace) -> dict[str, Any]:
    _verify_release_and_pins()
    now = _trusted_now()
    keyring_raw = _read_server("keyring.json")
    plan_raw = _read_server("activation-plan.json")
    decision = _server_json("decision-unsigned.json")
    keyring, registry = _load_keyring(keyring_raw, now_epoch=now)
    plan, _plan_sha = _load_plan(plan_raw)
    unsigned = _unsigned_decision(decision, keyring=keyring, plan=plan)
    if decision["expiresAtEpoch"] - now < MINIMUM_ASSEMBLY_WINDOW_SECONDS:
        raise CeremonyError("INSUFFICIENT_DECISION_WINDOW_REMAINING")
    _assert_tuple_matches_plan(_production_tuple(), plan)
    signatures = [
        _detached(
            _server_json("reviewer-signature.json"), decision=decision,
            keyring=keyring, plan=plan, role="INDEPENDENT_REVIEWER",
        ),
        _detached(
            _server_json("owner-signature.json"), decision=decision,
            keyring=keyring, plan=plan, role="ACCOUNTABLE_OWNER",
        ),
    ]
    for signature in signatures:
        _verify_detached_signature(
            signature, unsigned=unsigned, registry=registry,
        )
    completed = {**decision, "signatures": signatures}
    raw = _canonical(completed) + b"\n"
    root_fd = _require_online_root()
    temporary = f".decision.verify-{secrets.token_hex(12)}.json"
    temporary_path = COORDINATION_ROOT / temporary
    published = False
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
            0o600, dir_fd=root_fd,
        )
        try:
            view = memoryview(raw)
            while view:
                written = os.write(descriptor, view)
                if written <= 0:
                    raise CeremonyError("OUTPUT_WRITE_FAILED")
                view = view[written:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        _verify_with_immutable_entrypoint(
            keyring_sha256=keyring["keyringSha256"],
            decision_path=temporary_path, now=now,
            plan=plan, decision=decision,
        )
        try:
            os.stat("decision.json", dir_fd=root_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise CeremonyError("OUTPUT_ALREADY_EXISTS_OR_UNSAFE")
        os.link(
            temporary, "decision.json",
            src_dir_fd=root_fd, dst_dir_fd=root_fd,
            follow_symlinks=False,
        )
        published = True
        os.unlink(temporary, dir_fd=root_fd)
        os.fsync(root_fd)
    except BaseException:
        if published:
            try:
                os.unlink("decision.json", dir_fd=root_fd)
            except OSError:
                pass
        try:
            os.unlink(temporary, dir_fd=root_fd)
        except OSError:
            pass
        raise
    finally:
        os.close(root_fd)
    return {
        "status": "SIGNED_V3_DECISION_VERIFIED_NOT_DEPLOYED",
        "decisionSha256": decision["decisionSha256"],
        "runNonce": plan["runNonce"],
        "expiresAtEpoch": decision["expiresAtEpoch"],
        "minimumWindowRemainingSeconds": MINIMUM_ASSEMBLY_WINDOW_SECONDS,
        "outputSha256": _sha(raw),
        "productionAuthorityComplete": True,
        "runtimeRequestsCreated": False,
        "runtimePathsWritten": False,
        "launcherStarted": False,
        "actionAllowed": False,
    }


def command_verify_decision(_args: argparse.Namespace) -> dict[str, Any]:
    _verify_release_and_pins()
    now = _trusted_now()
    keyring_raw = _read_server("keyring.json")
    plan_raw = _read_server("activation-plan.json")
    decision_raw = _read_server("decision.json")
    keyring, _registry = _load_keyring(keyring_raw, now_epoch=now)
    plan, _plan_sha = _load_plan(plan_raw)
    decision = _decode_json(decision_raw)
    unsigned = {key: decision[key] for key in decision if key != "signatures"}
    _unsigned_decision(unsigned, keyring=keyring, plan=plan)
    if decision["expiresAtEpoch"] - now < MINIMUM_ASSEMBLY_WINDOW_SECONDS:
        raise CeremonyError("INSUFFICIENT_DECISION_WINDOW_REMAINING")
    _assert_tuple_matches_plan(_production_tuple(), plan)
    _verify_with_immutable_entrypoint(
        keyring_sha256=keyring["keyringSha256"],
        decision_path=COORDINATION_ROOT / "decision.json", now=now,
        plan=plan, decision=decision,
    )
    return {
        "status": "SIGNED_V3_DECISION_VERIFIED_NOT_DEPLOYED",
        "decisionSha256": decision["decisionSha256"],
        "runNonce": plan["runNonce"],
        "expiresAtEpoch": decision["expiresAtEpoch"],
        "productionAuthorityComplete": True,
        "runtimeRequestsCreated": False,
        "runtimePathsWritten": False,
        "launcherStarted": False,
        "actionAllowed": False,
    }


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    commands = value.add_subparsers(dest="command", required=True)
    commands.add_parser("build-keyring")
    command = commands.add_parser("build-offline-kit")
    command.add_argument("--out", required=True)
    commands.add_parser("create-plan")
    commands.add_parser("create-unsigned-decision")
    command = commands.add_parser("export-signing-request")
    command.add_argument("--out", required=True)
    command = commands.add_parser("sign")
    command.add_argument("--role", required=True)
    command.add_argument("--public-profile", required=True)
    command.add_argument("--keyring", required=True)
    command.add_argument("--activation-plan", required=True)
    command.add_argument("--decision", required=True)
    command.add_argument("--confirm-decision-sha256", required=True)
    command.add_argument("--private-key", required=True)
    command.add_argument("--passphrase-fd", type=int)
    command.add_argument("--out", required=True)
    command = commands.add_parser("import-signature")
    command.add_argument("--role", required=True)
    command.add_argument("--signature", required=True)
    commands.add_parser("assemble-decision")
    commands.add_parser("verify-decision")
    return value


def main() -> int:
    os.umask(0o077)
    try:
        args = parser().parse_args()
        if args.command == "build-keyring":
            result = command_build_keyring(args)
        elif args.command == "build-offline-kit":
            result = command_build_offline_kit(args)
        elif args.command == "create-plan":
            result = command_create_plan(args)
        elif args.command == "create-unsigned-decision":
            result = command_create_decision(args)
        elif args.command == "export-signing-request":
            result = command_export_signing_request(args)
        elif args.command == "sign":
            result = command_sign(args)
        elif args.command == "import-signature":
            result = command_import_signature(args)
        elif args.command == "assemble-decision":
            result = command_assemble_decision(args)
        else:
            result = command_verify_decision(args)
        print(json.dumps({
            "receiptStatus": "OK", "route": activation.ROUTE, **result,
        }, sort_keys=True, separators=(",", ":")))
        return 0
    except Exception as exc:
        print(json.dumps({
            "receiptStatus": "ERROR", "route": activation.ROUTE,
            "errorCode": _reason(exc), "actionAllowed": False,
        }, sort_keys=True, separators=(",", ":")))
        return 3


if __name__ == "__main__":
    sys.exit(main())
