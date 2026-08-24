import hashlib
import json
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "native-wallet/rehearsals/attestation-dependencies/automated-minimal/tests/fixtures"
CONTRACT_PATH = FIXTURES / "ed25519-corpus-review-checkpoint-auth-challenge-v1.json"
VECTOR_PATH = FIXTURES / "ed25519-corpus-review-checkpoint-auth-challenge-vector-v1.json"


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


def _optional_digest(value: str | None) -> bytes:
    return b"\x00" + bytes(32) if value is None else b"\x01" + _digest(value)


def _challenge(inputs: dict) -> str:
    slot = inputs["witness_slot"]
    if slot not in {0, 1}:
        raise ValueError("witness slot must be 0 or 1")
    parts = [
        _field("obsidian.ed25519-review.audit-checkpoint-auth.v1"),
        _digest(inputs["checkpoint_schema_sha256"]),
        _digest(inputs["exact_checkpoint_bytes_sha256"]),
        _field(inputs["chain_id"]), _digest(inputs["policy_sha256"]),
        inputs["audit_sequence"].to_bytes(8, "big"),
        _digest(inputs["audit_head_sha256"]),
        _optional_digest(inputs["previous_checkpoint_sha256"]),
        inputs["checkpoint_epoch"].to_bytes(8, "big"),
        _digest(inputs["caller_nonce_sha256"]),
        inputs["issued_at_epoch_ms"].to_bytes(8, "big"),
        inputs["expires_at_epoch_ms"].to_bytes(8, "big"),
        bytes([slot]), _field(inputs["witness_domain_id"]),
        _digest(inputs["authentication_root_sha256"]),
        _field(inputs["recovery_authority_id"]),
        _field(inputs["host_failure_domain_id"]),
    ]
    return hashlib.sha256(b"".join(parts)).hexdigest()


def test_fixed_vector_matches_exact_ordered_preimage():
    vector = _load(VECTOR_PATH)
    assert _challenge(vector["inputs"]) == vector["expected_challenge_sha256"]


def test_every_field_mutation_changes_challenge():
    inputs = _load(VECTOR_PATH)["inputs"]
    exact = _challenge(inputs)
    for field, value in inputs.items():
        changed = deepcopy(inputs)
        if value is None:
            changed[field] = "8" * 64
        elif field == "witness_slot":
            changed[field] = 1
        elif isinstance(value, int):
            changed[field] = value + 1
        elif field.endswith("sha256"):
            changed[field] = "8" * 64
        else:
            changed[field] = f"{value}x"
        assert _challenge(changed) != exact


def test_witness_slots_are_non_interchangeable_and_closed():
    inputs = _load(VECTOR_PATH)["inputs"]
    slot_zero = _challenge(inputs)
    slot_one_inputs = deepcopy(inputs)
    slot_one_inputs["witness_slot"] = 1
    assert _challenge(slot_one_inputs) != slot_zero
    for invalid in [-1, 2, 255]:
        changed = deepcopy(inputs)
        changed["witness_slot"] = invalid
        try:
            _challenge(changed)
        except ValueError:
            pass
        else:
            raise AssertionError(f"accepted witness slot {invalid}")


def test_genesis_predecessor_has_unique_zero_encoding():
    inputs = _load(VECTOR_PATH)["inputs"]
    non_genesis = _challenge(inputs)
    genesis = deepcopy(inputs)
    genesis["previous_checkpoint_sha256"] = None
    assert _challenge(genesis) != non_genesis
    zero_digest = deepcopy(inputs)
    zero_digest["previous_checkpoint_sha256"] = "0" * 64
    assert _challenge(genesis) != _challenge(zero_digest)


def test_candidate_mapping_preserves_exact_bytes_and_raw_challenge():
    contract = _load(CONTRACT_PATH)
    mapping = contract["candidate_mapping"]
    assert "DSSE signs exact statement bytes" in mapping["dual_dsse_offline_witnesses"]
    assert "raw 32-byte slot-specific challenge" in mapping["dual_webauthn_human_witnesses"]
    assert contract["slot_swap_allowed"] is False
    assert contract["challenge_reuse_across_chain_policy_epoch_or_witness_allowed"] is False


def test_hash_only_contract_grants_nothing():
    contract = _load(CONTRACT_PATH)
    for field in ["signature_or_assertion_decoding_implemented", "witness_enrolled", "real_authentication_evidence_present", "checkpoint_authentication_allowed", "gate_i09_pass", "runtime_integration_allowed"]:
        assert contract[field] is False
