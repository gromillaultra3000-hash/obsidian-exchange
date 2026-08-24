import hashlib
import json
import re
from copy import deepcopy
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "native-wallet/rehearsals/attestation-dependencies/automated-minimal/tests/fixtures"
REQUEST_PATH = FIXTURES / "ed25519-corpus-review-request-v1.json"
SCHEMA_PATH = FIXTURES / "ed25519-corpus-review-response-v1.schema.json"
AUTH_PATH = FIXTURES / "ed25519-corpus-review-authentication-v1.json"
MAX_LIFETIME_MS = 600_000
MAX_FUTURE_SKEW_MS = 1_000
REVIEWER_ID = re.compile(r"^[a-z0-9][a-z0-9._:-]*$")
OPAQUE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
TRUST_DOMAINS = {
    "independent_security",
    "standards_and_licensing",
    "reproducible_build",
}


def _field(value: str) -> bytes:
    encoded = value.encode("utf-8")
    if not encoded or len(encoded) > 65535:
        raise ValueError("bounded non-empty UTF-8 field required")
    return len(encoded).to_bytes(2, "big") + encoded


def _raw_digest(value: str) -> bytes:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError("canonical SHA-256 required")
    return bytes.fromhex(value)


def _review_challenge(response: dict) -> str:
    auth = response["authentication"]
    parts = [
        _field("obsidian.ed25519-corpus-review.webauthn.v1"),
        _raw_digest(response["request_sha256"]),
        _field(response["reviewer_id"]),
        _field(response["trust_domain"]),
        _field(response["reviewed_at"]),
        _field(auth["evidence_id"]),
        _raw_digest(auth["credential_root_sha256"]),
        _field(auth["recovery_authority_id"]),
        auth["revocation_epoch"].to_bytes(8, "big"),
        auth["issued_at_epoch_ms"].to_bytes(8, "big"),
        auth["expires_at_epoch_ms"].to_bytes(8, "big"),
        _raw_digest(auth["assertion_envelope_sha256"]),
    ]
    return hashlib.sha256(b"".join(parts)).hexdigest()


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _epoch_millis(value: object) -> int | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return int(parsed.timestamp() * 1000)


def _is_response_shape_valid(
    response: object, request: dict, request_digest: str, now_epoch_ms: int
) -> bool:
    if not isinstance(response, dict):
        return False
    if set(response) != {
        "schema",
        "request_sha256",
        "reviewer_id",
        "trust_domain",
        "reviewer_role",
        "reviewed_at",
        "checks",
        "decision",
        "authentication",
    }:
        return False
    if response["schema"] != "native-wallet-ed25519-corpus-review-response.v1":
        return False
    reviewer_id = response["reviewer_id"]
    if (
        not isinstance(reviewer_id, str)
        or not 1 <= len(reviewer_id) <= 128
        or REVIEWER_ID.fullmatch(reviewer_id) is None
    ):
        return False
    if response["trust_domain"] not in TRUST_DOMAINS:
        return False
    if response["reviewer_role"] != "non_generator_reviewer":
        return False
    if _epoch_millis(response["reviewed_at"]) is None:
        return False
    if response["request_sha256"] != request_digest:
        return False
    checks = response["checks"]
    required = set(request["required_checks"])
    if not isinstance(checks, dict) or set(checks) != required:
        return False
    if any(value is not True for value in checks.values()):
        return False
    if response["decision"] != "APPROVE":
        return False
    authentication = response["authentication"]
    if not isinstance(authentication, dict) or set(authentication) != {
        "profile",
        "evidence_id",
        "challenge_sha256",
        "credential_root_sha256",
        "recovery_authority_id",
        "revocation_epoch",
        "issued_at_epoch_ms",
        "expires_at_epoch_ms",
        "assertion_envelope_sha256",
    }:
        return False
    if authentication["profile"] != "WEBAUTHN_L3_CTAP22_ROAMING_ES256_UV":
        return False
    for key in ("evidence_id", "recovery_authority_id"):
        value = authentication[key]
        if (
            not isinstance(value, str)
            or not 8 <= len(value) <= 64
            or OPAQUE_ID.fullmatch(value) is None
        ):
            return False
    for key in ("challenge_sha256", "credential_root_sha256", "assertion_envelope_sha256"):
        value = authentication[key]
        if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
            return False
    for key in ("revocation_epoch", "issued_at_epoch_ms", "expires_at_epoch_ms"):
        value = authentication[key]
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            return False
    issued_at = authentication["issued_at_epoch_ms"]
    expires_at = authentication["expires_at_epoch_ms"]
    return (
        issued_at <= now_epoch_ms + MAX_FUTURE_SKEW_MS
        and expires_at > now_epoch_ms
        and expires_at > issued_at
        and expires_at - issued_at <= MAX_LIFETIME_MS
        and authentication["challenge_sha256"] == _review_challenge(response)
    )


