import json
import re
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "native-wallet/rehearsals/attestation-dependencies/automated-minimal/tests/fixtures"
BUNDLE_PATH = FIXTURES / "ed25519-corpus-review-supporting-evidence-bundle-v1.schema.json"
MATRIX_PATH = FIXTURES / "ed25519-corpus-review-conflict-of-control-matrix-v1.json"

BUNDLE_SCHEMA_ID = "native-wallet-ed25519-corpus-review-supporting-evidence-bundle.v1"
MAX_BUNDLE_LIFETIME_MS = 86_400_000
HEX64 = re.compile(r"^[0-9a-f]{64}$")
DOMAIN_ID = re.compile(r"^[a-z0-9][a-z0-9._:-]{7,127}$")
BUNDLE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{7,63}$")
BUNDLE_FIELDS = {
    "schema", "bundle_id", "independence_evidence_sha256", "scorecard_sha256",
    "issuer_challenge_sha256", "subject_review_domain_id", "issued_at_epoch_ms",
    "expires_at_epoch_ms", "artifacts", "completeness", "real_artifacts_embedded",
}
ARTIFACT_FIELDS = {
    "kind", "subject_domain_id", "issuer_domain_id", "sha256",
    "captured_at_epoch_ms", "expires_at_epoch_ms", "contains_personal_data",
}
ARTIFACT_KINDS = (
    "reviewer_control_registry", "credential_enrollment_provenance",
    "credential_revocation_snapshot", "reviewer_recovery_policy",
    "verifier_administration_registry", "verifier_recovery_policy",
    "result_authentication_root_registry", "builder_a_control_registry",
    "builder_b_control_registry", "reproducible_build_report",
    "build_provenance_bundle", "host_failure_domain_registry",
    "evidence_issuer_control_registry", "conflict_of_control_matrix",
)
MATRIX_FIELDS = {
    "schema", "node_roles", "prohibited_relationships", "required_separations",
    "cross_review_required_separations", "allowed_cell_states", "passing_cell_state",
    "conflict_unknown_or_missing_blocks_acceptance", "transitive_control_paths_must_be_evaluated",
    "direct_string_inequality_is_insufficient", "current_matrix_present", "current_decision",
    "selection_allowed", "waiver_allowed", "majority_or_compensating_control_allowed",
}
MATRIX_ROLES = (
    "reviewer", "credential_root", "reviewer_recovery", "verifier_administration",
    "verifier_recovery", "result_authentication_root", "builder_a", "builder_b",
    "host_failure_domain", "evidence_issuer", "evidence_issuer_authentication_root",
    "evidence_issuer_recovery",
)
MATRIX_PROHIBITED_RELATIONSHIPS = (
    "SAME_CONTROLLER", "CAN_ACTIVATE", "CAN_RECOVER", "CAN_REVOKE",
    "CAN_MODIFY_POLICY", "CAN_MODIFY_BUILD_INPUTS", "CAN_REPLACE_RUNTIME",
    "CAN_ISSUE_EVIDENCE_FOR_SELF", "SHARED_CREDENTIAL_ROOT", "SHARED_RECOVERY_ROOT",
    "SHARED_HOST_FAILURE_DOMAIN", "UNDISCLOSED_DELEGATION",
)
MATRIX_REQUIRED_SEPARATIONS = (
    ("reviewer", "evidence_issuer"),
    ("credential_root", "evidence_issuer_authentication_root"),
    ("reviewer_recovery", "evidence_issuer_recovery"),
    ("verifier_administration", "evidence_issuer"),
    ("verifier_recovery", "evidence_issuer_recovery"),
    ("result_authentication_root", "evidence_issuer_authentication_root"),
    ("builder_a", "builder_b"),
    ("builder_a", "evidence_issuer"),
    ("builder_b", "evidence_issuer"),
    ("host_failure_domain", "evidence_issuer"),
)
MATRIX_ALLOWED_STATES = ("SEPARATE_WITH_EVIDENCE", "CONFLICT", "UNKNOWN", "MISSING")


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _is_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _matches(pattern: re.Pattern[str], value: object) -> bool:
    return isinstance(value, str) and pattern.fullmatch(value) is not None


