"""Frozen Ed25519 public-key allowlist and rotation contract for shadow identity."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import stat
from pathlib import Path
from typing import Any

SCHEMA = "shadow-public-keyring.v1"
ALGORITHM = "Ed25519"
AUDIENCE = "lumi-shadow"
MAX_KEYS = 8
MAX_OVERLAP_SECONDS = 300
MAX_VALIDITY_SECONDS = 365 * 24 * 60 * 60
MAX_FILE_BYTES = 64 * 1024
_KEYRING_KEYS = {
    "schemaVersion", "keyringId", "algorithm", "audience", "generatedAt", "keys",
}
_KEY_KEYS = {"keyId", "publicKey", "status", "notBefore", "notAfter"}
_STATUSES = {"ACTIVE", "RETIRING", "REVOKED"}


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode_public(value: Any) -> bytes:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", value):
        raise ValueError("shadow public key is invalid")
    try:
        raw = base64.b64decode(value + "=", altchars=b"-_", validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError("shadow public key is invalid") from exc
    if len(raw) != 32:
        raise ValueError("shadow public key is invalid")
    return raw


def _seal(
    *, generated_at: int, keys: list[dict[str, Any]], audience: str = AUDIENCE,
) -> dict[str, Any]:
    unsigned = {
        "schemaVersion": SCHEMA, "algorithm": ALGORITHM, "audience": audience,
        "generatedAt": generated_at, "keys": sorted(keys, key=lambda item: item["keyId"]),
    }
    digest = hashlib.sha256(json.dumps(
        unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()
    return validate_keyring(
        {**unsigned, "keyringId": "kr_" + digest}, expected_audience=audience)


def validate_keyring(
    value: Any, *, expected_audience: str = AUDIENCE,
) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != _KEYRING_KEYS \
            or value.get("schemaVersion") != SCHEMA \
            or value.get("algorithm") != ALGORITHM \
            or expected_audience not in {"lumi-shadow", "kairos-shadow"} \
            or value.get("audience") != expected_audience \
            or not isinstance(value.get("generatedAt"), int) \
            or isinstance(value.get("generatedAt"), bool) or value["generatedAt"] < 0:
        raise ValueError("shadow keyring fields differ")
    keys = value.get("keys")
    if not isinstance(keys, list) or not 1 <= len(keys) <= MAX_KEYS:
        raise ValueError("shadow keyring count is invalid")
    previous = ""
    active_count = 0
    for item in keys:
        if not isinstance(item, dict) or set(item) != _KEY_KEYS \
                or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{2,31}", str(item.get("keyId"))) \
                or item["keyId"] <= previous or item.get("status") not in _STATUSES \
                or not isinstance(item.get("notBefore"), int) \
                or isinstance(item.get("notBefore"), bool) \
                or not isinstance(item.get("notAfter"), int) \
                or isinstance(item.get("notAfter"), bool) \
                or not 0 <= item["notBefore"] < item["notAfter"] \
                or item["notAfter"] - item["notBefore"] > MAX_VALIDITY_SECONDS:
            raise ValueError("shadow keyring entry is invalid")
        _decode_public(item.get("publicKey"))
        previous = item["keyId"]
        active_count += item["status"] == "ACTIVE"
    if active_count > 1:
        raise ValueError("shadow keyring has multiple active keys")
    unsigned = {key: item for key, item in value.items() if key != "keyringId"}
    expected = "kr_" + hashlib.sha256(json.dumps(
        unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()
    if value.get("keyringId") != expected:
        raise ValueError("shadow keyring hash differs")
    return value


def initial_keyring(
    *, key_id: str, public_key: bytes, activated_at: int, valid_until: int,
    audience: str = AUDIENCE,
) -> dict[str, Any]:
    return _seal(generated_at=activated_at, audience=audience, keys=[{
        "keyId": key_id, "publicKey": _b64(public_key), "status": "ACTIVE",
        "notBefore": activated_at, "notAfter": valid_until,
    }])


def rotate_keyring(
    value: Any, *, new_key_id: str, new_public_key: bytes,
    rotated_at: int, valid_until: int, overlap_seconds: int,
    expected_audience: str = AUDIENCE,
) -> dict[str, Any]:
    current = validate_keyring(value, expected_audience=expected_audience)
    if not isinstance(rotated_at, int) or isinstance(rotated_at, bool) \
            or rotated_at < current["generatedAt"] \
            or not isinstance(valid_until, int) or isinstance(valid_until, bool) \
            or not rotated_at < valid_until <= rotated_at + MAX_VALIDITY_SECONDS \
            or not isinstance(overlap_seconds, int) or isinstance(overlap_seconds, bool) \
            or not 0 <= overlap_seconds <= MAX_OVERLAP_SECONDS \
            or any(item["keyId"] == new_key_id for item in current["keys"]) \
            or len(current["keys"]) >= MAX_KEYS:
        raise ValueError("shadow key rotation is invalid")
    _decode_public(_b64(new_public_key))
    overlap_end = rotated_at + overlap_seconds
    keys = [{**item, "status": "RETIRING",
             "notAfter": min(item["notAfter"], overlap_end)}
            if item["status"] == "ACTIVE" else dict(item)
            for item in current["keys"]]
    if any(item["status"] == "RETIRING" and item["notAfter"] <= item["notBefore"]
           for item in keys):
        raise ValueError("shadow key overlap is invalid")
    keys = [*keys, {
        "keyId": new_key_id, "publicKey": _b64(new_public_key), "status": "ACTIVE",
        "notBefore": rotated_at, "notAfter": valid_until,
    }]
    return _seal(generated_at=rotated_at, keys=keys, audience=expected_audience)


def revoke_key(
    value: Any, *, key_id: str, revoked_at: int,
    expected_audience: str = AUDIENCE,
) -> dict[str, Any]:
    current = validate_keyring(value, expected_audience=expected_audience)
    if not isinstance(revoked_at, int) or isinstance(revoked_at, bool) \
            or revoked_at < current["generatedAt"] \
            or not any(item["keyId"] == key_id for item in current["keys"]):
        raise ValueError("shadow key revocation is invalid")
    keys = [{**item, "status": "REVOKED", "notAfter": max(
        item["notBefore"] + 1, min(item["notAfter"], revoked_at))}
            if item["keyId"] == key_id else dict(item) for item in current["keys"]]
    return _seal(generated_at=revoked_at, keys=keys, audience=expected_audience)


def resolve_public_key(
    value: Any, *, key_id: str, at_epoch: int,
    expected_audience: str = AUDIENCE,
) -> bytes:
    keyring = validate_keyring(value, expected_audience=expected_audience)
    if not isinstance(at_epoch, int) or isinstance(at_epoch, bool):
        raise ValueError("shadow key resolution time is invalid")
    matches = [item for item in keyring["keys"] if item["keyId"] == key_id]
    if len(matches) != 1:
        raise ValueError("shadow public key is not allowlisted")
    item = matches[0]
    if item["status"] == "REVOKED" \
            or not item["notBefore"] <= at_epoch <= item["notAfter"]:
        raise ValueError("shadow public key is not active")
    return _decode_public(item["publicKey"])


def load_keyring(
    path: Path, *, expected_audience: str = AUDIENCE,
) -> dict[str, Any]:
    target = Path(path)
    try:
        info = target.lstat()
    except OSError as exc:
        raise ValueError("shadow keyring file is unavailable") from exc
    if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode) \
            or info.st_size > MAX_FILE_BYTES or info.st_mode & 0o022:
        raise ValueError("shadow keyring file is invalid")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(target, flags)
    except OSError as exc:
        raise ValueError("shadow keyring file is invalid") from exc
    try:
        raw = os.read(fd, MAX_FILE_BYTES + 1)
    finally:
        os.close(fd)
    try:
        return validate_keyring(
            json.loads(raw), expected_audience=expected_audience)
    except Exception as exc:
        raise ValueError("shadow keyring file content is invalid") from exc
