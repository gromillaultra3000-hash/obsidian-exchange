import json
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "native-wallet/rehearsals/attestation-dependencies/automated-minimal/tests/fixtures"
CONTRACT_PATH = FIXTURES / "ed25519-corpus-review-audit-persistence-contract-v1.json"
FAULTS_PATH = FIXTURES / "ed25519-corpus-review-audit-fault-matrix-v1.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class SymbolicStore:
    def __init__(self):
        self.state = "PLANNED"
        self.authorizing_event = None
        self.audit = []

    def transition(self, expected: str, target: str, event_digest: str, fault: str | None = None):
        if self.state != expected:
            return False
        staged_audit = self.audit + [event_digest]
        if fault == "after_audit_staged":
            return False
        staged_state = target
        staged_authorizing_event = event_digest
        if fault == "after_state_staged":
            return False
        self.audit = staged_audit
        self.state = staged_state
        self.authorizing_event = staged_authorizing_event
        return True


def _recover_location(intent_state: str, invocation_may_have_begun: bool, durable_outcome: str | None):
    if intent_state in {"SUCCEEDED", "FAILED", "UNKNOWN_REVIEW"}:
        return intent_state
    if durable_outcome in {"SUCCEEDED", "FAILED"}:
        return durable_outcome
    if invocation_may_have_begun:
        return "UNKNOWN_REVIEW"
    return "PREPARED"


def test_internal_transition_commits_audit_and_state_together():
    store = SymbolicStore()
    assert store.transition("PLANNED", "CLAIMED", "1" * 64)
    assert store.audit == ["1" * 64]
    assert store.state == "CLAIMED"
    assert store.authorizing_event == store.audit[-1]


def test_staged_faults_expose_neither_audit_nor_state():
    for fault in ["after_audit_staged", "after_state_staged"]:
        store = SymbolicStore()
        before = deepcopy(store.__dict__)
        assert not store.transition("PLANNED", "CLAIMED", "1" * 64, fault=fault)
        assert store.__dict__ == before


def test_compare_and_set_allows_only_one_transition_winner():
    store = SymbolicStore()
    assert store.transition("PLANNED", "CLAIMED", "1" * 64)
    assert not store.transition("PLANNED", "FAILED", "2" * 64)
    assert store.state == "CLAIMED"
    assert store.audit == ["1" * 64]


def test_uncertain_external_effect_never_becomes_success_or_retry():
    assert _recover_location("PREPARED", True, None) == "UNKNOWN_REVIEW"
    assert _recover_location("UNKNOWN_REVIEW", True, None) == "UNKNOWN_REVIEW"
    assert _recover_location("PREPARED", True, "SUCCEEDED") == "SUCCEEDED"
    assert _recover_location("PREPARED", True, "FAILED") == "FAILED"
    assert _recover_location("PREPARED", False, None) == "PREPARED"


def test_fault_matrix_covers_each_transaction_and_external_boundary():
    matrix = _load(FAULTS_PATH)
    cases = {item["id"]: item for item in matrix["cases"]}
    assert set(cases) == {f"f{number:02d}_{suffix}" for number, suffix in [
        (1, "before_transaction"), (2, "after_audit_staged"),
        (3, "after_state_staged"), (4, "after_atomic_commit"),
        (5, "after_location_prepared_commit"), (6, "during_external_side_effect"),
        (7, "after_effect_before_outcome_commit"), (8, "after_outcome_commit"),
        (9, "during_read_only_scan"), (10, "checkpoint_unavailable"),
    ]}
    assert cases["f06_during_external_side_effect"]["recovery"] == "UNKNOWN_REVIEW and no automatic reinvocation"
    assert cases["f10_checkpoint_unavailable"]["visible_state"] == "BLOCKED_FROM_GATE_PASS"


def test_contract_denies_exactly_once_external_effect_claim():
    contract = _load(CONTRACT_PATH)
    assert contract["external_effect_and_database_atomicity_claimed"] is False
    assert contract["automatic_retry_of_uncertain_effect"] is False
    assert contract["independent_checkpoint_required_for_chain_completeness"] is True
    assert "UNKNOWN_REVIEW" in contract["per_location_attempt_states"]
    assert "post-deletion scan" in contract["read_only_repeatable_operations"]


def test_contract_freezes_atomicity_and_no_blind_repetition_invariants():
    contract = _load(CONTRACT_PATH)
    assert contract["internal_transition_transaction"] == [
        "lock current state row and current audit head",
        "compare expected state, sequence and previous event digest",
        "validate closed event and transition guard",
        "stage immutable audit event first",
        "stage state transition referencing staged event digest",
        "commit audit event, audit head and state atomically",
        "publish no state or event before commit",
    ]
    assert set(contract["required_invariants"]) == {
        "one audit event per visible internal state transition",
        "event sequence increases by exactly one",
        "event previous hash equals prior committed audit head",
        "state row stores the exact authorizing event digest",
        "compare-and-set allows one transition winner",
        "terminal state has no update or delete path",
        "audit event has no update or delete path",
        "transaction rollback exposes neither staged event nor staged state",
    }
    assert contract["external_side_effect_protocol"][1:] == [
        "invoke deletion at most once for that location intent",
        "atomically append outcome audit event and transition PREPARED to SUCCEEDED or FAILED",
        "if invocation may have begun but durable outcome is absent, transition only to UNKNOWN_REVIEW",
        "never automatically invoke a PREPARED or UNKNOWN_REVIEW location again after recovery",
    ]


def test_fault_matrix_is_closed_and_uncertainty_requires_review():
    matrix = _load(FAULTS_PATH)
    assert matrix["all_faults_fail_closed"] is True
    assert matrix["uncertain_side_effect_is_success"] is False
    assert matrix["uncertain_side_effect_is_safe_to_retry"] is False
    required = {"id", "fault_point", "visible_audit", "visible_state", "recovery"}
    assert all(set(case) == required for case in matrix["cases"])
    cases = {case["id"]: case for case in matrix["cases"]}
    assert "UNKNOWN_REVIEW" in cases["f06_during_external_side_effect"]["recovery"]
    assert "no automatic reinvocation" in cases["f06_during_external_side_effect"]["recovery"]
    assert "UNKNOWN_REVIEW" in cases["f07_after_effect_before_outcome_commit"]["recovery"]
    assert cases["f10_checkpoint_unavailable"]["visible_state"] == "BLOCKED_FROM_GATE_PASS"


def test_symbolic_contract_creates_no_store_or_permission():
    contract = _load(CONTRACT_PATH)
    matrix = _load(FAULTS_PATH)
    for field in ["persistence_backend_selected", "real_store_created", "real_side_effect_authorized", "gate_i09_pass", "selection_allowed", "runtime_integration_allowed"]:
        assert contract[field] is False
    assert matrix["real_fault_injection_executed"] is False
    assert matrix["gate_i09_pass"] is False