def _bundle_is_acceptable(
    bundle: dict,
    *,
    now_epoch_ms: int,
    expected_bindings: dict[str, str] | None = None,
) -> bool:
    if set(bundle) != BUNDLE_FIELDS:
        return False
    if bundle["schema"] != BUNDLE_SCHEMA_ID or not _matches(BUNDLE_ID, bundle["bundle_id"]):
        return False
    if any(not _matches(HEX64, bundle[field]) for field in [
        "independence_evidence_sha256", "scorecard_sha256", "issuer_challenge_sha256",
    ]):
        return False
    if expected_bindings is not None and any(
        bundle[field] != expected_bindings.get(field)
        for field in [
            "independence_evidence_sha256", "scorecard_sha256", "issuer_challenge_sha256",
            "subject_review_domain_id",
        ]
    ):
        return False
    if not _matches(DOMAIN_ID, bundle["subject_review_domain_id"]):
        return False
    if not all(_is_integer(bundle[field]) for field in ["issued_at_epoch_ms", "expires_at_epoch_ms"]):
        return False
    if bundle["issued_at_epoch_ms"] > now_epoch_ms:
        return False
    if bundle["expires_at_epoch_ms"] <= now_epoch_ms:
        return False
    if (
        bundle["expires_at_epoch_ms"] <= bundle["issued_at_epoch_ms"]
        or bundle["expires_at_epoch_ms"] - bundle["issued_at_epoch_ms"] > MAX_BUNDLE_LIFETIME_MS
    ):
        return False
    if bundle["completeness"] != "COMPLETE" or bundle["real_artifacts_embedded"] is not False:
        return False
    artifacts = bundle["artifacts"]
    if not isinstance(artifacts, list) or len(artifacts) != len(ARTIFACT_KINDS):
        return False
    if {item.get("kind") for item in artifacts} != set(ARTIFACT_KINDS):
        return False
    for artifact in artifacts:
        if set(artifact) != ARTIFACT_FIELDS:
            return False
        if not _matches(DOMAIN_ID, artifact["subject_domain_id"]):
            return False
        if not _matches(DOMAIN_ID, artifact["issuer_domain_id"]):
            return False
        if not _matches(HEX64, artifact["sha256"]):
            return False
        if not all(_is_integer(artifact[field]) for field in [
            "captured_at_epoch_ms", "expires_at_epoch_ms",
        ]):
            return False
        if artifact["captured_at_epoch_ms"] > bundle["issued_at_epoch_ms"]:
            return False
        if artifact["expires_at_epoch_ms"] < bundle["expires_at_epoch_ms"]:
            return False
        if artifact["contains_personal_data"] is not False:
            return False
    return True


def _bundle_is_complete(artifacts: list[dict], required: set[str], bundle_expiry: int) -> bool:
    kinds = [item.get("kind") for item in artifacts]
    return (
        len(kinds) == len(required)
        and set(kinds) == required
        and len(set(kinds)) == len(kinds)
        and all(item.get("expires_at_epoch_ms", 0) >= bundle_expiry for item in artifacts)
        and all(item.get("contains_personal_data") is False for item in artifacts)
    )


def _matrix_passes(cells: dict[tuple[str, str], str], required_pairs: list[list[str]]) -> bool:
    normalized = [tuple(pair) for pair in required_pairs]
    if len(set(normalized)) != len(normalized) or set(cells) != set(normalized):
        return False
    return all(cells[pair] == "SEPARATE_WITH_EVIDENCE" for pair in normalized)


def _matrix_contract_is_closed(matrix: dict) -> bool:
    if set(matrix) != MATRIX_FIELDS:
        return False
    if matrix["schema"] != "native-wallet-ed25519-corpus-review-conflict-of-control-matrix.v1":
        return False
    if tuple(matrix["node_roles"]) != MATRIX_ROLES:
        return False
    if tuple(matrix["prohibited_relationships"]) != MATRIX_PROHIBITED_RELATIONSHIPS:
        return False
    if tuple(tuple(pair) for pair in matrix["required_separations"]) != MATRIX_REQUIRED_SEPARATIONS:
        return False
    if set(matrix["cross_review_required_separations"]) != {
        "reviewer", "credential_root", "reviewer_recovery", "verifier_administration",
        "verifier_recovery", "result_authentication_root", "host_failure_domain",
        "evidence_issuer", "evidence_issuer_authentication_root", "evidence_issuer_recovery",
    }:
        return False
    if tuple(matrix["allowed_cell_states"]) != MATRIX_ALLOWED_STATES:
        return False
    return (
        matrix["passing_cell_state"] == "SEPARATE_WITH_EVIDENCE"
        and matrix["conflict_unknown_or_missing_blocks_acceptance"] is True
        and matrix["transitive_control_paths_must_be_evaluated"] is True
        and matrix["direct_string_inequality_is_insufficient"] is True
        and matrix["current_matrix_present"] is False
        and matrix["current_decision"] == "BLOCKED"
        and matrix["selection_allowed"] is False
        and matrix["waiver_allowed"] is False
        and matrix["majority_or_compensating_control_allowed"] is False
    )


