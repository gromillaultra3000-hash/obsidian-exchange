import base64
import copy
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUPPORT = ROOT / "native-wallet/rehearsals/attestation-dependencies/automated-minimal/tests/support"
sys.path.insert(0, str(SUPPORT))

from e5_android_webauthn_assertion_preflight import (  # noqa: E402
    AssertionPreflightError,
    preflight_assertion,
)


RP_ID = "review.invalid"
ORIGIN = "https://review.invalid"
CHALLENGE = bytes(range(32))
CHALLENGE_B64URL = base64.urlsafe_b64encode(CHALLENGE).decode().rstrip("=")


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _envelope() -> dict[str, object]:
    client_data = json.dumps(
        {"type": "webauthn.get", "challenge": CHALLENGE_B64URL, "origin": ORIGIN},
        separators=(",", ":"),
    ).encode()
    authenticator_data = hashlib.sha256(RP_ID.encode()).digest() + b"\x05\x00\x00\x00\x01"
    return {
        "schema": "native-wallet-ed25519-corpus-review-assertion-envelope.v1",
        "evidence_id": "reviewer-proof-01",
        "credential_id_base64url": _b64(b"credential-id"),
        "client_data_json_base64url": _b64(client_data),
        "authenticator_data_base64url": _b64(authenticator_data),
        "signature_base64url": _b64(b"synthetic-signature-bytes"),
        "user_handle_base64url": None,
    }


def test_preflight_accepts_exact_shape_but_grants_no_authentication():
    result = preflight_assertion(
        _envelope(), expected_challenge_b64url=CHALLENGE_B64URL,
        expected_rp_id=RP_ID, expected_origin=ORIGIN, role="reviewer",
    )
    assert result["preflightStructurallyValid"] is True
    assert result["challengeMatches"] is True
    assert result["rpIdMatches"] is True
    assert result["originMatches"] is True
    assert result["userPresent"] is True
    assert result["userVerified"] is True
    assert result["backupEligible"] is False
    assert result["backupState"] is False
    assert result["credentialLookupImplemented"] is False
    assert result["signatureValid"] is False
    assert result["authenticated"] is False
    assert result["selectionAllowed"] is False


def test_preflight_rejects_challenge_origin_rp_and_flags_drift():
    mutations = []
    changed = copy.deepcopy(_envelope())
    client = json.loads(base64.urlsafe_b64decode(changed["client_data_json_base64url"] + "=="))
    client["challenge"] = _b64(b"wrong")
    changed["client_data_json_base64url"] = _b64(json.dumps(client, separators=(",", ":")).encode())
    mutations.append(changed)

    changed = copy.deepcopy(_envelope())
    client = json.loads(base64.urlsafe_b64decode(changed["client_data_json_base64url"] + "=="))
    client["origin"] = "https://other.invalid"
    changed["client_data_json_base64url"] = _b64(json.dumps(client, separators=(",", ":")).encode())
    mutations.append(changed)

    changed = copy.deepcopy(_envelope())
    raw = bytearray(base64.urlsafe_b64decode(changed["authenticator_data_base64url"] + "=="))
    raw[32] = 0x01
    changed["authenticator_data_base64url"] = _b64(bytes(raw))
    mutations.append(changed)

    changed = copy.deepcopy(_envelope())
    raw = bytearray(base64.urlsafe_b64decode(changed["authenticator_data_base64url"] + "=="))
    raw[:32] = hashlib.sha256(b"other.invalid").digest()
    changed["authenticator_data_base64url"] = _b64(bytes(raw))
    mutations.append(changed)

    for value in mutations:
        try:
            preflight_assertion(
                value, expected_challenge_b64url=CHALLENGE_B64URL,
                expected_rp_id=RP_ID, expected_origin=ORIGIN, role="reviewer",
            )
        except AssertionPreflightError:
            pass
        else:
            raise AssertionError("preflight accepted challenge/RP/origin/flags drift")


