import hashlib
import json
import re
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "native-wallet/rehearsals/attestation-dependencies/automated-minimal/tests/fixtures"
AUTH_PATH = FIXTURES / "ed25519-corpus-review-independence-issuer-auth-v1.json"
VECTOR_PATH = FIXTURES / "ed25519-corpus-review-independence-issuer-challenge-v1.json"
EVIDENCE_SCHEMA_PATH = FIXTURES / "ed25519-corpus-review-independence-evidence-v1.schema.json"

DOMAIN_SEPARATOR = "obsidian.ed25519-review.independence-issuer-auth.v1"
MAX_ISSUER_AUTH_LIFETIME_MS = 600_000
MAX_EVIDENCE_LIFETIME_MS = 86_400_000
MAX_FUTURE_SKEW_MS = 1_000
HEX64 = re.compile(r"^[0-9a-f]{64}$")
IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,127}$")
CHALLENGE_INPUT_FIELDS = (
    "independence_schema_sha256",
    "scorecard_sha256",
    "evidence_record_sha256",
    "issuer_id",
    "issuer_trust_domain",
    "authentication_root_sha256",
    "recovery_authority_id",
    "revocation_epoch",
    "caller_nonce_sha256",
    "issued_at_epoch_ms",
    "expires_at_epoch_ms",
)
CHALLENGE_ORDERED_FIELDS = (
    "independence_schema_sha256_raw_32_bytes",
    "scorecard_sha256_raw_32_bytes",
    "evidence_record_sha256_raw_32_bytes",
    "issuer_id",
    "issuer_trust_domain",
    "authentication_root_sha256_raw_32_bytes",
    "recovery_authority_id",
    "revocation_epoch",
    "caller_nonce_sha256_raw_32_bytes",
    "issued_at_epoch_ms",
    "expires_at_epoch_ms",
)
EVIDENCE_REQUIRED_FIELDS = {
    "schema", "reviewer_id", "reviewer_trust_domain", "credential_root_sha256",
    "recovery_authority_id", "verifier_administration_root_sha256",
    "verifier_recovery_authority_id", "builder_a_root_sha256", "builder_b_root_sha256",
    "result_authentication_root_sha256", "host_failure_domain_id", "evidence_issuer_id",
    "issued_at_epoch_ms", "expires_at_epoch_ms", "supporting_evidence_sha256", "decision",
}
PAIRWISE_DISTINCT_FIELDS = (
    "reviewer_id", "reviewer_trust_domain", "credential_root_sha256",
    "recovery_authority_id", "verifier_administration_root_sha256",
    "verifier_recovery_authority_id", "result_authentication_root_sha256",
    "host_failure_domain_id", "evidence_issuer_id",
)
DISTINCT_WITHIN_RECORD = (
    ("credential_root_sha256", "verifier_administration_root_sha256", "result_authentication_root_sha256"),
    ("recovery_authority_id", "verifier_recovery_authority_id"),
    ("builder_a_root_sha256", "builder_b_root_sha256"),
)


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _field(value: str) -> bytes:
    encoded = value.encode("utf-8")
    if not encoded or len(encoded) > 65535:
        raise ValueError("bounded non-empty UTF-8 required")
    return len(encoded).to_bytes(2, "big") + encoded


def _digest(value: str) -> bytes:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError("canonical SHA-256 required")
    return bytes.fromhex(value)


def _is_digest(value: object) -> bool:
    return isinstance(value, str) and HEX64.fullmatch(value) is not None


def _is_identifier(value: object, minimum_length: int = 1) -> bool:
    return (
        isinstance(value, str)
        and minimum_length <= len(value) <= 128
        and IDENTIFIER.fullmatch(value) is not None
    )


def _challenge(inputs: dict) -> str:
    parts = [
        _field("obsidian.ed25519-review.independence-issuer-auth.v1"),
        _digest(inputs["independence_schema_sha256"]),
        _digest(inputs["scorecard_sha256"]),
        _digest(inputs["evidence_record_sha256"]),
        _field(inputs["issuer_id"]),
        _field(inputs["issuer_trust_domain"]),
        _digest(inputs["authentication_root_sha256"]),
        _field(inputs["recovery_authority_id"]),
        inputs["revocation_epoch"].to_bytes(8, "big"),
        _digest(inputs["caller_nonce_sha256"]),
        inputs["issued_at_epoch_ms"].to_bytes(8, "big"),
        inputs["expires_at_epoch_ms"].to_bytes(8, "big"),
    ]
    return hashlib.sha256(b"".join(parts)).hexdigest()


