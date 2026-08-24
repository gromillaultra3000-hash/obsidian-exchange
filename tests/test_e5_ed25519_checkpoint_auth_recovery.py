import json
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "native-wallet/rehearsals/attestation-dependencies/automated-minimal/tests/fixtures"
SCORECARD_PATH = FIXTURES / "ed25519-corpus-review-checkpoint-auth-scorecard-v1.json"
MATRIX_PATH = FIXTURES / "ed25519-corpus-review-checkpoint-split-view-recovery-matrix-v1.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _passes(common: dict[str, str], specific: dict[str, str], evidence: dict[str, list[str]]) -> bool:
    gates = common | specific
    return bool(gates) and all(state == "PASS" and bool(evidence.get(gate)) for gate, state in gates.items())


def test_scorecard_is_conjunctive_without_quorum_degradation():
    scorecard = _load(SCORECARD_PATH)
    common = {gate["id"]: "PASS" for gate in scorecard["common_mandatory_gates"]}
    dsse = {gate["id"]: "PASS" for gate in scorecard["candidate_specific_gates"]["dual_dsse_offline_witnesses"]}
    evidence = {gate: ["digest"] for gate in common | dsse}
    assert _passes(common, dsse, evidence)
    for state in ["FAIL", "UNKNOWN", "NOT_EVALUATED"]:
        changed = deepcopy(common)
        changed["k08_availability_no_degrade"] = state
        assert not _passes(changed, dsse, evidence)
    missing = deepcopy(evidence)
    missing.pop("s04_offline_recovery")
    assert not _passes(common, dsse, missing)


def test_common_gates_cover_equivocation_rotation_and_availability():
    scorecard = _load(SCORECARD_PATH)
    assert {gate["id"] for gate in scorecard["common_mandatory_gates"]} == {
        f"k{number:02d}_{suffix}" for number, suffix in [
            (1, "exact_checkpoint_bytes"), (2, "two_domain_independence"),
            (3, "nonce_freshness"), (4, "monotonic_high_water"),
            (5, "equivocation_quarantine"), (6, "root_rotation_recovery"),
            (7, "parser_dependency"), (8, "availability_no_degrade"),
        ]
    }


def test_candidate_specific_gates_preserve_distinct_trust_surfaces():
    scorecard = _load(SCORECARD_PATH)
    dsse = {gate["id"] for gate in scorecard["candidate_specific_gates"]["dual_dsse_offline_witnesses"]}
    webauthn = {gate["id"] for gate in scorecard["candidate_specific_gates"]["dual_webauthn_human_witnesses"]}
    assert dsse == {"s01_distinct_active_roots", "s02_exact_dsse", "s03_witness_signer_isolation", "s04_offline_recovery"}
    assert webauthn == {"h01_distinct_enrollments", "h02_exact_rp_origin", "h03_profile_flags", "h04_human_recovery_availability"}
    assert dsse.isdisjoint(webauthn)


def test_split_views_quarantine_and_never_choose_a_fork():
    matrix = _load(MATRIX_PATH)
    cases = {item["id"]: item for item in matrix["cases"]}
    for case_id in ["r01_same_sequence_different_head", "r02_divergent_descendants", "r08_checkpoint_ahead_of_local_store", "r09_transparency_split_view"]:
        assert cases[case_id]["decision"] == "QUARANTINE"
        assert cases[case_id]["automatic_recovery"] is False
    assert matrix["quarantine_does_not_select_a_winning_fork"] is True


def test_loss_or_overlap_blocks_without_single_witness_fallback():
    matrix = _load(MATRIX_PATH)
    cases = {item["id"]: item for item in matrix["cases"]}
    assert cases["r03_one_witness_unavailable"]["decision"] == "BLOCK"
    assert cases["r04_high_water_store_lost"]["decision"] == "BLOCK"
    assert cases["r10_recovery_authority_overlap"]["decision"] == "REJECT"
    assert matrix["emergency_single_witness_mode_allowed"] is False
    assert matrix["high_water_reconstruction_from_untrusted_local_chain_allowed"] is False


def test_rotation_requires_review_continuity_and_old_root_rejects():
    matrix = _load(MATRIX_PATH)
    cases = {item["id"]: item for item in matrix["cases"]}
    assert cases["r05_old_root_after_rotation"]["decision"] == "REJECT"
    assert cases["r06_valid_root_rotation"]["decision"] == "ALLOW_REVIEWED_ADVANCE"
    assert cases["r06_valid_root_rotation"]["automatic_recovery"] is False
    requirements = " ".join(matrix["quarantine_exit_requires"])
    assert "new consumer-approved policy epoch" in requirements
    assert "last non-conflicting accepted checkpoint" in requirements


def test_nothing_is_selected_executed_or_permitted():
    scorecard = _load(SCORECARD_PATH)
    matrix = _load(MATRIX_PATH)
    assert scorecard["current_gate_state"] == "NOT_EVALUATED"
    assert scorecard["selected_candidate"] is None
    for field in ["all_common_gates_pass", "any_candidate_gates_pass", "selection_allowed", "real_evidence_present", "gate_i09_pass", "runtime_integration_allowed"]:
        assert scorecard[field] is False
    assert matrix["real_split_view_test_executed"] is False
    assert matrix["real_recovery_executed"] is False
    assert matrix["gate_i09_pass"] is False