def _structurally_complete_pair(
    responses: list[dict], request: dict, now_epoch_ms: int
) -> bool:
    if (
        request.get("review_responses_present") is not False
        or request.get("crypto_call_allowed") is not False
        or request.get("runtime_integration_allowed") is not False
        or request.get("reviewer_must_not_be_generator") is not True
        or len(responses) != request["minimum_reviewers"]
    ):
        return False
    request_digest = _sha256(REQUEST_PATH)
    if not all(
        _is_response_shape_valid(item, request, request_digest, now_epoch_ms)
        for item in responses
    ):
        return False
    required = set(request["required_checks"])
    if len({item.get("reviewer_id") for item in responses}) != len(responses):
        return False
    if any(
        item["reviewer_id"] in request.get("generator_reviewer_ids", [])
        for item in responses
    ):
        return False
    if len({item.get("trust_domain") for item in responses}) != len(responses):
        return False
    if len({item.get("authentication", {}).get("evidence_id") for item in responses}) != len(responses):
        return False
    if len(
        {item.get("authentication", {}).get("credential_root_sha256") for item in responses}
    ) != len(responses):
        return False
    if len(
        {item.get("authentication", {}).get("recovery_authority_id") for item in responses}
    ) != len(responses):
        return False
    for item in responses:
        if item.get("request_sha256") != request_digest:
            return False
        if item.get("reviewer_role") != "non_generator_reviewer":
            return False
        if set(item.get("checks", {})) != required:
            return False
        authentication = item.get("authentication", {})
        if authentication["challenge_sha256"] != _review_challenge(item):
            return False
    if len(
        {item["authentication"]["assertion_envelope_sha256"] for item in responses}
    ) != len(responses):
        return False
    return True


def _synthetic_response(reviewer: str, domain: str, request: dict) -> dict:
    response = {
        "schema": "native-wallet-ed25519-corpus-review-response.v1",
        "request_sha256": _sha256(REQUEST_PATH),
        "reviewer_id": reviewer,
        "trust_domain": domain,
        "reviewer_role": "non_generator_reviewer",
        "reviewed_at": "2026-08-12T00:00:00Z",
        "checks": {check: True for check in request["required_checks"]},
        "decision": "APPROVE",
        "authentication": {
            "profile": "WEBAUTHN_L3_CTAP22_ROAMING_ES256_UV",
            "evidence_id": f"evidence-{reviewer}",
            "challenge_sha256": "0" * 64,
            "credential_root_sha256": "1" * 64 if reviewer.endswith("a") else "2" * 64,
            "recovery_authority_id": f"recovery-{reviewer}",
            "revocation_epoch": 7,
            "issued_at_epoch_ms": 1_786_500_000_000,
            "expires_at_epoch_ms": 1_786_500_600_000,
            "assertion_envelope_sha256": "3" * 64 if reviewer.endswith("a") else "4" * 64,
        },
    }
    response["authentication"]["challenge_sha256"] = _review_challenge(response)
    return response