def _issuer_context_is_valid(
    inputs: dict,
    *,
    now_epoch_ms: int,
    minimum_revocation_epoch: int,
    consumer_selected_root_sha256: str,
    consumed_caller_nonce_sha256: set[str],
) -> bool:
    if set(inputs) != set(CHALLENGE_INPUT_FIELDS):
        return False
    if any(not _is_digest(inputs[field]) for field in [
        "independence_schema_sha256", "scorecard_sha256", "evidence_record_sha256",
        "authentication_root_sha256", "caller_nonce_sha256",
    ]):
        return False
    if any(not _is_identifier(inputs[field]) for field in [
        "issuer_id", "issuer_trust_domain", "recovery_authority_id",
    ]):
        return False
    if any(
        isinstance(inputs[field], bool)
        or not isinstance(inputs[field], int)
        or inputs[field] < 1
        for field in ["revocation_epoch", "issued_at_epoch_ms", "expires_at_epoch_ms"]
    ):
        return False
    if inputs["authentication_root_sha256"] != consumer_selected_root_sha256:
        return False
    if inputs["revocation_epoch"] < minimum_revocation_epoch:
        return False
    if inputs["caller_nonce_sha256"] in consumed_caller_nonce_sha256:
        return False
    if inputs["issued_at_epoch_ms"] > now_epoch_ms + MAX_FUTURE_SKEW_MS:
        return False
    if inputs["expires_at_epoch_ms"] <= now_epoch_ms:
        return False
    return (
        inputs["expires_at_epoch_ms"] > inputs["issued_at_epoch_ms"]
        and inputs["expires_at_epoch_ms"] - inputs["issued_at_epoch_ms"]
        <= MAX_ISSUER_AUTH_LIFETIME_MS
    )


def _independence_record_is_valid(record: dict, *, now_epoch_ms: int) -> bool:
    if set(record) != EVIDENCE_REQUIRED_FIELDS:
        return False
    if record["schema"] != "native-wallet-ed25519-corpus-review-independence-evidence.v1":
        return False
    if record["decision"] != "INDEPENDENT":
        return False
    for field in [
        "credential_root_sha256", "verifier_administration_root_sha256",
        "builder_a_root_sha256", "builder_b_root_sha256",
        "result_authentication_root_sha256", "supporting_evidence_sha256",
    ]:
        if not _is_digest(record[field]):
            return False
    for field in [
        "reviewer_id", "reviewer_trust_domain", "recovery_authority_id",
        "verifier_recovery_authority_id", "host_failure_domain_id", "evidence_issuer_id",
    ]:
        minimum = 8 if field in {
            "recovery_authority_id", "verifier_recovery_authority_id",
            "host_failure_domain_id", "evidence_issuer_id",
        } else 1
        if not _is_identifier(record[field], minimum):
            return False
    for field in ["issued_at_epoch_ms", "expires_at_epoch_ms"]:
        if isinstance(record[field], bool) or not isinstance(record[field], int) or record[field] < 1:
            return False
    if record["issued_at_epoch_ms"] > now_epoch_ms + MAX_FUTURE_SKEW_MS:
        return False
    if record["expires_at_epoch_ms"] <= now_epoch_ms:
        return False
    if (
        record["expires_at_epoch_ms"] <= record["issued_at_epoch_ms"]
        or record["expires_at_epoch_ms"] - record["issued_at_epoch_ms"] > MAX_EVIDENCE_LIFETIME_MS
    ):
        return False
    return all(len({record[field] for field in group}) == len(group) for group in DISTINCT_WITHIN_RECORD)


def _pair_is_structurally_independent(
    first: dict,
    second: dict,
    *,
    now_epoch_ms: int,
) -> bool:
    if not _independence_record_is_valid(first, now_epoch_ms=now_epoch_ms):
        return False
    if not _independence_record_is_valid(second, now_epoch_ms=now_epoch_ms):
        return False
    return all(first[field] != second[field] for field in PAIRWISE_DISTINCT_FIELDS)