def _synthetic_bundle() -> dict:
    issued = 2_000
    expiry = issued + MAX_BUNDLE_LIFETIME_MS
    return {
        "schema": BUNDLE_SCHEMA_ID,
        "bundle_id": "bundle-20260822-a",
        "independence_evidence_sha256": "1" * 64,
        "scorecard_sha256": "2" * 64,
        "issuer_challenge_sha256": "3" * 64,
        "subject_review_domain_id": "review-domain-a",
        "issued_at_epoch_ms": issued,
        "expires_at_epoch_ms": expiry,
        "artifacts": [
            {
                "kind": kind,
                "subject_domain_id": "review-domain-a",
                "issuer_domain_id": "issuer-domain-a",
                "sha256": f"{index + 4:064x}",
                "captured_at_epoch_ms": issued,
                "expires_at_epoch_ms": expiry,
                "contains_personal_data": False,
            }
            for index, kind in enumerate(ARTIFACT_KINDS)
        ],
        "completeness": "COMPLETE",
        "real_artifacts_embedded": False,
    }


def test_bundle_schema_is_closed_hash_only_and_exactly_complete():
    schema = _load(BUNDLE_PATH)
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])
    artifacts = schema["properties"]["artifacts"]
    assert artifacts["minItems"] == artifacts["maxItems"] == 14
    assert artifacts["items"]["additionalProperties"] is False
    assert artifacts["items"]["properties"]["contains_personal_data"] == {"const": False}
    assert schema["artifact_bytes_external_and_digest_referenced"] is True
    assert schema["properties"]["real_artifacts_embedded"]["const"] is False
    assert schema["completeness_complete_required_for_acceptance"] is True
    assert schema["bundle_lifetime_requires_issued_before_expiry"] is True
    assert schema["artifact_capture_must_not_exceed_bundle_issue"] is True
    assert schema["artifact_metadata_canonical_and_closed"] is True


def test_bundle_binds_top_level_digests_and_all_artifact_metadata():
    bundle = _synthetic_bundle()
    expected = {
        field: bundle[field]
        for field in [
            "independence_evidence_sha256", "scorecard_sha256", "issuer_challenge_sha256",
            "subject_review_domain_id",
        ]
    }
    assert _bundle_is_acceptable(bundle, now_epoch_ms=2_000, expected_bindings=expected)
    for field, value in [
        ("independence_evidence_sha256", "0" * 64),
        ("scorecard_sha256", "not-a-digest"),
        ("issuer_challenge_sha256", "4" * 64),
        ("subject_review_domain_id", "bad"),
    ]:
        changed = deepcopy(bundle)
        changed[field] = value
        assert not _bundle_is_acceptable(changed, now_epoch_ms=2_000, expected_bindings=expected)
    changed = deepcopy(bundle)
    changed["artifacts"][0]["issuer_domain_id"] = "bad"
    assert not _bundle_is_acceptable(changed, now_epoch_ms=2_000)
    changed = deepcopy(bundle)
    changed["artifacts"][0]["sha256"] = "A" * 64
    assert not _bundle_is_acceptable(changed, now_epoch_ms=2_000)


def test_bundle_lifetime_completeness_and_expiry_coverage_fail_closed():
    bundle = _synthetic_bundle()
    for mutation in [
        lambda value: value.update(completeness="UNKNOWN"),
        lambda value: value.update(expires_at_epoch_ms=value["issued_at_epoch_ms"]),
        lambda value: value.update(expires_at_epoch_ms=value["issued_at_epoch_ms"] + MAX_BUNDLE_LIFETIME_MS + 1),
        lambda value: value.update(issued_at_epoch_ms=2_001),
        lambda value: value["artifacts"][0].update(expires_at_epoch_ms=value["expires_at_epoch_ms"] - 1),
        lambda value: value["artifacts"][0].update(captured_at_epoch_ms=value["issued_at_epoch_ms"] + 1),
        lambda value: value["artifacts"][0].update(contains_personal_data=True),
        lambda value: value.update(extra="closed-shape-drift"),
    ]:
        changed = deepcopy(bundle)
        mutation(changed)
        assert not _bundle_is_acceptable(changed, now_epoch_ms=2_000)


