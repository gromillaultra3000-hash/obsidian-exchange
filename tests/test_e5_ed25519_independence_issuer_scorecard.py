import hashlib
import json
import re
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "native-wallet/rehearsals/attestation-dependencies/automated-minimal/tests/fixtures"
SCORECARD_PATH = FIXTURES / "ed25519-corpus-review-independence-issuer-selection-scorecard-v1.json"
BUNDLE_PATH = FIXTURES / "ed25519-corpus-review-supporting-evidence-bundle-v1.schema.json"
MATRIX_PATH = FIXTURES / "ed25519-corpus-review-conflict-of-control-matrix-v1.json"
ISSUER_AUTH_PATH = FIXTURES / "ed25519-corpus-review-independence-issuer-auth-v1.json"
INDEPENDENCE_EVIDENCE_PATH = FIXTURES / "ed25519-corpus-review-independence-evidence-v1.schema.json"
DECISION_RESULT_SCHEMA_PATH = FIXTURES / "ed25519-corpus-review-independence-issuer-selection-decision-result-v1.schema.json"

HEX64 = re.compile(r"^[0-9a-f]{64}$")
DOMAIN_ID = re.compile(r"^[a-z0-9][a-z0-9._:-]{7,127}$")
COMMON_GATE_IDS = {
    "i01_exact_challenge", "i02_complete_bundle", "i03_conflict_matrix",
    "i04_two_issuer_independence", "i05_subject_non_control", "i06_freshness_replay",
    "i07_root_recovery", "i08_parser_corpus", "i09_audit_privacy_retention",
    "i10_dependency_incident",
}
THRESHOLD_GATE_IDS = {
    "t01_threshold_policy", "t02_role_separation", "t03_dsse_exact_bytes",
    "t04_offline_root_ceremony",
}
WEBAUTHN_GATE_IDS = {
    "w01_enrollment_provenance", "w02_exact_rp_origin", "w03_profile_flags",
    "w04_human_collusion_controls",
}
HANDOFF_FIELDS = {
    "selection_scorecard_sha256", "independence_evidence_sha256",
    "supporting_bundle_sha256", "conflict_matrix_sha256", "issuer_challenge_sha256",
    "subject_review_domain_id",
}
SCORECARD_FIELDS = {
    "schema", "decision_rule", "allowed_gate_states", "current_gate_state",
    "common_mandatory_gates", "option_specific_gates", "non_selection_reasons",
    "tie_rule", "handoff_contract", "selection_decision_contract", "selected_option", "all_common_gates_pass",
    "any_option_specific_gates_pass", "selection_allowed", "real_evidence_present",
    "issuer_authenticated", "crypto_call_allowed", "runtime_integration_allowed",
    "decision_result_envelope_schema", "owner_reviewer_handoff_schema",
}
OPTION_IDS = {"threshold_dsse_offline_roots", "dual_webauthn_human_issuers"}
DECISION_OUTCOMES = {
    "NOT_EVALUATED",
    "REVIEW_REQUIRED_SINGLE_CANDIDATE",
    "TIE_REQUIRES_SEPARATE_ADR",
    "BLOCKED_INVALID_STATE",
}
DECISION_RESULT_FIELDS = {
    "schema", "decision_id", "outcome", "candidate_option_id", "selected_option",
    "selection_scorecard_sha256", "context_handoff_sha256", "independence_evidence_sha256",
    "supporting_bundle_sha256", "conflict_matrix_sha256", "issuer_challenge_sha256",
    "subject_review_domain_id", "issued_at_epoch_ms", "expires_at_epoch_ms",
    "caller_nonce_sha256", "result_sha256",
}
DECISION_RESULT_HASH_FIELDS = {
    "selection_scorecard_sha256", "context_handoff_sha256", "independence_evidence_sha256",
    "supporting_bundle_sha256", "conflict_matrix_sha256", "issuer_challenge_sha256",
    "caller_nonce_sha256", "result_sha256",
}
MAX_DECISION_RESULT_LIFETIME_MS = 600_000
MAX_FUTURE_SKEW_MS = 1_000


