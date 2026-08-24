"""Relay-side Ed25519 client for scoped internal KAIROS requests."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from pathlib import Path
from urllib.parse import urlparse

import requests
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _read_key(path_env: str, default: str) -> bytes:
    path = Path(os.getenv(path_env) or default)
    raw = base64.urlsafe_b64decode(path.read_text(encoding="ascii").strip() + "==")
    if len(raw) != 32:
        raise RuntimeError(f"{path_env} key must be 32 bytes")
    return raw


def principal_for_web_user(web_user_id: int) -> str:
    key = _read_key("RELAY_KAIROS_PRINCIPAL_KEY_FILE", "/etc/obsidian-relay/principal.key")
    digest = hmac.new(key, f"oe:web:v1:{int(web_user_id)}".encode(), hashlib.sha256).hexdigest()
    return "oe_web_" + digest[:48]


def _base_url() -> str:
    value = (os.getenv("KAIROS_URL") or "http://127.0.0.1:8000").rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise RuntimeError("KAIROS_URL must be loopback HTTP")
    return value


def signed_request(
    method: str, path: str, *, principal: str, scope: str,
    payload: dict | None = None, timeout: float = 5.0,
) -> dict:
    if not path.startswith("/internal/v1/") or "?" in path:
        raise ValueError("internal KAIROS path must be exact and query-free")
    method = method.upper()
    if method not in {"GET", "POST", "DELETE"}:
        raise ValueError("unsupported internal KAIROS method")
    if method == "GET" and payload is not None:
        raise ValueError("GET request cannot have a payload")
    key_id = os.getenv("RELAY_KAIROS_KEY_ID", "relay-v1").strip()
    timestamp = str(int(time.time()))
    nonce = _b64(secrets.token_bytes(18))
    body = b"" if payload is None else json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    content_type = "" if not body else "application/json"
    body_hash = hashlib.sha256(body).hexdigest()
    canonical = ("\n".join((
        "v1", method, path, "", body_hash, content_type, key_id, timestamp, nonce,
        principal, scope, "kairos",
    )) + "\n").encode()
    private_raw = _read_key(
        "RELAY_KAIROS_PRIVATE_KEY_FILE", "/etc/obsidian-relay/signing.key")
    signature = _b64(Ed25519PrivateKey.from_private_bytes(private_raw).sign(canonical))
    headers = {
        "X-OE-Signature-Version": "1", "X-OE-Key-Id": key_id,
        "X-OE-Timestamp": timestamp, "X-OE-Nonce": nonce,
        "X-OE-Principal": principal, "X-OE-Scope": scope,
        "X-OE-Body-SHA256": body_hash, "X-OE-Signature": signature,
    }
    if content_type:
        headers["Content-Type"] = content_type
    response = requests.request(
        method, _base_url() + path, headers=headers, data=body or None,
        timeout=timeout, allow_redirects=False)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise RuntimeError("invalid KAIROS service response")
    return data


def signed_get(path: str, *, principal: str, scope: str, timeout: float = 5.0) -> dict:
    return signed_request("GET", path, principal=principal, scope=scope, timeout=timeout)