def _synthetic_record(suffix: str, digest_chars: tuple[str, ...]) -> dict:
    (
        credential_root, verifier_root, builder_a_root, builder_b_root,
        result_root, supporting_evidence,
    ) = (char * 64 for char in digest_chars)
    return {
        "schema": "native-wallet-ed25519-corpus-review-independence-evidence.v1",
        "reviewer_id": f"reviewer-{suffix}",
        "reviewer_trust_domain": f"review-domain-{suffix}",
        "credential_root_sha256": credential_root,
        "recovery_authority_id": f"recovery-{suffix}",
        "verifier_administration_root_sha256": verifier_root,
        "verifier_recovery_authority_id": f"verifier-recovery-{suffix}",
        "builder_a_root_sha256": builder_a_root,
        "builder_b_root_sha256": builder_b_root,
        "result_authentication_root_sha256": result_root,
        "host_failure_domain_id": f"host-failure-{suffix}",
        "evidence_issuer_id": f"evidence-issuer-{suffix}",
        "issued_at_epoch_ms": 1_786_500_000_000,
        "expires_at_epoch_ms": 1_786_586_400_000,
        "supporting_evidence_sha256": supporting_evidence,
        "decision": "INDEPENDENT",
    }


def test_challenge_vector_binds_exact_context():
    vector = _load(VECTOR_PATH)
    exact = _challenge(vector["inputs"])
    assert exact == vector["expected_challenge_sha256"]
    for field, value in vector["inputs"].items():
        changed = deepcopy(vector["inputs"])
        changed[field] = value + 1 if isinstance(value, int) else ("6" * 64 if field.endswith("sha256") else f"{value}x")
        assert _challenge(changed) != exact


def test_challenge_order_is_closed_and_matches_the_auth_contract():
    contract = _load(AUTH_PATH)
    vector = _load(VECTOR_PATH)
    assert contract["domain_separator_utf8"] == DOMAIN_SEPARATOR
    assert tuple(contract["ordered_fields"]) == CHALLENGE_ORDERED_FIELDS
    assert tuple(vector["inputs"]) == CHALLENGE_INPUT_FIELDS


def test_issuer_context_rejects_stale_replay_epoch_and_root_drift():
    vector = _load(VECTOR_PATH)
    inputs = vector["inputs"]
    now = inputs["issued_at_epoch_ms"]
    root = inputs["authentication_root_sha256"]
    assert _issuer_context_is_valid(
        inputs,
        now_epoch_ms=now,
        minimum_revocation_epoch=inputs["revocation_epoch"],
        consumer_selected_root_sha256=root,
        consumed_caller_nonce_sha256=set(),
    )
    replayed = deepcopy(inputs)
    assert not _issuer_context_is_valid(
        replayed,
        now_epoch_ms=now,
        minimum_revocation_epoch=inputs["revocation_epoch"],
        consumer_selected_root_sha256=root,
        consumed_caller_nonce_sha256={inputs["caller_nonce_sha256"]},
    )
    for field, value in [
        ("expires_at_epoch_ms", now),
        ("issued_at_epoch_ms", now + MAX_FUTURE_SKEW_MS + 1),
        ("revocation_epoch", inputs["revocation_epoch"] - 1),
    ]:
        changed = deepcopy(inputs)
        changed[field] = value
        assert not _issuer_context_is_valid(
            changed,
            now_epoch_ms=now,
            minimum_revocation_epoch=inputs["revocation_epoch"],
            consumer_selected_root_sha256=root,
            consumed_caller_nonce_sha256=set(),
        )
    assert not _issuer_context_is_valid(
        inputs,
        now_epoch_ms=now,
        minimum_revocation_epoch=inputs["revocation_epoch"],
        consumer_selected_root_sha256="6" * 64,
        consumed_caller_nonce_sha256=set(),
    )


