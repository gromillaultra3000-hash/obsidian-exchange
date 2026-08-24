import json
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "native-wallet/rehearsals/attestation-dependencies/automated-minimal/tests/fixtures"
SCORECARD_PATH = FIXTURES / "ed25519-corpus-review-verifier-selection-scorecard-v1.json"
INDEPENDENCE_PATH = FIXTURES / "ed25519-corpus-review-independence-evidence-v1.schema.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _conjunctive_decision(common: dict[str, str], specific: dict[str, str], evidence: dict[str, list[str]]) -> bool:
    gates = common | specific
    return bool(gates) and all(
        state == "PASS" and bool(evidence.get(gate_id)) for gate_id, state in gates.items()
    )


def test_scorecard_is_conjunctive_and_has_no_weighted_bypass():
    scorecard = _load(SCORECARD_PATH)
    assert "every common and option-specific mandatory gate" in scorecard["decision_rule"]
    assert scorecard["allowed_gate_states"] == ["PASS", "FAIL", "UNKNOWN", "NOT_EVALUATED"]
    common = {gate["id"]: "PASS" for gate in scorecard["common_mandatory_gates"]}
    local = {gate["id"]: "PASS" for gate in scorecard["option_specific_gates"]["local_pinned_execution"]}
    evidence = {gate_id: ["digest"] for gate_id in common | local}
    assert _conjunctive_decision(common, local, evidence)
    for blocked_state in ["FAIL", "UNKNOWN", "NOT_EVALUATED"]:
        changed = dict(common)
        changed["c06_freshness_replay"] = blocked_state
        assert not _conjunctive_decision(changed, local, evidence)
    missing = deepcopy(evidence)
    missing.pop("l02_executed_identity")
    assert not _conjunctive_decision(common, local, missing)


def test_common_gates_cover_every_non_compensable_boundary():
    scorecard = _load(SCORECARD_PATH)
    gates = {gate["id"] for gate in scorecard["common_mandatory_gates"]}
    assert gates == {f"c{number:02d}_{suffix}" for number, suffix in [
        (1, "closed_exact_bytes"), (2, "complete_cross_binding"),
        (3, "build_provenance"), (4, "reproducible_bytes"),
        (5, "policy_identity"), (6, "freshness_replay"),
        (7, "parser_parity"), (8, "independent_administration"),
        (9, "rotation_recovery"), (10, "dependency_license"),
    ]}
    assert all(gate["minimum_evidence"] for gate in scorecard["common_mandatory_gates"])


def test_local_and_dsse_specific_gates_close_different_failure_modes():
    scorecard = _load(SCORECARD_PATH)
    local = {gate["id"] for gate in scorecard["option_specific_gates"]["local_pinned_execution"]}
    dsse = {gate["id"] for gate in scorecard["option_specific_gates"]["dsse_signed_result"]}
    assert local == {"l01_private_process_boundary", "l02_executed_identity", "l03_host_failure_domain"}
    assert dsse == {
        "d01_dedicated_result_key", "d02_root_epoch_revocation",
        "d03_signer_execution_binding", "d04_key_compromise_recovery",
    }
    assert local.isdisjoint(dsse)


def test_independence_contract_is_closed_and_rejects_shared_roots():
    schema = _load(INDEPENDENCE_PATH)
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])
    distinct = schema["pairwise_distinct_across_reviews"]
    assert "verifier_administration_root_sha256" in distinct
    assert "result_authentication_root_sha256" in distinct
    assert "host_failure_domain_id" in distinct
    assert schema["distinct_within_each_record"] == [
        ["credential_root_sha256", "verifier_administration_root_sha256", "result_authentication_root_sha256"],
        ["recovery_authority_id", "verifier_recovery_authority_id"],
        ["builder_a_root_sha256", "builder_b_root_sha256"],
    ]


def test_current_state_selects_nothing_and_grants_nothing():
    scorecard = _load(SCORECARD_PATH)
    assert scorecard["current_gate_state"] == "NOT_EVALUATED"
    assert scorecard["selected_option"] is None
    assert scorecard["all_common_gates_pass"] is False
    assert scorecard["any_option_specific_gates_pass"] is False
    assert scorecard["selection_allowed"] is False
    assert scorecard["real_evidence_present"] is False
    assert scorecard["crypto_call_allowed"] is False
    assert scorecard["runtime_integration_allowed"] is False
    independence = _load(INDEPENDENCE_PATH)
    assert independence["issuer_authentication_defined"] is False
    assert independence["real_evidence_present"] is False
    assert independence["selection_allowed"] is False


def test_no_real_identity_key_or_evidence_is_checked_in():
    for path in [SCORECARD_PATH, INDEPENDENCE_PATH]:
        text = path.read_text(encoding="utf-8")
        for forbidden in ["private_key", "secret_key", "BEGIN PRIVATE", "credential_public_key"]:
            assert forbidden not in text