def _load(path: Path = SCORECARD_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _is_digest(value: object) -> bool:
    return isinstance(value, str) and HEX64.fullmatch(value) is not None


def _is_handoff_bound(handoff: dict, expected: dict[str, str]) -> bool:
    if set(handoff) != HANDOFF_FIELDS:
        return False
    if any(not _is_digest(handoff[field]) for field in HANDOFF_FIELDS - {"subject_review_domain_id"}):
        return False
    if not isinstance(handoff["subject_review_domain_id"], str) or not DOMAIN_ID.fullmatch(
        handoff["subject_review_domain_id"]
    ):
        return False
    return all(handoff[field] == expected.get(field) for field in HANDOFF_FIELDS)


def _passes(
    common: dict[str, str],
    specific: dict[str, str],
    evidence: dict[str, list[str]],
    *,
    required_common: set[str],
    required_specific: set[str],
    minimum_evidence_counts: dict[str, int],
) -> bool:
    if set(common) != required_common or set(specific) != required_specific:
        return False
    gates = common | specific
    if set(evidence) != set(gates):
        return False
    return bool(gates) and all(
        state == "PASS"
        and isinstance(evidence[gate_id], list)
        and len(evidence[gate_id]) >= minimum_evidence_counts[gate_id]
        and all(_is_digest(reference) for reference in evidence[gate_id])
        for gate_id, state in gates.items()
    )


def _scorecard_is_closed(scorecard: dict) -> bool:
    if set(scorecard) != SCORECARD_FIELDS:
        return False
    if scorecard["schema"] != "native-wallet-ed25519-corpus-review-independence-issuer-selection-scorecard.v1":
        return False
    if scorecard["decision_result_envelope_schema"] != "native-wallet-ed25519-corpus-review-independence-issuer-selection-decision-result.v1":
        return False
    if scorecard["owner_reviewer_handoff_schema"] != "native-wallet-ed25519-corpus-review-independence-owner-reviewer-handoff.v1":
        return False
    if "all common and option-specific mandatory gates" not in scorecard["decision_rule"]:
        return False
    if "no automatic winner" not in scorecard["tie_rule"]:
        return False
    if scorecard["allowed_gate_states"] != ["PASS", "FAIL", "UNKNOWN", "NOT_EVALUATED"]:
        return False
    common = scorecard["common_mandatory_gates"]
    options = scorecard["option_specific_gates"]
    if {gate["id"] for gate in common} != COMMON_GATE_IDS:
        return False
    if set(options) != {"threshold_dsse_offline_roots", "dual_webauthn_human_issuers"}:
        return False
    if {gate["id"] for gate in options["threshold_dsse_offline_roots"]} != THRESHOLD_GATE_IDS:
        return False
    if {gate["id"] for gate in options["dual_webauthn_human_issuers"]} != WEBAUTHN_GATE_IDS:
        return False
    all_gates = common + options["threshold_dsse_offline_roots"] + options["dual_webauthn_human_issuers"]
    if any(set(gate) != {"id", "requirement", "minimum_evidence"} for gate in all_gates):
        return False
    if any(not gate["requirement"] or not gate["minimum_evidence"] for gate in all_gates):
        return False
    if set(scorecard["non_selection_reasons"]) != {
        "threshold_dsse_offline_roots", "dual_webauthn_human_issuers",
    }:
        return False
    contract = scorecard["handoff_contract"]
    handoff_closed = (
        set(contract)
        == {
            "required_fields", "canonical_digest_fields", "closed",
            "exact_context_required", "no_implicit_current_state",
        }
        and contract["required_fields"] == [
            "selection_scorecard_sha256", "independence_evidence_sha256",
            "supporting_bundle_sha256", "conflict_matrix_sha256",
            "issuer_challenge_sha256", "subject_review_domain_id",
        ]
        and contract["canonical_digest_fields"] == [
            "selection_scorecard_sha256", "independence_evidence_sha256",
            "supporting_bundle_sha256", "conflict_matrix_sha256", "issuer_challenge_sha256",
        ]
        and contract["closed"] is True
        and contract["exact_context_required"] is True
        and contract["no_implicit_current_state"] is True
    )
    decision_contract = scorecard["selection_decision_contract"]
    return handoff_closed and (
        set(decision_contract)
        == {
            "allowed_outcomes", "automatic_selection_allowed",
            "all_pass_grants_capability", "tie_requires_separate_adr",
            "explicit_owner_and_independent_review_required",
            "selected_option_must_remain_null_until_explicit_decision",
        }
        and set(decision_contract["allowed_outcomes"]) == DECISION_OUTCOMES
        and decision_contract["automatic_selection_allowed"] is False
        and decision_contract["all_pass_grants_capability"] is False
        and decision_contract["tie_requires_separate_adr"] is True
        and decision_contract["explicit_owner_and_independent_review_required"] is True
        and decision_contract["selected_option_must_remain_null_until_explicit_decision"] is True
    )


def _final_selection_decision(
    scorecard: dict,
    handoff: dict,
    expected_handoff: dict[str, str],
    option_results: dict[str, bool],
) -> str:
    if not _scorecard_is_closed(scorecard) or not _is_handoff_bound(handoff, expected_handoff):
        return "BLOCKED_INVALID_STATE"
    if (
        scorecard["current_gate_state"] != "NOT_EVALUATED"
        or scorecard["selected_option"] is not None
        or scorecard["selection_allowed"] is not False
        or scorecard["real_evidence_present"] is not False
        or scorecard["issuer_authenticated"] is not False
        or scorecard["crypto_call_allowed"] is not False
        or scorecard["runtime_integration_allowed"] is not False
    ):
        return "BLOCKED_INVALID_STATE"
    if set(option_results) != OPTION_IDS or any(not isinstance(value, bool) for value in option_results.values()):
        return "BLOCKED_INVALID_STATE"
    passing = [option_id for option_id, passed in option_results.items() if passed]
    if not passing:
        return "NOT_EVALUATED"
    if len(passing) > 1:
        return "TIE_REQUIRES_SEPARATE_ADR"
    return "REVIEW_REQUIRED_SINGLE_CANDIDATE"


def _synthetic_handoff() -> dict[str, str]:
    return {
        "selection_scorecard_sha256": "1" * 64,
        "independence_evidence_sha256": "2" * 64,
        "supporting_bundle_sha256": "3" * 64,
        "conflict_matrix_sha256": "4" * 64,
        "issuer_challenge_sha256": "5" * 64,
        "subject_review_domain_id": "review-domain-a",
    }


def _canonical_digest(value: dict) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _decision_result_is_valid(
    result: dict,
    *,
    expected_handoff: dict[str, str],
    now_epoch_ms: int,
    consumed_decision_ids: set[str],
    consumed_caller_nonces: set[str],
) -> bool:
    if set(result) != DECISION_RESULT_FIELDS:
        return False
    if result["schema"] != "native-wallet-ed25519-corpus-review-independence-issuer-selection-decision-result.v1":
        return False
    if not isinstance(result["decision_id"], str) or not re.fullmatch(
        r"^[a-z0-9][a-z0-9._:-]{7,127}$", result["decision_id"]
    ):
        return False
    if result["outcome"] not in DECISION_OUTCOMES:
        return False
    if result["selected_option"] is not None:
        return False
    if result["outcome"] == "REVIEW_REQUIRED_SINGLE_CANDIDATE":
        if result["candidate_option_id"] not in OPTION_IDS:
            return False
    elif result["candidate_option_id"] is not None:
        return False
    if any(not _is_digest(result[field]) for field in DECISION_RESULT_HASH_FIELDS):
        return False
    if not isinstance(result["subject_review_domain_id"], str) or not DOMAIN_ID.fullmatch(
        result["subject_review_domain_id"]
    ):
        return False
    if not all(
        isinstance(result[field], int) and not isinstance(result[field], bool) and result[field] >= 1
        for field in ["issued_at_epoch_ms", "expires_at_epoch_ms"]
    ):
        return False
    if result["issued_at_epoch_ms"] > now_epoch_ms + MAX_FUTURE_SKEW_MS:
        return False
    if result["expires_at_epoch_ms"] <= now_epoch_ms:
        return False
    if (
        result["expires_at_epoch_ms"] <= result["issued_at_epoch_ms"]
        or result["expires_at_epoch_ms"] - result["issued_at_epoch_ms"] > MAX_DECISION_RESULT_LIFETIME_MS
    ):
        return False
    if result["decision_id"] in consumed_decision_ids or result["caller_nonce_sha256"] in consumed_caller_nonces:
        return False
    for field in [
        "selection_scorecard_sha256", "independence_evidence_sha256", "supporting_bundle_sha256",
        "conflict_matrix_sha256", "issuer_challenge_sha256", "subject_review_domain_id",
    ]:
        if result[field] != expected_handoff[field]:
            return False
    if result["context_handoff_sha256"] != _canonical_digest(expected_handoff):
        return False
    unsigned = {key: value for key, value in result.items() if key != "result_sha256"}
    return result["result_sha256"] == _canonical_digest(unsigned)


def _synthetic_decision_result(
    handoff: dict[str, str],
    *,
    outcome: str = "REVIEW_REQUIRED_SINGLE_CANDIDATE",
    candidate_option_id: str | None = "threshold_dsse_offline_roots",
) -> dict:
    result = {
        "schema": "native-wallet-ed25519-corpus-review-independence-issuer-selection-decision-result.v1",
        "decision_id": "decision-20260822-a",
        "outcome": outcome,
        "candidate_option_id": candidate_option_id if outcome == "REVIEW_REQUIRED_SINGLE_CANDIDATE" else None,
        "selected_option": None,
        "selection_scorecard_sha256": handoff["selection_scorecard_sha256"],
        "context_handoff_sha256": _canonical_digest(handoff),
        "independence_evidence_sha256": handoff["independence_evidence_sha256"],
        "supporting_bundle_sha256": handoff["supporting_bundle_sha256"],
        "conflict_matrix_sha256": handoff["conflict_matrix_sha256"],
        "issuer_challenge_sha256": handoff["issuer_challenge_sha256"],
        "subject_review_domain_id": handoff["subject_review_domain_id"],
        "issued_at_epoch_ms": 10_000,
        "expires_at_epoch_ms": 10_000 + MAX_DECISION_RESULT_LIFETIME_MS,
        "caller_nonce_sha256": "6" * 64,
        "result_sha256": "0" * 64,
    }
    result["result_sha256"] = _canonical_digest(
        {key: value for key, value in result.items() if key != "result_sha256"}
    )
    return result


def _synthetic_evidence(scorecard: dict) -> tuple[dict[str, str], dict[str, str], dict[str, list[str]], dict[str, int]]:
    common = {gate["id"]: "PASS" for gate in scorecard["common_mandatory_gates"]}
    specific = {
        gate["id"]: "PASS"
        for option in scorecard["option_specific_gates"].values()
        for gate in option
    }
    all_gates = scorecard["common_mandatory_gates"] + [
        gate
        for option in scorecard["option_specific_gates"].values()
        for gate in option
    ]
    minimum_counts = {gate["id"]: len(gate["minimum_evidence"]) for gate in all_gates}
    evidence = {gate_id: ["0" * 64] * minimum_counts[gate_id] for gate_id in minimum_counts}
    return common, specific, evidence, minimum_counts


def test_scorecard_is_conjunctive_and_missing_evidence_blocks():
    scorecard = _load()
    common, threshold, evidence, minimum_counts = _synthetic_evidence(scorecard)
    threshold = {gate_id: state for gate_id, state in threshold.items() if gate_id in THRESHOLD_GATE_IDS}
    threshold_evidence = {gate_id: evidence[gate_id] for gate_id in common | threshold}
    assert _passes(
        common,
        threshold,
        threshold_evidence,
        required_common=COMMON_GATE_IDS,
        required_specific=THRESHOLD_GATE_IDS,
        minimum_evidence_counts={gate_id: minimum_counts[gate_id] for gate_id in common | threshold},
    )
    for state in ["FAIL", "UNKNOWN", "NOT_EVALUATED"]:
        changed = deepcopy(common)
        changed["i06_freshness_replay"] = state
        assert not _passes(
            changed,
            threshold,
            threshold_evidence,
            required_common=COMMON_GATE_IDS,
            required_specific=THRESHOLD_GATE_IDS,
            minimum_evidence_counts={gate_id: minimum_counts[gate_id] for gate_id in common | threshold},
        )
    missing = deepcopy(threshold_evidence)
    missing.pop("t04_offline_root_ceremony")
    assert not _passes(
        common,
        threshold,
        missing,
        required_common=COMMON_GATE_IDS,
        required_specific=THRESHOLD_GATE_IDS,
        minimum_evidence_counts={gate_id: minimum_counts[gate_id] for gate_id in common | threshold},
    )


def test_scorecard_rejects_gate_omission_extra_ids_and_non_digest_evidence():
    scorecard = _load()
    common, threshold, evidence, minimum_counts = _synthetic_evidence(scorecard)
    threshold = {gate_id: state for gate_id, state in threshold.items() if gate_id in THRESHOLD_GATE_IDS}
    expected = {
        "required_common": COMMON_GATE_IDS,
        "required_specific": THRESHOLD_GATE_IDS,
        "minimum_evidence_counts": {gate_id: minimum_counts[gate_id] for gate_id in common | threshold},
    }
    valid_evidence = {gate_id: evidence[gate_id] for gate_id in common | threshold}
    omitted = deepcopy(common)
    omitted.pop("i10_dependency_incident")
    assert not _passes(omitted, threshold, valid_evidence, **expected)
    extra = deepcopy(threshold)
    extra["unexpected_gate"] = "PASS"
    assert not _passes(common, extra, valid_evidence, **expected)
    non_digest = deepcopy(valid_evidence)
    non_digest["i01_exact_challenge"] = ["digest"] * minimum_counts["i01_exact_challenge"]
    assert not _passes(common, threshold, non_digest, **expected)


def test_scorecard_handoff_binds_exact_context_without_implicit_state():
    scorecard = _load()
    assert _scorecard_is_closed(scorecard)
    expected = _synthetic_handoff()
    assert _is_handoff_bound(deepcopy(expected), expected)
    for field, value in [
        ("selection_scorecard_sha256", "6" * 64),
        ("supporting_bundle_sha256", "not-a-digest"),
        ("subject_review_domain_id", "bad"),
    ]:
        changed = deepcopy(expected)
        changed[field] = value
        assert not _is_handoff_bound(changed, expected)
    extra = deepcopy(expected)
    extra["selected_option"] = "threshold_dsse_offline_roots"
    assert not _is_handoff_bound(extra, expected)
    missing = deepcopy(expected)
    missing.pop("conflict_matrix_sha256")
    assert not _is_handoff_bound(missing, expected)


def test_final_decision_is_non_authoritative_and_tie_is_not_auto_selected():
    scorecard = _load()
    handoff = _synthetic_handoff()
    assert _final_selection_decision(scorecard, handoff, handoff, {
        "threshold_dsse_offline_roots": False,
        "dual_webauthn_human_issuers": False,
    }) == "NOT_EVALUATED"
    assert _final_selection_decision(scorecard, handoff, handoff, {
        "threshold_dsse_offline_roots": True,
        "dual_webauthn_human_issuers": False,
    }) == "REVIEW_REQUIRED_SINGLE_CANDIDATE"
    assert _final_selection_decision(scorecard, handoff, handoff, {
        "threshold_dsse_offline_roots": True,
        "dual_webauthn_human_issuers": True,
    }) == "TIE_REQUIRES_SEPARATE_ADR"


def test_final_decision_rejects_state_drift_and_never_grants_capability():
    scorecard = _load()
    handoff = _synthetic_handoff()
    for field, value in [
        ("current_gate_state", "PASS"),
        ("selected_option", "threshold_dsse_offline_roots"),
        ("selection_allowed", True),
        ("real_evidence_present", True),
        ("issuer_authenticated", True),
        ("crypto_call_allowed", True),
        ("runtime_integration_allowed", True),
    ]:
        changed = deepcopy(scorecard)
        changed[field] = value
        assert _final_selection_decision(changed, handoff, handoff, {
            "threshold_dsse_offline_roots": True,
            "dual_webauthn_human_issuers": False,
        }) == "BLOCKED_INVALID_STATE"
    for invalid_options in [
        {"threshold_dsse_offline_roots": True},
        {"threshold_dsse_offline_roots": True, "dual_webauthn_human_issuers": True, "extra": False},
        {"threshold_dsse_offline_roots": 1, "dual_webauthn_human_issuers": False},
    ]:
        assert _final_selection_decision(scorecard, handoff, handoff, invalid_options) == "BLOCKED_INVALID_STATE"


def test_decision_result_schema_is_closed_immutable_and_non_authoritative():
    schema = _load(DECISION_RESULT_SCHEMA_PATH)
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])
    assert schema["properties"]["selected_option"] == {"const": None}
    assert schema["maximum_lifetime_ms"] == MAX_DECISION_RESULT_LIFETIME_MS
    assert schema["maximum_future_skew_ms"] == MAX_FUTURE_SKEW_MS
    assert schema["single_use_decision_id_required"] is True
    assert schema["single_use_caller_nonce_required"] is True
    assert schema["result_digest_covers_all_other_fields"] is True
    assert schema["context_handoff_digest_is_exact"] is True
    assert schema["automatic_selection_allowed"] is False
    assert schema["selection_allowed"] is False
    assert schema["crypto_call_allowed"] is False
    assert schema["runtime_integration_allowed"] is False