def test_duplicate_missing_expired_or_personal_artifact_blocks_bundle():
    schema = _load(BUNDLE_PATH)
    required = set(schema["properties"]["artifacts"]["items"]["properties"]["kind"]["enum"])
    expiry = 2_000
    artifacts = [
        {"kind": kind, "expires_at_epoch_ms": expiry, "contains_personal_data": False}
        for kind in sorted(required)
    ]
    assert _bundle_is_complete(artifacts, required, expiry)
    assert not _bundle_is_complete(artifacts[:-1], required, expiry)
    duplicate = deepcopy(artifacts)
    duplicate[-1]["kind"] = duplicate[0]["kind"]
    assert not _bundle_is_complete(duplicate, required, expiry)
    expired = deepcopy(artifacts)
    expired[0]["expires_at_epoch_ms"] = expiry - 1
    assert not _bundle_is_complete(expired, required, expiry)
    personal = deepcopy(artifacts)
    personal[0]["contains_personal_data"] = True
    assert not _bundle_is_complete(personal, required, expiry)


def test_matrix_covers_direct_transitive_recovery_runtime_and_self_issuance():
    matrix = _load(MATRIX_PATH)
    assert _matrix_contract_is_closed(matrix)
    relationships = set(matrix["prohibited_relationships"])
    assert relationships == set(MATRIX_PROHIBITED_RELATIONSHIPS)
    assert matrix["transitive_control_paths_must_be_evaluated"] is True
    assert matrix["direct_string_inequality_is_insufficient"] is True


def test_only_evidence_backed_separation_passes_every_required_pair():
    matrix = _load(MATRIX_PATH)
    pairs = matrix["required_separations"]
    cells = {tuple(pair): "SEPARATE_WITH_EVIDENCE" for pair in pairs}
    assert _matrix_passes(cells, pairs)
    for blocked in ["CONFLICT", "UNKNOWN", "MISSING"]:
        changed = deepcopy(cells)
        changed[tuple(pairs[0])] = blocked
        assert not _matrix_passes(changed, pairs)
    absent = deepcopy(cells)
    absent.pop(tuple(pairs[-1]))
    assert not _matrix_passes(absent, pairs)
    extra = deepcopy(cells)
    extra[("reviewer", "builder_a")] = "SEPARATE_WITH_EVIDENCE"
    assert not _matrix_passes(extra, pairs)
    invalid = deepcopy(cells)
    invalid[tuple(pairs[0])] = "NOT_A_MATRIX_STATE"
    assert not _matrix_passes(invalid, pairs)
    duplicated_pairs = pairs + [pairs[0]]
    assert not _matrix_passes(cells, duplicated_pairs)


def test_cross_review_separation_includes_every_high_value_control_root():
    matrix = _load(MATRIX_PATH)
    assert set(matrix["cross_review_required_separations"]) == {
        "reviewer", "credential_root", "reviewer_recovery", "verifier_administration",
        "verifier_recovery", "result_authentication_root", "host_failure_domain",
        "evidence_issuer", "evidence_issuer_authentication_root", "evidence_issuer_recovery",
    }


def test_current_contract_has_no_real_evidence_and_grants_nothing():
    bundle = _load(BUNDLE_PATH)
    matrix = _load(MATRIX_PATH)
    assert bundle["bundle_accepted"] is False
    assert bundle["selection_allowed"] is False
    assert matrix["current_matrix_present"] is False
    assert matrix["current_decision"] == "BLOCKED"
    assert matrix["selection_allowed"] is False
    assert matrix["waiver_allowed"] is False
    assert matrix["majority_or_compensating_control_allowed"] is False
    for path in [BUNDLE_PATH, MATRIX_PATH]:
        text = path.read_text(encoding="utf-8")
        for forbidden in ["private_key", "secret_key", "BEGIN PRIVATE", "credential_public_key"]:
            assert forbidden not in text