def test_authentication_shortlist_has_no_selected_option():
    contract = _load(AUTH_PATH)
    options = {item["id"]: item for item in contract["authentication_options"]}
    assert set(options) == {
        "threshold_dsse_offline_roots", "dual_webauthn_human_issuers",
        "hardware_workload_attested_issuer",
    }
    assert options["threshold_dsse_offline_roots"]["status"] == "SHORTLISTED_NOT_SELECTED"
    assert options["dual_webauthn_human_issuers"]["status"] == "SHORTLISTED_NOT_SELECTED"
    assert options["hardware_workload_attested_issuer"]["status"] == "DEFERRED_COMPLEXITY"
    assert contract["selected_authentication_option"] is None


def test_pair_policy_requires_independence_beyond_issuer_name():
    contract = _load(AUTH_PATH)
    policy = contract["pair_policy"]
    assert policy["minimum_authenticated_evidence_issuers"] == 2
    assert policy["issuer_must_not_administer_reviewed_reviewer_verifier_or_builder"] is True
    assert policy["same_mechanism_allowed_only_with_independent_roots"] is True
    now = 1_786_500_000_000
    first = _synthetic_record("a", ("1", "2", "3", "4", "5", "6"))
    second = _synthetic_record("b", ("a", "b", "c", "d", "e", "f"))
    assert _pair_is_structurally_independent(first, second, now_epoch_ms=now)
    for field in PAIRWISE_DISTINCT_FIELDS:
        shared = deepcopy(second)
        shared[field] = first[field]
        assert not _pair_is_structurally_independent(first, shared, now_epoch_ms=now)


def test_pair_policy_rejects_record_reuse_and_malformed_evidence():
    now = 1_786_500_000_000
    first = _synthetic_record("a", ("1", "2", "3", "4", "5", "6"))
    second = _synthetic_record("b", ("a", "b", "c", "d", "e", "f"))
    for group in DISTINCT_WITHIN_RECORD:
        reused = deepcopy(first)
        reused[group[1]] = reused[group[0]]
        assert not _pair_is_structurally_independent(reused, second, now_epoch_ms=now)
    for mutation in [
        lambda record: record.pop("evidence_issuer_id"),
        lambda record: record.update(extra="closed-shape-drift"),
        lambda record: record.update(decision="UNVERIFIED"),
        lambda record: record.update(expires_at_epoch_ms=now),
        lambda record: record.update(issued_at_epoch_ms=now + MAX_FUTURE_SKEW_MS + 1),
    ]:
        malformed = deepcopy(first)
        mutation(malformed)
        assert not _pair_is_structurally_independent(malformed, second, now_epoch_ms=now)


def test_evidence_schema_declares_the_same_closed_pair_boundary():
    schema = _load(EVIDENCE_SCHEMA_PATH)
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == EVIDENCE_REQUIRED_FIELDS
    assert tuple(schema["pairwise_distinct_across_reviews"]) == PAIRWISE_DISTINCT_FIELDS
    assert tuple(tuple(group) for group in schema["distinct_within_each_record"]) == DISTINCT_WITHIN_RECORD
    assert schema["maximum_lifetime_ms"] == MAX_EVIDENCE_LIFETIME_MS


def test_lifetime_nonce_epoch_and_consumer_root_are_mandatory():
    contract = _load(AUTH_PATH)
    assert contract["maximum_lifetime_ms"] == 600_000
    assert contract["single_use_caller_nonce_required"] is True
    assert contract["monotonic_revocation_epoch_required"] is True
    assert contract["consumer_selected_root_required"] is True
    inputs = _load(VECTOR_PATH)["inputs"]
    assert inputs["expires_at_epoch_ms"] - inputs["issued_at_epoch_ms"] == 600_000


def test_current_contract_grants_nothing():
    contract = _load(AUTH_PATH)
    for field in [
        "issuer_enrolled", "real_issuer_assertion_present", "issuer_authenticated",
        "independence_evidence_accepted", "selection_allowed", "crypto_call_allowed",
        "runtime_integration_allowed",
    ]:
        assert contract[field] is False


def test_no_key_assertion_or_real_issuer_evidence_is_present():
    for path in [AUTH_PATH, VECTOR_PATH]:
        text = path.read_text(encoding="utf-8")
        for forbidden in ["private_key", "secret_key", "BEGIN PRIVATE", "credential_public_key"]:
            assert forbidden not in text