def test_preflight_rejects_duplicate_or_unknown_client_fields():
    value = _envelope()
    client = '{"type":"webauthn.get","type":"webauthn.get","challenge":"%s","origin":"%s"}' % (CHALLENGE_B64URL, ORIGIN)
    value["client_data_json_base64url"] = _b64(client.encode())
    for changed in [value, {**_envelope(), "extra": "nope"}]:
        try:
            preflight_assertion(
                changed, expected_challenge_b64url=CHALLENGE_B64URL,
                expected_rp_id=RP_ID, expected_origin=ORIGIN, role="owner",
            )
        except AssertionPreflightError:
            pass
        else:
            raise AssertionError("malformed client/envelope shape was accepted")


def test_preflight_rejects_noncanonical_base64_and_oversized_fields():
    value = _envelope()
    value["signature_base64url"] += "="
    try:
        preflight_assertion(
            value, expected_challenge_b64url=CHALLENGE_B64URL,
            expected_rp_id=RP_ID, expected_origin=ORIGIN, role="owner",
        )
    except AssertionPreflightError:
        pass
    else:
        raise AssertionError("padded base64url was accepted")

    value = _envelope()
    value["signature_base64url"] = _b64(b"x" * 1_025)
    try:
        preflight_assertion(
            value, expected_challenge_b64url=CHALLENGE_B64URL,
            expected_rp_id=RP_ID, expected_origin=ORIGIN, role="owner",
        )
    except AssertionPreflightError:
        pass
    else:
        raise AssertionError("oversized signature was accepted")


def test_preflight_rejects_invalid_role_and_wrong_challenge_length():
    for role in ["server", "", "reviewer/owner"]:
        try:
            preflight_assertion(
                _envelope(), expected_challenge_b64url=CHALLENGE_B64URL,
                expected_rp_id=RP_ID, expected_origin=ORIGIN, role=role,
            )
        except AssertionPreflightError:
            pass
        else:
            raise AssertionError("invalid role was accepted")
    try:
        preflight_assertion(
            _envelope(), expected_challenge_b64url=_b64(b"short"),
            expected_rp_id=RP_ID, expected_origin=ORIGIN, role="reviewer",
        )
    except AssertionPreflightError:
        pass
    else:
        raise AssertionError("short expected challenge was accepted")


def test_preflight_rejects_non_boolean_cross_origin():
    value = _envelope()
    client = json.loads(base64.urlsafe_b64decode(value["client_data_json_base64url"] + "=="))
    client["crossOrigin"] = True
    value["client_data_json_base64url"] = _b64(json.dumps(client, separators=(",", ":")).encode())
    try:
        preflight_assertion(
            value, expected_challenge_b64url=CHALLENGE_B64URL,
            expected_rp_id=RP_ID, expected_origin=ORIGIN, role="reviewer",
        )
    except AssertionPreflightError:
        pass
    else:
        raise AssertionError("cross-origin assertion was accepted")


def test_preflight_rejects_json_depth_token_and_string_overflow():
    for client in [
        {"type": "webauthn.get", "challenge": CHALLENGE_B64URL, "origin": ORIGIN, "nested": {"x": {"y": 1}}},
        {"type": "webauthn.get", "challenge": CHALLENGE_B64URL, "origin": ORIGIN, "values": list(range(40))},
        {"type": "webauthn.get", "challenge": "x" * 2_049, "origin": ORIGIN},
    ]:
        value = _envelope()
        value["client_data_json_base64url"] = _b64(json.dumps(client, separators=(",", ":")).encode())
        try:
            preflight_assertion(
                value, expected_challenge_b64url=CHALLENGE_B64URL,
                expected_rp_id=RP_ID, expected_origin=ORIGIN, role="reviewer",
            )
        except AssertionPreflightError:
            pass
        else:
            raise AssertionError("oversized client-data JSON was accepted")


def test_preflight_result_does_not_expose_assertion_bytes():
    result = preflight_assertion(
        _envelope(), expected_challenge_b64url=CHALLENGE_B64URL,
        expected_rp_id=RP_ID, expected_origin=ORIGIN, role="owner",
    )
    assert set(result).isdisjoint({
        "credentialId", "clientDataJson", "authenticatorData", "signature",
        "userHandle", "credentialIdBase64Url", "clientDataJsonBase64Url",
        "authenticatorDataBase64Url", "signatureBase64Url",
    })