def test_review_request_binds_every_input_and_grants_nothing():
    request = _load(REQUEST_PATH)
    assert request["schema"] == "native-wallet-ed25519-corpus-review-request.v1"
    assert _sha256(FIXTURES / request["corpus"]["path"]) == request["corpus"]["sha256"]
    assert _sha256(FIXTURES / request["provenance"]["path"]) == request["provenance"]["sha256"]
    assert _sha256(ROOT / request["decision_record"]["path"]) == request["decision_record"]["sha256"]
    assert _sha256(FIXTURES / request["authentication_contract"]["path"]) == request[
        "authentication_contract"
    ]["sha256"]
    assert request["minimum_reviewers"] == 2
    assert request["generator_reviewer_ids"] == ["offline_generator"]
    assert request["reviewer_must_not_be_generator"] is True
    assert request["review_responses_present"] is False
    assert request["crypto_call_allowed"] is False
    assert request["runtime_integration_allowed"] is False


def test_response_schema_is_closed_and_requires_every_check():
    schema = _load(SCHEMA_PATH)
    assert schema["additionalProperties"] is False
    checks = schema["properties"]["checks"]
    assert checks["additionalProperties"] is False
    assert set(checks["required"]) == set(_load(REQUEST_PATH)["required_checks"])
    assert all(rule == {"const": True} for rule in checks["properties"].values())
    assert schema["properties"]["request_sha256"]["pattern"] == "^[0-9a-f]{64}$"


def test_webauthn_profile_binds_exact_context_without_enabling_verification():
    auth = _load(AUTH_PATH)
    assert auth["profile"] == "WEBAUTHN_L3_CTAP22_ROAMING_ES256_UV"
    assert auth["ordered_fields"] == [
        "request_sha256_raw_32_bytes",
        "reviewer_id",
        "trust_domain",
        "reviewed_at",
        "evidence_id",
        "credential_root_sha256_raw_32_bytes",
        "recovery_authority_id",
        "revocation_epoch",
        "issued_at_epoch_ms",
        "expires_at_epoch_ms",
        "assertion_envelope_sha256_raw_32_bytes",
    ]
    assert auth["maximum_lifetime_ms"] == 600_000
    assert auth["user_present_required"] is True
    assert auth["user_verified_required"] is True
    assert auth["backup_eligible_allowed"] is False
    assert auth["backup_state_allowed"] is False
    assert auth["verifier_implemented"] is False
    assert auth["credential_enrolled"] is False
    assert auth["reviewer_authenticated"] is False
    assert auth["crypto_call_allowed"] is False

    request = _load(REQUEST_PATH)
    response = _synthetic_response("reviewer-a", "independent_security", request)
    exact = response["authentication"]["challenge_sha256"]
    assert exact == "81aa5639fadd2fb33bb3e5e3c96b2ddc1394820bf15893d459a96b83e4a70904"
    for field, replacement in [
        ("reviewer_id", "reviewer-z"),
        ("trust_domain", "standards_and_licensing"),
        ("request_sha256", "f" * 64),
    ]:
        drifted = deepcopy(response)
        drifted[field] = replacement
        assert _review_challenge(drifted) != exact
    drifted_review_time = deepcopy(response)
    drifted_review_time["reviewed_at"] = "2026-08-12T00:00:01Z"
    assert _review_challenge(drifted_review_time) != exact
    for field in [
        "evidence_id",
        "recovery_authority_id",
        "revocation_epoch",
        "issued_at_epoch_ms",
        "expires_at_epoch_ms",
    ]:
        drifted = deepcopy(response)
        value = drifted["authentication"][field]
        drifted["authentication"][field] = value + 1 if isinstance(value, int) else f"{value}x"
        assert _review_challenge(drifted) != exact
    drifted_root = deepcopy(response)
    drifted_root["authentication"]["credential_root_sha256"] = "e" * 64
    assert _review_challenge(drifted_root) != exact
    drifted_assertion = deepcopy(response)
    drifted_assertion["authentication"]["assertion_envelope_sha256"] = "e" * 64
    assert _review_challenge(drifted_assertion) != exact


