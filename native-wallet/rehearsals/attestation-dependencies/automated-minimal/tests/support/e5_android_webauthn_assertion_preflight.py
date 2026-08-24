"""Test-only WebAuthn assertion preflight for the Android handoff rehearsal.

The function in this module checks bounded transport and WebAuthn data shape
only. It deliberately does not look up a credential, read a trust registry,
check revocation, or verify an ES256 signature. Its positive result is
therefore a preflight result, never authentication or authority.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from collections.abc import Mapping


SCHEMA = "native-wallet-e5-android-webauthn-assertion-preflight.v1"
ENVELOPE_SCHEMA = "native-wallet-ed25519-corpus-review-assertion-envelope.v1"
PROFILE = "WEBAUTHN_L3_CTAP22_ROAMING_ES256_UV"
MAX_CREDENTIAL_ID_BYTES = 1_024
MAX_CLIENT_DATA_BYTES = 8_192
MAX_AUTHENTICATOR_DATA_BYTES = 1_024
MAX_SIGNATURE_BYTES = 1_024
MAX_USER_HANDLE_BYTES = 64
MAX_WHOLE_ENVELOPE_BYTES = 16_384
MAX_JSON_DEPTH = 2
MAX_JSON_TOKENS = 32
MAX_JSON_STRING_BYTES = 2_048
EVIDENCE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{7,63}$")


class AssertionPreflightError(ValueError):
    """Raised when a bounded assertion cannot be accepted for preflight."""


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _canonical_b64url(value: object, *, field: str, limit: int) -> bytes:
    if not isinstance(value, str) or not value or "=" in value or any(
        character.isspace() for character in value
    ):
        raise AssertionPreflightError(f"{field} must be unpadded base64url")
    padding = "=" * ((4 - len(value) % 4) % 4)
    try:
        decoded = base64.b64decode(value + padding, altchars=b"-_", validate=True)
    except (ValueError, binascii.Error) as exc:
        raise AssertionPreflightError(f"{field} is not valid base64url") from exc
    if len(decoded) > limit:
        raise AssertionPreflightError(f"{field} exceeds decoded byte limit")
    if base64.urlsafe_b64encode(decoded).decode("ascii").rstrip("=") != value:
        raise AssertionPreflightError(f"{field} is not canonical base64url")
    return decoded


def _strict_json(value: bytes) -> Mapping[str, object]:
    if len(value) > MAX_CLIENT_DATA_BYTES:
        raise AssertionPreflightError("client data exceeds byte limit")

    def reject_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, item in pairs:
            if key in result:
                raise AssertionPreflightError("duplicate client-data field")
            result[key] = item
        return result

    try:
        parsed = json.loads(
            value.decode("utf-8"),
            object_pairs_hook=reject_duplicate_pairs,
            parse_constant=lambda _constant: (_ for _ in ()).throw(
                AssertionPreflightError("non-standard JSON number")
            ),
        )
    except AssertionPreflightError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
        raise AssertionPreflightError("client data JSON is invalid") from exc
    if not isinstance(parsed, Mapping):
        raise AssertionPreflightError("client data JSON must be an object")

    token_count = 0

    def check_bounds(item: object, depth: int) -> None:
        nonlocal token_count
        token_count += 1
        if token_count > MAX_JSON_TOKENS:
            raise AssertionPreflightError("client data exceeds token limit")
        if depth > MAX_JSON_DEPTH:
            raise AssertionPreflightError("client data exceeds depth limit")
        if isinstance(item, str) and len(item.encode("utf-8")) > MAX_JSON_STRING_BYTES:
            raise AssertionPreflightError("client data string exceeds byte limit")
        if isinstance(item, Mapping):
            for key, child in item.items():
                check_bounds(key, depth + 1)
                check_bounds(child, depth + 1)
        elif isinstance(item, list):
            for child in item:
                check_bounds(child, depth + 1)

    check_bounds(parsed, 0)
    return parsed


def _assertion_fields(value: object) -> dict[str, object]:
    required = {
        "schema",
        "evidence_id",
        "credential_id_base64url",
        "client_data_json_base64url",
        "authenticator_data_base64url",
        "signature_base64url",
        "user_handle_base64url",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise AssertionPreflightError("assertion envelope shape is not closed")
    if value["schema"] != ENVELOPE_SCHEMA:
        raise AssertionPreflightError("assertion envelope schema is invalid")
    evidence_id = value["evidence_id"]
    if not isinstance(evidence_id, str) or EVIDENCE_ID.fullmatch(evidence_id) is None:
        raise AssertionPreflightError("evidence_id is invalid")
    return dict(value)


def preflight_assertion(
    envelope: Mapping[str, object],
    *,
    expected_challenge_b64url: str,
    expected_rp_id: str,
    expected_origin: str,
    role: str,
) -> dict[str, object]:
    """Validate a future phone assertion without authenticating it."""
    if role not in {"reviewer", "owner"}:
        raise AssertionPreflightError("role must be reviewer or owner")
    fields = _assertion_fields(envelope)
    credential_id = _canonical_b64url(
        fields["credential_id_base64url"],
        field="credential_id_base64url",
        limit=MAX_CREDENTIAL_ID_BYTES,
    )
    client_data = _canonical_b64url(
        fields["client_data_json_base64url"],
        field="client_data_json_base64url",
        limit=MAX_CLIENT_DATA_BYTES,
    )
    authenticator_data = _canonical_b64url(
        fields["authenticator_data_base64url"],
        field="authenticator_data_base64url",
        limit=MAX_AUTHENTICATOR_DATA_BYTES,
    )
    signature = _canonical_b64url(
        fields["signature_base64url"],
        field="signature_base64url",
        limit=MAX_SIGNATURE_BYTES,
    )
    user_handle_value = fields["user_handle_base64url"]
    if user_handle_value is None:
        user_handle = None
    else:
        user_handle = _canonical_b64url(
            user_handle_value,
            field="user_handle_base64url",
            limit=MAX_USER_HANDLE_BYTES,
        )
    if sum(
        len(item) for item in [credential_id, client_data, authenticator_data, signature]
        if item is not None
    ) + (len(user_handle) if user_handle is not None else 0) > MAX_WHOLE_ENVELOPE_BYTES:
        raise AssertionPreflightError("decoded assertion exceeds whole-envelope limit")

    client = _strict_json(client_data)
    if set(client) not in ({"type", "challenge", "origin"}, {"type", "challenge", "origin", "crossOrigin"}):
        raise AssertionPreflightError("client data has missing or unknown fields")
    if client.get("type") != "webauthn.get":
        raise AssertionPreflightError("client data type is invalid")
    if client.get("challenge") != expected_challenge_b64url:
        raise AssertionPreflightError("client data challenge does not match session")
    if client.get("origin") != expected_origin:
        raise AssertionPreflightError("client data origin does not match session")
    if "crossOrigin" in client and client["crossOrigin"] is not False:
        raise AssertionPreflightError("cross-origin client data is forbidden")
    expected_challenge = _canonical_b64url(
        expected_challenge_b64url,
        field="expected_challenge_b64url",
        limit=32,
    )
    if len(expected_challenge) != 32:
        raise AssertionPreflightError("expected challenge must be exactly 32 bytes")

    if len(authenticator_data) != 37:
        raise AssertionPreflightError("authenticator data must be exactly 37 bytes")
    if not isinstance(expected_rp_id, str) or not expected_rp_id:
        raise AssertionPreflightError("expected RP ID is invalid")
    try:
        expected_rp_hash = hashlib.sha256(expected_rp_id.encode("ascii")).digest()
    except UnicodeEncodeError as exc:
        raise AssertionPreflightError("expected RP ID must be ASCII") from exc
    if authenticator_data[:32] != expected_rp_hash:
        raise AssertionPreflightError("RP ID hash does not match expected RP ID")
    if authenticator_data[32] != 0x05:
        raise AssertionPreflightError("authenticator flags must be exactly UP+UV (0x05)")

    return {
        "schema": SCHEMA,
        "profile": PROFILE,
        "role": role,
        "evidenceId": fields["evidence_id"],
        "assertionEnvelopeSha256": hashlib.sha256(_canonical(fields)).hexdigest(),
        "credentialIdShapeValid": True,
        "clientDataShapeValid": True,
        "authenticatorDataShapeValid": True,
        "challengeMatches": True,
        "rpIdMatches": True,
        "originMatches": True,
        "userPresent": True,
        "userVerified": True,
        "backupEligible": False,
        "backupState": False,
        "credentialLookupImplemented": False,
        "credentialAllowed": False,
        "revocationLookupImplemented": False,
        "credentialNotRevoked": False,
        "es256SignatureVerificationImplemented": False,
        "signatureValid": False,
        "preflightStructurallyValid": True,
        "authenticated": False,
        "selectionAllowed": False,
        "cryptoCallAllowed": False,
        "runtimeIntegrationAllowed": False,
    }
