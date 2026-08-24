import json
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "native-wallet/rehearsals/attestation-dependencies/automated-minimal/tests/fixtures"
SCHEMA_PATH = FIXTURES / "ed25519-corpus-review-audit-checkpoint-v1.schema.json"
POLICY_PATH = FIXTURES / "ed25519-corpus-review-audit-checkpoint-policy-v1.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _accept_checkpoint(checkpoint: dict, expected: dict, highest: dict, now_ms: int) -> bool:
    evidence = checkpoint.get("authentication_evidence", [])
    distinct_fields = ["domain_id", "authentication_root_sha256", "recovery_authority_id", "host_failure_domain_id", "evidence_sha256"]
    return (
        checkpoint.get("chain_id") == expected["chain_id"]
        and checkpoint.get("policy_sha256") == expected["policy_sha256"]
        and checkpoint.get("caller_nonce_sha256") == expected["caller_nonce_sha256"]
        and len(evidence) == 2
        and all(evidence[0].get(field) != evidence[1].get(field) for field in distinct_fields)
        and checkpoint.get("issued_at_epoch_ms", now_ms + 1) <= now_ms <= checkpoint.get("expires_at_epoch_ms", now_ms - 1)
        and 0 < checkpoint["expires_at_epoch_ms"] - checkpoint["issued_at_epoch_ms"] <= 600_000
        and checkpoint.get("checkpoint_epoch", 0) >= highest["epoch"]
        and checkpoint.get("audit_sequence", 0) > highest["sequence"]
        and checkpoint.get("previous_checkpoint_sha256") == highest["checkpoint_sha256"]
        and checkpoint.get("audit_sequence") == expected["local_sequence"]
        and checkpoint.get("audit_head_sha256") == expected["local_head_sha256"]
    )


def _synthetic_checkpoint() -> tuple[dict, dict, dict, int]:
    now = 1_786_500_100_000
    checkpoint = {
        "chain_id": "audit-chain-a", "policy_sha256": "1" * 64,
        "audit_sequence": 11, "audit_head_sha256": "2" * 64,
        "previous_checkpoint_sha256": "3" * 64, "checkpoint_epoch": 7,
        "caller_nonce_sha256": "4" * 64,
        "issued_at_epoch_ms": now - 1_000, "expires_at_epoch_ms": now + 599_000,
        "authentication_evidence": [
            {"domain_id": "witness-a", "authentication_root_sha256": "5" * 64, "recovery_authority_id": "recovery-a", "host_failure_domain_id": "host-a", "evidence_sha256": "6" * 64},
            {"domain_id": "witness-b", "authentication_root_sha256": "7" * 64, "recovery_authority_id": "recovery-b", "host_failure_domain_id": "host-b", "evidence_sha256": "8" * 64},
        ],
    }
    expected = {"chain_id": "audit-chain-a", "policy_sha256": "1" * 64, "caller_nonce_sha256": "4" * 64, "local_sequence": 11, "local_head_sha256": "2" * 64}
    highest = {"epoch": 6, "sequence": 10, "checkpoint_sha256": "3" * 64}
    return checkpoint, expected, highest, now


def test_checkpoint_schema_is_closed_bounded_and_requires_two_domains():
    schema = _load(SCHEMA_PATH)
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])
    evidence = schema["properties"]["authentication_evidence"]
    assert evidence["minItems"] == evidence["maxItems"] == 2
    assert evidence["items"]["additionalProperties"] is False
    assert schema["maximum_lifetime_ms"] == 600_000
    assert schema["single_use_caller_nonce_required"] is True


def test_exact_fresh_monotonic_checkpoint_passes_symbolic_gate():
    checkpoint, expected, highest, now = _synthetic_checkpoint()
    assert _accept_checkpoint(checkpoint, expected, highest, now)


def test_each_shared_authentication_domain_root_blocks():
    checkpoint, expected, highest, now = _synthetic_checkpoint()
    for field in ["domain_id", "authentication_root_sha256", "recovery_authority_id", "host_failure_domain_id", "evidence_sha256"]:
        changed = deepcopy(checkpoint)
        changed["authentication_evidence"][1][field] = changed["authentication_evidence"][0][field]
        assert not _accept_checkpoint(changed, expected, highest, now)


def test_rollback_fork_predecessor_local_drift_and_nonce_reuse_block():
    checkpoint, expected, highest, now = _synthetic_checkpoint()
    mutations = [
        ("checkpoint_epoch", 5), ("audit_sequence", 10),
        ("previous_checkpoint_sha256", "9" * 64), ("audit_head_sha256", "a" * 64),
        ("caller_nonce_sha256", "b" * 64),
    ]
    for field, value in mutations:
        changed = deepcopy(checkpoint)
        changed[field] = value
        assert not _accept_checkpoint(changed, expected, highest, now)


def test_expired_future_or_overlong_checkpoint_blocks():
    checkpoint, expected, highest, now = _synthetic_checkpoint()
    expired = deepcopy(checkpoint)
    expired["expires_at_epoch_ms"] = now - 1
    assert not _accept_checkpoint(expired, expected, highest, now)
    future = deepcopy(checkpoint)
    future["issued_at_epoch_ms"] = now + 1
    assert not _accept_checkpoint(future, expected, highest, now)
    overlong = deepcopy(checkpoint)
    overlong["issued_at_epoch_ms"] = now - 1_000
    overlong["expires_at_epoch_ms"] = now + 600_000
    assert not _accept_checkpoint(overlong, expected, highest, now)


def test_authentication_shortlist_selects_nothing():
    policy = _load(POLICY_PATH)
    options = {item["id"]: item["status"] for item in policy["authentication_shortlist"]}
    assert options == {
        "dual_dsse_offline_witnesses": "SHORTLISTED_NOT_SELECTED",
        "dual_webauthn_human_witnesses": "SHORTLISTED_NOT_SELECTED",
        "dsse_witness_plus_transparency_inclusion": "SUPPLEMENTAL_CANDIDATE",
    }
    assert policy["selected_authentication"] is None


def test_no_store_verifier_checkpoint_or_permission_exists():
    schema = _load(SCHEMA_PATH)
    policy = _load(POLICY_PATH)
    assert schema["real_checkpoint_present"] is False
    assert schema["checkpoint_accepted"] is False
    assert schema["gate_i09_pass"] is False
    for field in ["highest_state_store_implemented", "nonce_ledger_implemented", "authentication_verifier_implemented", "real_checkpoint_present", "checkpoint_acceptance_allowed", "gate_i09_pass", "runtime_integration_allowed"]:
        assert policy[field] is False
