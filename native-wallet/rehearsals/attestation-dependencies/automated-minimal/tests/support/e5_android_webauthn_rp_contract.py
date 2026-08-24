"""Inert test-only RP route contract for the Android WebAuthn rehearsal.

This is a pure request/response adapter. It does not listen on a socket, read
environment/configuration, persist sessions, enroll credentials, verify
signatures, or select an issuer. A caller supplies the already-created
pre-auth sessions and the exact expected context.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from urllib.parse import urlsplit

from e5_android_webauthn_assertion_preflight import (
    AssertionPreflightError,
    preflight_assertion,
)
from e5_android_webauthn_preauth import (
    PreAuthSessionError,
    validate_preauth_session,
)


SCHEMA = "native-wallet-e5-android-webauthn-rp-contract.v1"
MAX_REQUEST_BODY_BYTES = 32_768
SESSION_ID = re.compile(r"^e5s_[0-9a-f]{32}$")


def _error(*, code: str) -> dict[str, object]:
    return {
        "schema": SCHEMA,
        "status": "REJECTED",
        "errorCode": code,
        "cryptographicVerificationImplemented": False,
        "authenticated": False,
        "selectionAllowed": False,
        "cryptoCallAllowed": False,
        "runtimeIntegrationAllowed": False,
    }


def _parse_path(path: str) -> tuple[str, str, bool]:
    if not isinstance(path, str):
        raise ValueError("path is invalid")
    parsed = urlsplit(path)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
        raise ValueError("path must be a relative path without query or fragment")
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) not in {4, 5} or parts[:2] != ["e5", "webauthn"]:
        raise ValueError("route is unknown")
    role, session_id = parts[2], parts[3]
    if role not in {"reviewer", "owner"} or SESSION_ID.fullmatch(session_id) is None:
        raise ValueError("route identity is invalid")
    if len(parts) == 5 and parts[4] != "assertion":
        raise ValueError("route action is unknown")
    return role, session_id, len(parts) == 5


def _parse_body(body: bytes | bytearray | None) -> Mapping[str, object]:
    if body is None:
        raise ValueError("request body is required")
    if not isinstance(body, (bytes, bytearray)) or len(body) > MAX_REQUEST_BODY_BYTES:
        raise ValueError("request body is invalid or too large")
    pairs_seen: set[str] = set()

    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in pairs_seen:
                raise ValueError("duplicate request field")
            pairs_seen.add(key)
            result[key] = value
        return result

    try:
        parsed = json.loads(
            bytes(body).decode("utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda _constant: (_ for _ in ()).throw(
                ValueError("non-standard JSON value")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ValueError("request JSON is invalid") from exc
    if not isinstance(parsed, Mapping) or set(parsed) != {"assertion"}:
        raise ValueError("request shape is not closed")
    if not isinstance(parsed["assertion"], Mapping):
        raise ValueError("assertion must be an object")
    return parsed


def handle_test_only_request(
    *,
    method: str,
    path: str,
    body: bytes | bytearray | None,
    sessions: Mapping[str, Mapping[str, object]],
    expected_context: Mapping[str, object],
    now_epoch_ms: int,
) -> tuple[int, dict[str, object]]:
    """Return an inert RP response for one synthetic request."""
    try:
        role, session_id, assertion_route = _parse_path(path)
    except ValueError:
        return 404, _error(code="ROUTE_NOT_FOUND")
    if session_id not in sessions:
        return 404, _error(code="SESSION_NOT_FOUND")
    session = sessions[session_id]
    try:
        session_result = validate_preauth_session(
            session,
            expected_context=expected_context,
            expected_role=role,
            now_epoch_ms=now_epoch_ms,
        )
    except PreAuthSessionError:
        return 409, _error(code="SESSION_NOT_USABLE")

    if method != method.upper():
        return 405, _error(code="METHOD_NOT_ALLOWED")
    if not assertion_route:
        if method != "GET" or body not in (None, b"", bytearray()):
            return 405, _error(code="METHOD_NOT_ALLOWED")
        return 200, {
            "schema": "native-wallet-e5-android-webauthn-rp-session-view.v1",
            "role": role,
            "sessionId": session_id,
            "context": session["context"],
            "challengeB64Url": session["challengeB64Url"],
            "challengeSha256": session["challengeSha256"],
            "rpId": session["rpId"],
            "origin": session["origin"],
            "issuedAtEpochMs": session["issuedAtEpochMs"],
            "expiresAtEpochMs": session["expiresAtEpochMs"],
            "action": "ASSERTION_PREFLIGHT_ONLY",
            "sessionPreAuthStructurallyValid": session_result["preAuthStructurallyValid"],
            "cryptographicVerificationImplemented": False,
            "authenticated": False,
            "selectionAllowed": False,
            "cryptoCallAllowed": False,
            "runtimeIntegrationAllowed": False,
        }
    if method != "POST":
        return 405, _error(code="METHOD_NOT_ALLOWED")
    try:
        request = _parse_body(body)
    except ValueError:
        return 400, _error(code="MALFORMED_REQUEST")
    try:
        preflight = preflight_assertion(
            request["assertion"],
            expected_challenge_b64url=session["challengeB64Url"],
            expected_rp_id=session["rpId"],
            expected_origin=session["origin"],
            role=role,
        )
    except AssertionPreflightError:
        return 422, _error(code="ASSERTION_PREFLIGHT_REJECTED")
    return 200, {
        "schema": "native-wallet-e5-android-webauthn-rp-assertion-response.v1",
        "status": "PREFLIGHT_ONLY",
        "role": role,
        "sessionId": session_id,
        "sessionPreAuthStructurallyValid": session_result["preAuthStructurallyValid"],
        "preflight": preflight,
        "replayLedgerConfigured": False,
        "consumptionPerformed": False,
        "cryptographicVerificationImplemented": False,
        "authenticated": False,
        "selectionAllowed": False,
        "cryptoCallAllowed": False,
        "runtimeIntegrationAllowed": False,
    }
