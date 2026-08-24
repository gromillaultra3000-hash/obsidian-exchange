import base64
import json
import re
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "native-wallet/rehearsals/attestation-dependencies/automated-minimal/tests/fixtures"
ENVELOPE_SCHEMA = FIXTURES / "ed25519-corpus-review-assertion-envelope-v1.schema.json"
RESULT_SCHEMA = FIXTURES / "ed25519-corpus-review-verifier-result-v1.schema.json"
SHORTLIST_PATH = FIXTURES / "ed25519-corpus-review-verifier-trust-shortlist-v1.json"
MAX_RESULT_LIFETIME_MS = 600_000
MAX_FUTURE_SKEW_MS = 1_000
HEX64 = re.compile(r"^[0-9a-f]{64}$")
OPAQUE_ID = re.compile(r"^[a-z0-9][a-z0-9._:-]*$")
EVIDENCE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
RESULT_FIELDS = {
    "schema", "profile", "review_request_sha256", "evidence_id",
    "assertion_envelope_sha256", "challenge_sha256", "credential_root_sha256",
    "revocation_epoch", "rp_id", "origin", "algorithm", "credential_type",
    "client_data_type", "user_present", "user_verified", "backup_eligible",
    "backup_state", "challenge_matches", "rp_id_matches", "origin_matches",
    "credential_allowed", "credential_not_revoked", "signature_valid",
    "result_issued_at_epoch_ms", "result_expires_at_epoch_ms",
    "verified_at_epoch_ms", "caller_nonce_sha256", "verifier_policy_sha256",
    "verifier_identity", "verifier_build_sha256", "decision",
}
BINDING_FIELDS = {
    "review_request_sha256", "assertion_envelope_sha256", "challenge_sha256",
    "evidence_id", "credential_root_sha256", "revocation_epoch", "rp_id",
    "origin", "verifier_identity", "verifier_build_sha256",
    "verifier_policy_sha256", "caller_nonce_sha256",
}
HASH_FIELDS = {
    "review_request_sha256", "assertion_envelope_sha256", "challenge_sha256",
    "credential_root_sha256", "verifier_build_sha256", "verifier_policy_sha256",
    "caller_nonce_sha256",
}


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _canonical_decode(value: str, limit: int) -> bytes:
    if not value or "=" in value or any(char.isspace() for char in value):
        raise ValueError("canonical unpadded base64url required")
    padding = "=" * ((4 - len(value) % 4) % 4)
    try:
        decoded = base64.b64decode(value + padding, altchars=b"-_", validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        raise ValueError("invalid base64url") from exc
    if len(decoded) > limit:
        raise ValueError("decoded field exceeds limit")
    if base64.urlsafe_b64encode(decoded).decode("ascii").rstrip("=") != value:
        raise ValueError("non-canonical base64url")
    return decoded


def _accept_external_result(
    result: object,
    expected: dict,
    now_epoch_ms: int,
    consumed_nonce_sha256: set[str],
    consumed_evidence_ids: set[str],
) -> bool:
    required_true = {
        "user_present", "user_verified", "challenge_matches", "rp_id_matches",
        "origin_matches", "credential_allowed", "credential_not_revoked", "signature_valid",
    }
    exact = {
        "schema": "native-wallet-ed25519-corpus-review-verifier-result.v1",
        "profile": "WEBAUTHN_L3_CTAP22_ROAMING_ES256_UV",
        "algorithm": "ES256", "credential_type": "public-key",
        "client_data_type": "webauthn.get", "backup_eligible": False,
        "backup_state": False, "decision": "VERIFIED",
    }
    if not isinstance(result, dict) or set(result) != RESULT_FIELDS:
        return False
    if set(expected) != BINDING_FIELDS:
        return False
    if not all(
        isinstance(result.get(key), str) and HEX64.fullmatch(result[key])
        for key in HASH_FIELDS
    ):
        return False
    if (
        not isinstance(result["evidence_id"], str)
        or EVIDENCE_ID.fullmatch(result["evidence_id"]) is None
        or not isinstance(result["verifier_identity"], str)
        or OPAQUE_ID.fullmatch(result["verifier_identity"]) is None
    ):
        return False
    integer_fields = {
        "revocation_epoch", "result_issued_at_epoch_ms", "result_expires_at_epoch_ms",
        "verified_at_epoch_ms",
    }
    if any(
        isinstance(result[key], bool) or not isinstance(result[key], int) or result[key] < 1
        for key in integer_fields
    ):
        return False
    issued_at = result["result_issued_at_epoch_ms"]
    expires_at = result["result_expires_at_epoch_ms"]
    verified_at = result["verified_at_epoch_ms"]
    if not (
        issued_at <= now_epoch_ms + MAX_FUTURE_SKEW_MS
        and expires_at > now_epoch_ms
        and expires_at > issued_at
        and expires_at - issued_at <= MAX_RESULT_LIFETIME_MS
        and issued_at <= verified_at < expires_at
        and verified_at <= now_epoch_ms + MAX_FUTURE_SKEW_MS
    ):
        return False
    if (
        result["caller_nonce_sha256"] in consumed_nonce_sha256
        or result["evidence_id"] in consumed_evidence_ids
    ):
        return False
    return (
        all(result.get(key) == value for key, value in exact.items())
        and all(result.get(key) is True for key in required_true)
        and all(result.get(key) == expected[key] for key in BINDING_FIELDS)
    )


def test_assertion_envelope_is_closed_bounded_and_non_authoritative():
    schema = _load(ENVELOPE_SCHEMA)
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])
    assert schema["decoded_limits_bytes"] == {
        "credential_id": 1024, "client_data_json": 8192,
        "authenticator_data": 1024, "signature": 1024,
        "user_handle": 64, "whole_envelope": 16384,
    }
    assert schema["assertion_verified"] is False
    assert schema["credential_enrolled"] is False
    assert schema["runtime_integration_allowed"] is False


