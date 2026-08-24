"""Hermetic signed identity envelope for a future shadow advisory transport."""

from __future__ import annotations

import base64
import hashlib
import re
from typing import Any, Callable

SCHEMA = "shadow-service-envelope.v1"
VERIFICATION_SCHEMA = "shadow-service-verification.v1"
ALGORITHM = "Ed25519"
METHOD = "POST"
PATH = "/internal/v1/shadow-advisory"
CONTENT_TYPE = "application/json"
ISSUER = "kairos-shadow"
AUDIENCE = "lumi-shadow"
SCOPE = "shadow:advisory"
MAX_CLOCK_SKEW_SECONDS = 30
_KEYS = {
    "schemaVersion", "algorithm", "keyId", "issuedAt", "nonce", "issuer",
    "audience", "scope", "method", "path", "contentType", "bodySha256",
    "signature",
}


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode(value: Any) -> bytes:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{86}", value):
        raise ValueError("shadow service signature is invalid")
    try:
        decoded = base64.b64decode(
            value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError("shadow service signature is invalid") from exc
    if len(decoded) != 64:
        raise ValueError("shadow service signature is invalid")
    return decoded


def canonical_envelope(value: dict[str, Any]) -> bytes:
    fields = (
        "v1", value["method"], value["path"], "", value["bodySha256"],
        value["contentType"], value["keyId"], str(value["issuedAt"]),
        value["nonce"], value["issuer"], value["scope"], value["audience"],
    )
    if any("\n" in item or "\r" in item for item in fields):
        raise ValueError("shadow service canonical field is invalid")
    return ("\n".join(fields) + "\n").encode("utf-8")


def build_envelope(
    body: bytes, *, key_id: str, issued_at: int, nonce: str,
    signer: Callable[[bytes], bytes],
) -> dict[str, Any]:
    if not isinstance(body, bytes):
        raise ValueError("shadow service body must be bytes")
    unsigned = {
        "schemaVersion": SCHEMA, "algorithm": ALGORITHM, "keyId": key_id,
        "issuedAt": issued_at, "nonce": nonce, "issuer": ISSUER,
        "audience": AUDIENCE, "scope": SCOPE, "method": METHOD, "path": PATH,
        "contentType": CONTENT_TYPE,
        "bodySha256": hashlib.sha256(body).hexdigest(),
    }
    _validate_fields({**unsigned, "signature": "A" * 86}, check_signature=False)
    signature = signer(canonical_envelope(unsigned))
    if not isinstance(signature, bytes) or len(signature) != 64:
        raise ValueError("shadow service signer returned an invalid signature")
    return {**unsigned, "signature": _b64(signature)}


def _validate_fields(value: Any, *, check_signature: bool = True) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != _KEYS \
            or value.get("schemaVersion") != SCHEMA \
            or value.get("algorithm") != ALGORITHM \
            or value.get("method") != METHOD or value.get("path") != PATH \
            or value.get("contentType") != CONTENT_TYPE \
            or value.get("issuer") != ISSUER or value.get("audience") != AUDIENCE \
            or value.get("scope") != SCOPE:
        raise ValueError("shadow service envelope fields differ")
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{2,31}", str(value.get("keyId"))) \
            or not re.fullmatch(r"[A-Za-z0-9_-]{22,64}", str(value.get("nonce"))) \
            or not re.fullmatch(r"[a-f0-9]{64}", str(value.get("bodySha256"))) \
            or not isinstance(value.get("issuedAt"), int) \
            or isinstance(value.get("issuedAt"), bool) or value["issuedAt"] < 0:
        raise ValueError("shadow service envelope identity is invalid")
    if check_signature:
        _decode(value.get("signature"))
    canonical_envelope(value)
    return value


def verify_envelope(
    envelope: Any, body: bytes, *, now_epoch: int,
    verify_signature: Callable[[str, bytes, bytes], None],
    consume_nonce: Callable[[str, str, int], None],
) -> dict[str, Any]:
    value = _validate_fields(envelope)
    if not isinstance(body, bytes) or hashlib.sha256(body).hexdigest() != value["bodySha256"]:
        raise ValueError("shadow service body hash differs")
    if not isinstance(now_epoch, int) or isinstance(now_epoch, bool) \
            or abs(now_epoch - value["issuedAt"]) > MAX_CLOCK_SKEW_SECONDS:
        raise ValueError("shadow service timestamp is outside replay window")
    try:
        verify_signature(
            value["keyId"], _decode(value["signature"]), canonical_envelope(value))
    except Exception as exc:
        raise ValueError("shadow service signature verification failed") from exc
    expires_at = value["issuedAt"] + MAX_CLOCK_SKEW_SECONDS
    consume_nonce(value["keyId"], value["nonce"], expires_at)
    return {
        "schemaVersion": VERIFICATION_SCHEMA, "verified": True,
        "keyId": value["keyId"], "issuer": ISSUER, "audience": AUDIENCE,
        "scope": SCOPE, "requestHash": value["bodySha256"],
        "issuedAt": value["issuedAt"], "expiresAt": expires_at,
        "replayProtected": True, "executionEffect": "NONE", "actionAllowed": False,
    }