def test_decision_result_binds_outcome_context_digest_and_replay_state():
    scorecard = _load()
    handoff = _synthetic_handoff()
    result = _synthetic_decision_result(handoff)
    assert _scorecard_is_closed(scorecard)
    assert _decision_result_is_valid(
        result,
        expected_handoff=handoff,
        now_epoch_ms=10_000,
        consumed_decision_ids=set(),
        consumed_caller_nonces=set(),
    )
    for outcome in ["NOT_EVALUATED", "TIE_REQUIRES_SEPARATE_ADR", "BLOCKED_INVALID_STATE"]:
        changed = _synthetic_decision_result(handoff, outcome=outcome)
        assert _decision_result_is_valid(
            changed,
            expected_handoff=handoff,
            now_epoch_ms=10_000,
            consumed_decision_ids=set(),
            consumed_caller_nonces=set(),
        )
    assert not _decision_result_is_valid(
        result,
        expected_handoff=handoff,
        now_epoch_ms=10_000,
        consumed_decision_ids={result["decision_id"]},
        consumed_caller_nonces=set(),
    )
    assert not _decision_result_is_valid(
        result,
        expected_handoff=handoff,
        now_epoch_ms=10_000,
        consumed_decision_ids=set(),
        consumed_caller_nonces={result["caller_nonce_sha256"]},
    )