def test_canonical_base64url_gate_rejects_padding_whitespace_and_oversize():
    exact = base64.urlsafe_b64encode(b"assertion bytes").decode().rstrip("=")
    assert _canonical_decode(exact, 32) == b"assertion bytes"
    for rejected in [exact + "=", exact + " ", "Zh"]:
        try:
            _canonical_decode(rejected, 32)
        except ValueError:
            pass
        else:
            raise AssertionError(f"accepted non-canonical value: {rejected!r}")
    oversized = base64.urlsafe_b64encode(b"x" * 33).decode().rstrip("=")
    try:
        _canonical_decode(oversized, 32)
    except ValueError:
        pass
    else:
        raise AssertionError("accepted oversized decoded value")


def test_external_result_is_closed_ordered_and_grants_nothing():
    schema = _load(RESULT_SCHEMA)
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])
    assert schema["ordered_validation"][0] == "bounded_closed_result_shape"
    assert schema["ordered_validation"][-1] == "issue_and_expiry_window"
    assert "exact_review_request_and_policy_digests" in schema["ordered_validation"]
    assert "single_use_caller_nonce_and_evidence_id" in schema["ordered_validation"]
    assert schema["result_signature_or_attestation_defined"] is False
    assert schema["external_verifier_selected"] is False
    assert schema["reviewer_authenticated"] is False
    assert schema["crypto_call_allowed"] is False
    assert schema["runtime_integration_allowed"] is False


def test_result_schema_carries_every_shortlist_mandatory_binding():
    schema = _load(RESULT_SCHEMA)
    shortlist = _load(SHORTLIST_PATH)
    required = set(schema["required"])
    translations = {
        "review_request_sha256": "review_request_sha256",
        "assertion_envelope_sha256": "assertion_envelope_sha256",
        "challenge_sha256": "challenge_sha256",
        "evidence_id": "evidence_id",
        "credential_root_sha256": "credential_root_sha256",
        "revocation_epoch": "revocation_epoch",
        "verifier_build_sha256": "verifier_build_sha256",
        "verifier_policy_sha256": "verifier_policy_sha256",
        "result_issued_at_epoch_ms": "result_issued_at_epoch_ms",
        "result_expires_at_epoch_ms": "result_expires_at_epoch_ms",
        "caller_nonce_sha256": "caller_nonce_sha256",
    }
    assert set(translations) == set(shortlist["mandatory_cross_bindings"])
    assert set(translations.values()) <= required