def test_pair_gate_rejects_shared_identity_domain_drift_and_rejection():
    request = _load(REQUEST_PATH)
    first = _synthetic_response("reviewer-a", "independent_security", request)
    second = _synthetic_response("reviewer-b", "standards_and_licensing", request)
    now = first["authentication"]["issued_at_epoch_ms"]
    assert _structurally_complete_pair([first, second], request, now)

    cases = []
    same_id = deepcopy(second)
    same_id["reviewer_id"] = first["reviewer_id"]
    cases.append(same_id)
    same_domain = deepcopy(second)
    same_domain["trust_domain"] = first["trust_domain"]
    cases.append(same_domain)
    same_evidence = deepcopy(second)
    same_evidence["authentication"]["evidence_id"] = first["authentication"]["evidence_id"]
    same_evidence["authentication"]["challenge_sha256"] = _review_challenge(same_evidence)
    cases.append(same_evidence)
    same_root = deepcopy(second)
    same_root["authentication"]["credential_root_sha256"] = first["authentication"][
        "credential_root_sha256"
    ]
    same_root["authentication"]["challenge_sha256"] = _review_challenge(same_root)
    cases.append(same_root)
    same_recovery = deepcopy(second)
    same_recovery["authentication"]["recovery_authority_id"] = first["authentication"][
        "recovery_authority_id"
    ]
    same_recovery["authentication"]["challenge_sha256"] = _review_challenge(same_recovery)
    cases.append(same_recovery)
    drifted = deepcopy(second)
    drifted["request_sha256"] = "0" * 64
    cases.append(drifted)
    unchecked = deepcopy(second)
    unchecked["checks"]["license_treatment_reviewed"] = False
    cases.append(unchecked)
    rejected = deepcopy(second)
    rejected["decision"] = "REJECT"
    cases.append(rejected)
    generator = deepcopy(second)
    generator["reviewer_id"] = request["generator_reviewer_ids"][0]
    generator["authentication"]["challenge_sha256"] = _review_challenge(generator)
    cases.append(generator)
    assertion = deepcopy(second)
    assertion["authentication"]["assertion_envelope_sha256"] = first["authentication"][
        "assertion_envelope_sha256"
    ]
    assertion["authentication"]["challenge_sha256"] = _review_challenge(assertion)
    cases.append(assertion)

    for invalid_second in cases:
        assert not _structurally_complete_pair([first, invalid_second], request, now)


def test_pair_gate_rejects_expired_future_and_shape_drift():
    request = _load(REQUEST_PATH)
    first = _synthetic_response("reviewer-a", "independent_security", request)
    second = _synthetic_response("reviewer-b", "standards_and_licensing", request)
    issued_at = first["authentication"]["issued_at_epoch_ms"]
    expires_at = first["authentication"]["expires_at_epoch_ms"]
    assert not _structurally_complete_pair([first, second], request, expires_at)
    assert not _structurally_complete_pair(
        [first, second], request, issued_at - MAX_FUTURE_SKEW_MS - 1
    )

    malformed = deepcopy(second)
    malformed["unexpected"] = True
    assert not _structurally_complete_pair([first, malformed], request, issued_at)
    malformed = deepcopy(second)
    malformed["reviewed_at"] = "not-a-date"
    assert not _structurally_complete_pair([first, malformed], request, issued_at)


def test_no_review_response_or_credential_is_checked_in():
    names = {path.name for path in FIXTURES.iterdir()}
    assert not any(name.endswith(".review.json") for name in names)
    request = _load(REQUEST_PATH)
    assert "authentication" not in request
    assert "reviewer_id" not in request
    assert "trust_domain" not in request
