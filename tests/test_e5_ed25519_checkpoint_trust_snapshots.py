import json
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "native-wallet/rehearsals/attestation-dependencies/automated-minimal/tests/fixtures"
DSSE_PATH = FIXTURES / "ed25519-corpus-review-checkpoint-dsse-root-snapshot-v1.schema.json"
WEBAUTHN_PATH = FIXTURES / "ed25519-corpus-review-checkpoint-webauthn-credential-snapshot-v1.schema.json"
POLICY_PATH = FIXTURES / "ed25519-corpus-review-checkpoint-trust-snapshot-policy-v1.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _snapshot_gate(snapshot: dict, expected: dict, now_ms: int) -> bool:
    return (
        all(snapshot.get(field) == expected[field] for field in ["policy_id", "witness_slot", "witness_domain_id", "epoch"])
        and snapshot.get("status") == "ACTIVE"
        and snapshot.get("valid_from_epoch_ms", now_ms + 1) <= now_ms <= snapshot.get("valid_until_epoch_ms", now_ms - 1)
        and snapshot.get("recovery_authority_id") != snapshot.get("witness_domain_id")
    )


def _active_snapshot() -> tuple[dict, dict, int]:
    now = 1_786_500_000_000
    snapshot = {
        "policy_id": "checkpoint-policy-a", "witness_slot": 0,
        "witness_domain_id": "checkpoint-witness-a", "epoch": 7,
        "status": "ACTIVE", "valid_from_epoch_ms": now - 1,
        "valid_until_epoch_ms": now + 600_000,
        "recovery_authority_id": "checkpoint-recovery-a",
    }
    expected = {field: snapshot[field] for field in ["policy_id", "witness_slot", "witness_domain_id", "epoch"]}
    return snapshot, expected, now


def test_snapshot_schemas_are_closed_and_embed_no_key_bytes():
    dsse = _load(DSSE_PATH)
    webauthn = _load(WEBAUTHN_PATH)
    for schema in [dsse, webauthn]:
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) == set(schema["properties"])
    assert dsse["public_key_bytes_embedded"] is False
    assert webauthn["credential_or_public_key_bytes_embedded"] is False
    assert "public_key_bytes_sha256" in dsse["properties"]
    assert "cose_public_key_bytes_sha256" in webauthn["properties"]


def test_consumer_selection_never_uses_keyid_or_assertion_credential():
    dsse = _load(DSSE_PATH)
    webauthn = _load(WEBAUTHN_PATH)
    expected = ["policy_id", "witness_slot", "witness_domain_id", "epoch"]
    assert dsse["consumer_selection_inputs"] == expected
    assert webauthn["consumer_selection_inputs"] == expected
    assert dsse["keyid_input_used_for_selection"] is False
    assert webauthn["assertion_credential_id_used_for_selection"] is False


def test_exact_active_current_snapshot_passes_symbolic_gate():
    snapshot, expected, now = _active_snapshot()
    assert _snapshot_gate(snapshot, expected, now)


def test_policy_slot_domain_epoch_status_time_or_recovery_drift_blocks():
    snapshot, expected, now = _active_snapshot()
    mutations = [
        ("policy_id", "other-policy"), ("witness_slot", 1),
        ("witness_domain_id", "checkpoint-witness-b"), ("epoch", 8),
        ("status", "REVOKED"), ("valid_from_epoch_ms", now + 1),
        ("valid_until_epoch_ms", now - 1),
        ("recovery_authority_id", "checkpoint-witness-a"),
    ]
    for field, value in mutations:
        changed = deepcopy(snapshot)
        changed[field] = value
        assert not _snapshot_gate(changed, expected, now)


def test_candidate_metadata_is_exact_and_backup_eligibility_false():
    dsse = _load(DSSE_PATH)
    webauthn = _load(WEBAUTHN_PATH)
    assert dsse["properties"]["algorithm"] == {"const": "Ed25519"}
    assert webauthn["properties"]["algorithm"] == {"const": "ES256"}
    assert webauthn["properties"]["credential_type"] == {"const": "public-key"}
    assert webauthn["properties"]["backup_eligible"] == {"const": False}


def test_rotation_requires_monotonic_continuity_new_material_and_atomic_revocation():
    policy = _load(POLICY_PATH)
    contract = " ".join(policy["rotation_contract"])
    assert "strictly greater than highest accepted epoch" in contract
    assert "predecessor equals highest accepted snapshot digest" in contract
    assert "material digest differs" in contract
    assert "two independent recovery domains" in contract
    assert "same atomic advancement" in contract
    assert "permanently rejected" in contract


def test_no_store_key_parser_rotation_or_crypto_permission_exists():
    dsse = _load(DSSE_PATH)
    webauthn = _load(WEBAUTHN_PATH)
    policy = _load(POLICY_PATH)
    for field in ["public_key_parsing_implemented", "root_store_implemented", "real_root_present", "crypto_call_allowed"]:
        assert dsse[field] is False
    for field in ["cose_key_parsing_implemented", "credential_store_implemented", "real_credential_present", "crypto_call_allowed"]:
        assert webauthn[field] is False
    for field in ["rotation_implemented", "snapshot_store_implemented", "real_snapshot_present", "crypto_call_allowed", "checkpoint_authenticated", "gate_i09_pass", "runtime_integration_allowed"]:
        assert policy[field] is False
