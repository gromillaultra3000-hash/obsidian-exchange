"""Pure bounded replay-ledger snapshot transitions for shadow service identity."""

from __future__ import annotations

import hashlib
import re
from typing import Any

SNAPSHOT_SCHEMA = "shadow-replay-ledger.v1"
TRANSITION_SCHEMA = "shadow-replay-transition.v1"
MAX_CAPACITY = 10000
MAX_RETENTION_SECONDS = 60
_SNAPSHOT_KEYS = {"schemaVersion", "capacity", "entryCount", "entries"}
_ENTRY_KEYS = {"replayKey", "expiresAt"}


def empty_snapshot(*, capacity: int = MAX_CAPACITY) -> dict[str, Any]:
    value = {
        "schemaVersion": SNAPSHOT_SCHEMA, "capacity": capacity,
        "entryCount": 0, "entries": [],
    }
    return validate_snapshot(value)


def validate_snapshot(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != _SNAPSHOT_KEYS \
            or value.get("schemaVersion") != SNAPSHOT_SCHEMA:
        raise ValueError("shadow replay snapshot fields differ")
    capacity = value.get("capacity")
    count = value.get("entryCount")
    entries = value.get("entries")
    if not isinstance(capacity, int) or isinstance(capacity, bool) \
            or not 1 <= capacity <= MAX_CAPACITY \
            or not isinstance(count, int) or isinstance(count, bool) \
            or not isinstance(entries, list) or count != len(entries) \
            or count > capacity:
        raise ValueError("shadow replay snapshot cardinality is invalid")
    previous = ""
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != _ENTRY_KEYS \
                or not re.fullmatch(r"[a-f0-9]{64}", str(entry.get("replayKey"))) \
                or not isinstance(entry.get("expiresAt"), int) \
                or isinstance(entry.get("expiresAt"), bool) or entry["expiresAt"] < 0 \
                or entry["replayKey"] <= previous:
            raise ValueError("shadow replay snapshot entry is invalid")
        previous = entry["replayKey"]
    return value


def replay_key(key_id: str, nonce: str) -> str:
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{2,31}", str(key_id)) \
            or not re.fullmatch(r"[A-Za-z0-9_-]{22,64}", str(nonce)):
        raise ValueError("shadow replay identity is invalid")
    return hashlib.sha256(f"{key_id}\0{nonce}".encode()).hexdigest()


def consume(
    snapshot: Any, *, key_id: str, nonce: str, now_epoch: int,
    expires_at: int,
) -> dict[str, Any]:
    current = validate_snapshot(snapshot)
    if not isinstance(now_epoch, int) or isinstance(now_epoch, bool) or now_epoch < 0 \
            or not isinstance(expires_at, int) or isinstance(expires_at, bool) \
            or not now_epoch <= expires_at <= now_epoch + MAX_RETENTION_SECONDS:
        raise ValueError("shadow replay expiry is invalid")
    identity = replay_key(key_id, nonce)
    active = [dict(entry) for entry in current["entries"]
              if entry["expiresAt"] >= now_epoch]
    if any(entry["replayKey"] == identity for entry in active):
        raise ValueError("shadow service request replayed")
    if len(active) >= current["capacity"]:
        raise ValueError("shadow replay capacity exceeded")
    entries = sorted(
        [*active, {"replayKey": identity, "expiresAt": expires_at}],
        key=lambda entry: entry["replayKey"])
    next_snapshot = validate_snapshot({
        "schemaVersion": SNAPSHOT_SCHEMA, "capacity": current["capacity"],
        "entryCount": len(entries), "entries": entries,
    })
    return {
        "schemaVersion": TRANSITION_SCHEMA, "accepted": True,
        "replayKey": identity, "previousCount": current["entryCount"],
        "prunedCount": current["entryCount"] - len(active),
        "nextSnapshot": next_snapshot, "replayProtected": True,
        "executionEffect": "NONE", "actionAllowed": False,
    }