def test_decision_result_rejects_context_outcome_digest_and_time_drift():
    handoff = _synthetic_handoff()
    result = _synthetic_decision_result(handoff)
    mutations = []
    for field, value in [
        ("selection_scorecard_sha256", "7" * 64),
        ("context_handoff_sha256", "8" * 64),
        ("independence_evidence_sha256", "9" * 64),
        ("subject_review_domain_id", "other-domain"),
        ("selected_option", "threshold_dsse_offline_roots"),
        ("candidate_option_id", None),
        ("outcome", "UNKNOWN"),
        ("expires_at_epoch_ms", 10_000),
        ("issued_at_epoch_ms", 10_000 + MAX_FUTURE_SKEW_MS + 1),
        ("caller_nonce_sha256", "a" * 64),
    ]:
        changed = deepcopy(result)
        changed[field] = value
        mutations.append(changed)
    too_long = deepcopy(result)
    too_long["expires_at_epoch_ms"] = too_long["issued_at_epoch_ms"] + MAX_DECISION_RESULT_LIFETIME_MS + 1
    mutations.append(too_long)
    extra = deepcopy(result)
    extra["extra"] = "closed-shape-drift"
    mutations.append(extra)
    missing = deepcopy(result)
    missing.pop("result_sha256")
    mutations.append(missing)
    for changed in mutations:
        assert not _decision_result_is_valid(
            changed,
            expected_handoff=handoff,
            now_epoch_ms=10_000,
            consumed_decision_ids=set(),
            consumed_caller_nonces=set(),
        )


