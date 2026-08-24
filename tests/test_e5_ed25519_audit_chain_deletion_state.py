import hashlib
import json
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "native-wallet/rehearsals/attestation-dependencies/automated-minimal/tests/fixtures"
EVENT_SCHEMA_PATH = FIXTURES / "ed25519-corpus-review-audit-event-v1.schema.json"
VECTOR_PATH = FIXTURES / "ed25519-corpus-review-audit-event-hash-vector-v1.json"
MACHINE_PATH = FIXTURES / "ed25519-corpus-review-deletion-state-machine-v1.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _field(value: str) -> bytes:
    encoded = value.encode("utf-8")
    if not encoded or len(encoded) > 65535:
        raise ValueError("bounded non-empty UTF-8 required")
    return len(encoded).to_bytes(2, "big") + encoded


def _digest(value: str | None) -> bytes:
    if value is None:
        return bytes(32)
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError("canonical SHA-256 required")
    return bytes.fromhex(value)


def _event_hash(event: dict) -> str:
    parts = [
        _field("obsidian.ed25519-review.audit-event.v1"),
        event["sequence"].to_bytes(8, "big"),
        _field(event["event_id"]), _field(event["event_type"]),
        event["occurred_at_epoch_ms"].to_bytes(8, "big"),
        _field(event["actor_domain_id"]), _field(event["subject_domain_id"]),
        _digest(event["object_sha256"]), _digest(event["policy_sha256"]),
        _digest(event["previous_event_sha256"]),
        _field(event["decision"]), _field(event["reason_code"]),
    ]
    return hashlib.sha256(b"".join(parts)).hexdigest()


def _transition(machine: dict, state: str, event: str) -> str | None:
    matches = [item["to"] for item in machine["transitions"] if item["from"] == state and item["event"] == event]
    return matches[0] if len(matches) == 1 else None


def test_event_schema_is_closed_minimized_and_immutable():
    schema = _load(EVENT_SCHEMA_PATH)
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])
    assert schema["updates_or_deletes_allowed"] is False
    assert schema["free_text_allowed"] is False
    assert schema["storage_implemented"] is False
    assert schema["real_event_present"] is False


def test_fixed_hash_vector_and_every_field_mutation_change_digest():
    vector = _load(VECTOR_PATH)
    exact = _event_hash(vector["event"])
    assert exact == vector["expected_event_sha256"]
    for field, value in vector["event"].items():
        changed = deepcopy(vector["event"])
        if value is None:
            changed[field] = "3" * 64
        elif isinstance(value, int):
            changed[field] = value + 1
        elif field.endswith("sha256"):
            changed[field] = "4" * 64
        else:
            changed[field] = f"{value}x"
        assert _event_hash(changed) != exact


def test_hash_chain_binds_sequence_and_previous_event():
    first = _load(VECTOR_PATH)["event"]
    second = deepcopy(first)
    second["sequence"] = 2
    second["event_id"] = "audit-event-0002"
    second["previous_event_sha256"] = _event_hash(first)
    exact = _event_hash(second)
    reordered = deepcopy(second)
    reordered["sequence"] = 3
    assert _event_hash(reordered) != exact
    broken = deepcopy(second)
    broken["previous_event_sha256"] = "0" * 64
    assert _event_hash(broken) != exact


def test_happy_path_is_unique_and_terminal_states_have_no_outgoing_edges():
    machine = _load(MACHINE_PATH)
    state = machine["initial_state"]
    for event in ["CLAIM", "BEGIN", "ALL_LOCATION_OUTCOMES_KNOWN", "SCAN_COVERS_INVENTORY", "INDEPENDENT_WITNESS_APPROVES"]:
        state = _transition(machine, state, event)
        assert state is not None
    assert state == "COMPLETE"
    for terminal in machine["terminal_states"]:
        assert not any(item["from"] == terminal for item in machine["transitions"])


def test_partial_unknown_scan_or_witness_failure_requires_review():
    machine = _load(MACHINE_PATH)
    assert _transition(machine, "DELETING", "PARTIAL_OR_UNKNOWN") == "REVIEW_REQUIRED"
    assert _transition(machine, "SCANNING", "SCAN_MISMATCH") == "REVIEW_REQUIRED"
    assert _transition(machine, "AWAITING_WITNESS", "WITNESS_REJECTS_OR_UNKNOWN") == "REVIEW_REQUIRED"
    assert machine["automatic_retry_after_any_deletion_side_effect"] is False
    assert machine["new_attempt_after_review_requires_new_plan_and_links_previous_receipt"] is True


def test_crash_policy_never_blindly_repeats_deletion():
    machine = _load(MACHINE_PATH)
    policy = {item["state"]: item["recovery"] for item in machine["crash_policy"]}
    assert "no side effect began" in policy["CLAIMED"]
    assert "REVIEW_REQUIRED" in policy["DELETING"]
    assert "do not repeat deletion" in policy["SCANNING"]
    assert "do not repeat deletion" in policy["AWAITING_WITNESS"]
    assert machine["append_audit_event_before_state_visibility"] is True


def test_symbolic_machine_grants_nothing():
    machine = _load(MACHINE_PATH)
    for field in ["real_state_machine_implemented", "real_deletion_attempt_present", "gate_i09_pass", "selection_allowed", "runtime_integration_allowed"]:
        assert machine[field] is False
