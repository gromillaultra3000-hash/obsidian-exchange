"""Fail-closed two-direction service-key provisioning contract."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import stat
from pathlib import Path
from typing import Any, Callable, Mapping

from lumi.app.integration.shadow_public_keyring import initial_keyring

SCHEMA = "shadow-service-key-plan.v1"
REPORT_SCHEMA = "shadow-service-key-provisioning.v1"
VALIDITY_SECONDS = 365 * 24 * 60 * 60
_PLAN_KEYS = {
    "schemaVersion", "planId", "generatedAt", "validUntil", "identities",
    "executionEffect", "actionAllowed",
}
_IDENTITY_KEYS = {
    "direction", "issuer", "audience", "scope", "keyId", "privatePath",
    "privateGroup", "publicKeyringPath", "publicGroup",
}
_EXPECTED = ({
    "direction": "KAIROS_TO_LUMI", "issuer": "kairos-shadow",
    "audience": "lumi-shadow", "scope": "shadow:advisory",
    "keyId": "kairos-shadow-v1",
    "privatePath": "/etc/kairos/shadow-private/request-v1.key",
    "privateGroup": "kairos-svc",
    "publicKeyringPath": "/etc/lumi/shadow-trust/kairos-request-keyring.json",
    "publicGroup": "lumi-svc",
}, {
    "direction": "LUMI_TO_KAIROS", "issuer": "lumi-shadow",
    "audience": "kairos-shadow", "scope": "shadow:advisory-response",
    "keyId": "lumi-shadow-v1",
    "privatePath": "/etc/lumi/shadow-private/response-v1.key",
    "privateGroup": "lumi-svc",
    "publicKeyringPath": "/etc/kairos/shadow-trust/lumi-response-keyring.json",
    "publicGroup": "kairos-svc",
})


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def _plan_id(value: dict[str, Any]) -> str:
    unsigned = {key: item for key, item in value.items() if key != "planId"}
    return "kp_" + hashlib.sha256(_canonical(unsigned)).hexdigest()


def build_plan(*, generated_at: int) -> dict[str, Any]:
    if not isinstance(generated_at, int) or isinstance(generated_at, bool) \
            or generated_at < 0:
        raise ValueError("shadow key plan time is invalid")
    value = {
        "schemaVersion": SCHEMA, "generatedAt": generated_at,
        "validUntil": generated_at + VALIDITY_SECONDS,
        "identities": [dict(item) for item in _EXPECTED],
        "executionEffect": "NONE", "actionAllowed": False,
    }
    value["planId"] = _plan_id(value)
    return validate_plan(value)


def validate_plan(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != _PLAN_KEYS \
            or value.get("schemaVersion") != SCHEMA \
            or not re.fullmatch(r"kp_[a-f0-9]{64}", str(value.get("planId"))) \
            or not isinstance(value.get("generatedAt"), int) \
            or isinstance(value.get("generatedAt"), bool) \
            or value.get("generatedAt", -1) < 0 \
            or value.get("validUntil") != value["generatedAt"] + VALIDITY_SECONDS \
            or value.get("executionEffect") != "NONE" \
            or value.get("actionAllowed") is not False:
        raise ValueError("shadow key plan fields differ")
    identities = value.get("identities")
    if not isinstance(identities, list) or len(identities) != 2:
        raise ValueError("shadow key plan identities differ")
    for actual, expected in zip(identities, _EXPECTED):
        if not isinstance(actual, dict) or set(actual) != _IDENTITY_KEYS \
                or actual != expected:
            raise ValueError("shadow key plan ownership differs")
    if value["planId"] != _plan_id(value):
        raise ValueError("shadow key plan hash differs")
    return value


def _encoded(raw: bytes) -> bytes:
    return base64.urlsafe_b64encode(raw).rstrip(b"=") + b"\n"


def _write_new(
    path: Path, payload: bytes, *, uid: int, gid: int, mode: int,
) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, mode)
    try:
        os.write(fd, payload)
        os.fsync(fd)
        os.fchown(fd, uid, gid)
        os.fchmod(fd, mode)
    finally:
        os.close(fd)


def _target(root: Path, logical: str) -> Path:
    path = Path(logical)
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("shadow key target is invalid")
    return root.joinpath(*path.parts[1:])


def _ensure_directory(path: Path, *, uid: int, gid: int) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        path.mkdir(mode=0o750)
        os.chown(path, uid, gid)
        os.chmod(path, 0o750)
        return True
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode) \
            or info.st_uid != uid or info.st_gid != gid \
            or stat.S_IMODE(info.st_mode) != 0o750:
        raise ValueError("shadow key directory is unsafe")
    return False


def provision_service_keys(
    plan: Any, *, root: Path, owner_uid: int, group_ids: Mapping[str, int],
    key_factory: Callable[[str], tuple[bytes, bytes]],
    fault_after_writes: int | None = None,
) -> dict[str, Any]:
    value = validate_plan(plan)
    base = Path(root)
    try:
        base_info = base.lstat()
    except OSError as exc:
        raise ValueError("shadow key provisioning root is unavailable") from exc
    if not stat.S_ISDIR(base_info.st_mode) or stat.S_ISLNK(base_info.st_mode):
        raise ValueError("shadow key provisioning root is unsafe")
    if set(group_ids) != {"kairos-svc", "lumi-svc"} \
            or any(not isinstance(item, int) or isinstance(item, bool) or item < 0
                   for item in group_ids.values()):
        raise ValueError("shadow key provisioning groups differ")
    targets = []
    for identity in value["identities"]:
        targets.extend((
            _target(base, identity["privatePath"]),
            _target(base, identity["publicKeyringPath"]),
        ))
    if any(path.exists() or path.is_symlink() for path in targets):
        raise ValueError("shadow key provisioning target already exists")
    created_files: list[Path] = []
    created_dirs: list[Path] = []
    writes = 0
    try:
        for identity in value["identities"]:
            private_path = _target(base, identity["privatePath"])
            public_path = _target(base, identity["publicKeyringPath"])
            for path, group in (
                (private_path.parent, identity["privateGroup"]),
                (public_path.parent, identity["publicGroup"]),
            ):
                path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
                if _ensure_directory(
                        path, uid=owner_uid, gid=group_ids[group]):
                    created_dirs.append(path)
            private_raw, public_raw = key_factory(identity["direction"])
            if not isinstance(private_raw, bytes) or len(private_raw) != 32 \
                    or not isinstance(public_raw, bytes) or len(public_raw) != 32:
                raise ValueError("shadow key factory returned invalid material")
            _write_new(
                private_path, _encoded(private_raw), uid=owner_uid,
                gid=group_ids[identity["privateGroup"]], mode=0o640)
            created_files.append(private_path)
            writes += 1
            if fault_after_writes == writes:
                raise RuntimeError("injected shadow key provisioning fault")
            keyring = initial_keyring(
                key_id=identity["keyId"], public_key=public_raw,
                activated_at=value["generatedAt"], valid_until=value["validUntil"],
                audience=identity["audience"])
            _write_new(
                public_path, _canonical(keyring) + b"\n", uid=owner_uid,
                gid=group_ids[identity["publicGroup"]], mode=0o640)
            created_files.append(public_path)
            writes += 1
            if fault_after_writes == writes:
                raise RuntimeError("injected shadow key provisioning fault")
        for directory in {path.parent for path in created_files}:
            fd = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
    except Exception:
        for path in reversed(created_files):
            try:
                path.unlink()
            except FileNotFoundError:
                pass
        for path in reversed(created_dirs):
            try:
                path.rmdir()
            except OSError:
                pass
        raise
    return {
        "schemaVersion": REPORT_SCHEMA, "planId": value["planId"],
        "status": "PROVISIONED", "keyIds": [
            item["keyId"] for item in value["identities"]],
        "privateKeyCount": 2, "publicKeyringCount": 2,
        "secretsExposed": False, "executionEffect": "KEY_FILES_CREATED",
        "actionAllowed": False,
    }