def test_all_green_result_still_requires_exact_external_context():
    result = {
        "schema": "native-wallet-ed25519-corpus-review-verifier-result.v1",
        "profile": "WEBAUTHN_L3_CTAP22_ROAMING_ES256_UV",
        "review_request_sha256": "a" * 64,
        "evidence_id": "evidence-reviewer-a", "assertion_envelope_sha256": "1" * 64,
        "challenge_sha256": "2" * 64, "credential_root_sha256": "3" * 64,
        "revocation_epoch": 7, "rp_id": "review.invalid", "origin": "https://review.invalid",
        "algorithm": "ES256", "credential_type": "public-key",
        "client_data_type": "webauthn.get", "user_present": True, "user_verified": True,
        "backup_eligible": False, "backup_state": False, "challenge_matches": True,
        "rp_id_matches": True, "origin_matches": True, "credential_allowed": True,
        "credential_not_revoked": True, "signature_valid": True,
        "result_issued_at_epoch_ms": 1_786_500_000_100,
        "result_expires_at_epoch_ms": 1_786_500_600_100,
        "verified_at_epoch_ms": 1_786_500_000_200,
        "caller_nonce_sha256": "5" * 64,
        "verifier_policy_sha256": "6" * 64,
        "verifier_identity": "verifier-a",
        "verifier_build_sha256": "4" * 64, "decision": "VERIFIED",
    }
    expected = {key: result[key] for key in [
        "review_request_sha256", "evidence_id", "assertion_envelope_sha256",
        "challenge_sha256", "credential_root_sha256", "revocation_epoch", "rp_id",
        "origin", "verifier_identity", "verifier_build_sha256",
        "verifier_policy_sha256", "caller_nonce_sha256",
    ]}
    now = result["verified_at_epoch_ms"]
    assert _accept_external_result(result, expected, now, set(), set())
    for key, value in expected.items():
        drifted = deepcopy(result)
        drifted[key] = value + 1 if isinstance(value, int) else f"{value}x"
        assert not _accept_external_result(drifted, expected, now, set(), set())
    failed = deepcopy(result)
    failed["signature_valid"] = False
    assert not _accept_external_result(failed, expected, now, set(), set())

    for key in ["review_request_sha256", "verifier_policy_sha256", "caller_nonce_sha256"]:
        drifted = deepcopy(result)
        drifted[key] = "0" * 64
        assert not _accept_external_result(drifted, expected, now, set(), set())

    expired = deepcopy(result)
    assert not _accept_external_result(
        expired, expected, expired["result_expires_at_epoch_ms"], set(), set()
    )
    future = deepcopy(result)
    assert not _accept_external_result(
        future,
        expected,
        future["result_issued_at_epoch_ms"] - MAX_FUTURE_SKEW_MS - 1,
        set(),
        set(),
    )
    verified_before_issue = deepcopy(result)
    verified_before_issue["verified_at_epoch_ms"] = verified_before_issue["result_issued_at_epoch_ms"] - 1
    assert not _accept_external_result(verified_before_issue, expected, now, set(), set())
    verified_in_future = deepcopy(result)
    verified_in_future["verified_at_epoch_ms"] = now + MAX_FUTURE_SKEW_MS + 1
    assert not _accept_external_result(verified_in_future, expected, now, set(), set())
    extra = deepcopy(result)
    extra["unexpected"] = True
    assert not _accept_external_result(extra, expected, now, set(), set())
    assert not _accept_external_result(
        result, expected, now, {result["caller_nonce_sha256"]}, set()
    )
    assert not _accept_external_result(
        result, expected, now, set(), {result["evidence_id"]}
    )


def test_no_assertion_verifier_result_or_credential_is_checked_in():
    names = {path.name for path in FIXTURES.iterdir()}
    assert not any(name.endswith(".assertion.json") for name in names)
    assert not any(name.endswith(".verifier-result.json") for name in names)
    for schema_path in [ENVELOPE_SCHEMA, RESULT_SCHEMA]:
        text = schema_path.read_text(encoding="utf-8")
        assert "private_key" not in text
        assert "secret_key" not in text