def test_handoff_names_match_the_challenge_bundle_matrix_and_evidence_contracts():
    scorecard = _load()
    handoff = scorecard["handoff_contract"]
    bundle = _load(BUNDLE_PATH)
    matrix = _load(MATRIX_PATH)
    issuer_auth = _load(ISSUER_AUTH_PATH)
    independence = _load(INDEPENDENCE_EVIDENCE_PATH)
    assert {
        "independence_evidence_sha256", "scorecard_sha256", "issuer_challenge_sha256",
    } <= set(bundle["required"])
    assert matrix["schema"] == "native-wallet-ed25519-corpus-review-conflict-of-control-matrix.v1"
    assert independence["additionalProperties"] is False
    assert set(handoff["canonical_digest_fields"]) == {
        "selection_scorecard_sha256", "independence_evidence_sha256",
        "supporting_bundle_sha256", "conflict_matrix_sha256", "issuer_challenge_sha256",
    }
    assert {
        "scorecard_sha256_raw_32_bytes", "evidence_record_sha256_raw_32_bytes",
        "authentication_root_sha256_raw_32_bytes", "caller_nonce_sha256_raw_32_bytes",
    } <= set(issuer_auth["ordered_fields"])
    assert set(scorecard["selection_decision_contract"]["allowed_outcomes"]) == DECISION_OUTCOMES


