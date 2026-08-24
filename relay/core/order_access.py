"""Short-lived bearer proof for the legacy numeric payment-status link."""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time


TTL_SECONDS = 2 * 60 * 60


def _secret() -> bytes:
    value = (os.getenv("RELAY_SECRET") or "").strip()
    return value.encode() if value and value != "fallback" else b""


def issue(order_id: int, user_id: int, *, now: int | None = None) -> str | None:
    key = _secret()
    oid, uid = int(order_id), int(user_id)
    if not key or oid <= 0 or uid <= 0:
        return None
    body = f"{int(now or time.time())}.{oid}.{uid}.{secrets.token_hex(12)}"
    signature = hmac.new(key, body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{signature}"


def verify(proof: str, order_id: int, *, now: int | None = None,
           ttl: int = TTL_SECONDS) -> int | None:
    key = _secret()
    parts = str(proof or "").split(".")
    if not key or len(parts) != 5:
        return None
    timestamp, oid, uid, nonce, signature = parts
    body = f"{timestamp}.{oid}.{uid}.{nonce}"
    expected = hmac.new(key, body.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return None
    try:
        issued_at, claimed_order, claimed_user = int(timestamp), int(oid), int(uid)
        current = int(now or time.time())
    except (TypeError, ValueError):
        return None
    if claimed_order != int(order_id) or claimed_order <= 0 or claimed_user <= 0:
        return None
    if current < issued_at - 1 or current - issued_at > max(1, min(int(ttl), TTL_SECONDS)):
        return None
    if len(nonce) != 24:
        return None
    try:
        bytes.fromhex(nonce)
    except ValueError:
        return None
    return claimed_user
