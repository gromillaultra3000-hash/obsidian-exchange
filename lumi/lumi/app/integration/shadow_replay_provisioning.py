"""Fail-closed provisioning contract for the dormant shadow replay state."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from pathlib import Path
from typing import Any, Callable

from lumi.app.integration.shadow_replay_ledger import empty_snapshot

SCHEMA = "shadow-replay-provisioning-plan.v1"
REPORT_SCHEMA = "shadow-replay-provisioning.v1"
STATE_PATH = "/var/lib/lumi/e2-shadow/replay-ledger.json"
OWNER = "lumi-svc"
CAPACITY = 10000
_PLAN_KEYS = {
    "schemaVersion", "planId", "statePath", "lockPath", "owner", "group",
    "directoryMode", "fileMode", "capacity", "executionEffect", "actionAllowed",
}


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def _plan_id(value: dict[str, Any]) -> str:
    unsigned = {key: item for key, item in value.items() if key != "planId"}
    return "rp_" + hashlib.sha256(_canonical(unsigned)).hexdigest()


def build_plan() -> dict[str, Any]:
    value = {
        "schemaVersion": SCHEMA,
        "statePath": STATE_PATH,
        "lockPath": STATE_PATH + ".lock",
        "owner": OWNER,
        "group": OWNER,
        "directoryMode": "0700",
        "fileMode": "0600",
        "capacity": CAPACITY,
        "executionEffect": "NONE",
        "actionAllowed": False,
    }
    value["planId"] = _plan_id(value)
    return validate_plan(value)


def validate_plan(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != _PLAN_KEYS \
            or value.get("schemaVersion") != SCHEMA \
            or value.get("statePath") != STATE_PATH \
            or value.get("lockPath") != STATE_PATH + ".lock" \
            or value.get("owner") != OWNER or value.get("group") != OWNER \
            or value.get("directoryMode") != "0700" \
            or value.get("fileMode") != "0600" \
            or value.get("capacity") != CAPACITY \
            or value.get("executionEffect") != "NONE" \
            or value.get("actionAllowed") is not False \
            or not re.fullmatch(r"rp_[a-f0-9]{64}", str(value.get("planId"))):
        raise ValueError("shadow replay provisioning plan differs")
    if value["planId"] != _plan_id(value):
        raise ValueError("shadow replay provisioning plan hash differs")
    return value


def _target(root: Path, logical: str) -> Path:
    path = Path(logical)
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("shadow replay provisioning target is invalid")
    return root.joinpath(*path.parts[1:])


def _validate_directory(path: Path, *, uid: int, gid: int) -> None:
    try:
        info = path.lstat()
    except OSError as exc:
        raise ValueError("shadow replay provisioning ancestor is unavailable") from exc
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode) \
            or info.st_uid != uid or info.st_gid != gid \
            or stat.S_IMODE(info.st_mode) != 0o700:
        raise ValueError("shadow replay provisioning ancestor is unsafe")


def _write_new(path: Path, payload: bytes, *, uid: int, gid: int) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    try:
        written = 0
        while written < len(payload):
            count = os.write(fd, payload[written:])
            if count <= 0:
                raise ValueError("shadow replay provisioning write failed")
            written += count
        os.fchown(fd, uid, gid)
        os.fchmod(fd, 0o600)
        os.fsync(fd)
    finally:
        os.close(fd)


def provision_replay_state(
    plan: Any, *, root: Path, owner_uid: int, owner_gid: int,
    fault: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    value = validate_plan(plan)
    if not isinstance(owner_uid, int) or isinstance(owner_uid, bool) or owner_uid < 0 \
            or not isinstance(owner_gid, int) or isinstance(owner_gid, bool) \
            or owner_gid < 0:
        raise ValueError("shadow replay provisioning identity differs")
    base = Path(root)
    try:
        root_info = base.lstat()
    except OSError as exc:
        raise ValueError("shadow replay provisioning root is unavailable") from exc
    if not stat.S_ISDIR(root_info.st_mode) or stat.S_ISLNK(root_info.st_mode):
        raise ValueError("shadow replay provisioning root is unsafe")
    state = _target(base, value["statePath"])
    lock = _target(base, value["lockPath"])
    ancestor = state.parent.parent
    _validate_directory(ancestor, uid=owner_uid, gid=owner_gid)
    if state.exists() or state.is_symlink() or lock.exists() or lock.is_symlink():
        raise ValueError("shadow replay provisioning target already exists")
    created_directory = False
    created: list[Path] = []
    inject = fault or (lambda _stage: None)
    try:
        state.parent.mkdir(mode=0o700)
        created_directory = True
        os.chown(state.parent, owner_uid, owner_gid)
        os.chmod(state.parent, 0o700)
        inject("after_directory")
        payload = _canonical(empty_snapshot(capacity=value["capacity"])) + b"\n"
        _write_new(state, payload, uid=owner_uid, gid=owner_gid)
        created.append(state)
        inject("after_state")
        _write_new(lock, b"", uid=owner_uid, gid=owner_gid)
        created.append(lock)
        inject("after_lock")
        directory_fd = os.open(state.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except Exception:
        for path in reversed(created):
            try:
                path.unlink()
            except FileNotFoundError:
                pass
        if created_directory:
            try:
                state.parent.rmdir()
            except OSError:
                pass
        raise
    return {
        "schemaVersion": REPORT_SCHEMA,
        "planId": value["planId"],
        "status": "PROVISIONED",
        "stateCreated": True,
        "lockCreated": True,
        "entryCount": 0,
        "capacity": value["capacity"],
        "executionEffect": "REPLAY_STATE_CREATED",
        "actionAllowed": False,
    }