def test_common_gates_cover_bundle_control_replay_recovery_privacy_and_incidents():
    scorecard = _load()
    assert {gate["id"] for gate in scorecard["common_mandatory_gates"]} == {
        f"i{number:02d}_{suffix}" for number, suffix in [
            (1, "exact_challenge"), (2, "complete_bundle"), (3, "conflict_matrix"),
            (4, "two_issuer_independence"), (5, "subject_non_control"),
            (6, "freshness_replay"), (7, "root_recovery"), (8, "parser_corpus"),
            (9, "audit_privacy_retention"), (10, "dependency_incident"),
        ]
    }
    assert all(gate["minimum_evidence"] for gate in scorecard["common_mandatory_gates"])


def test_threshold_gates_prevent_duplicate_signers_and_role_escalation():
    scorecard = _load()
    gates = {gate["id"]: gate for gate in scorecard["option_specific_gates"]["threshold_dsse_offline_roots"]}
    assert set(gates) == {
        "t01_threshold_policy", "t02_role_separation",
        "t03_dsse_exact_bytes", "t04_offline_root_ceremony",
    }
    assert "duplicate signer identities cannot count twice" in gates["t01_threshold_policy"]["requirement"]
    assert "lower threshold" in gates["t02_role_separation"]["requirement"]


def test_webauthn_gates_require_two_enrollments_exact_context_and_collusion_controls():
    scorecard = _load()
    gates = {gate["id"]: gate for gate in scorecard["option_specific_gates"]["dual_webauthn_human_issuers"]}
    assert set(gates) == {
        "w01_enrollment_provenance", "w02_exact_rp_origin",
        "w03_profile_flags", "w04_human_collusion_controls",
    }
    assert "separately witnessed" in gates["w01_enrollment_provenance"]["requirement"]
    assert "no fallback" in gates["w02_exact_rp_origin"]["requirement"]
    assert "UP, UV" in gates["w03_profile_flags"]["requirement"]


def test_current_state_has_explicit_blockers_and_no_selection():
    scorecard = _load()
    assert _scorecard_is_closed(scorecard)
    assert scorecard["current_gate_state"] == "NOT_EVALUATED"
    assert set(scorecard["non_selection_reasons"]) == {
        "threshold_dsse_offline_roots", "dual_webauthn_human_issuers",
    }
    assert scorecard["selected_option"] is None
    assert scorecard["all_common_gates_pass"] is False
    assert scorecard["any_option_specific_gates_pass"] is False
    assert scorecard["selection_allowed"] is False


def test_no_real_evidence_key_or_runtime_permission_is_present():
    scorecard = _load()
    for field in ["real_evidence_present", "issuer_authenticated", "crypto_call_allowed", "runtime_integration_allowed"]:
        assert scorecard[field] is False
    text = SCORECARD_PATH.read_text(encoding="utf-8")
    for forbidden in ["private_key", "secret_key", "BEGIN PRIVATE", "credential_public_key"]:
        assert forbidden not in text
