import hashlib
import json
import re
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "native-wallet/rehearsals/attestation-dependencies/automated-minimal/tests/fixtures"
POLICY_PATH = FIXTURES / "ed25519-corpus-review-audit-retention-policy-v1.json"
RECEIPT_PATH = FIXTURES / "ed25519-corpus-review-deletion-receipt-v1.schema.json"
HEX64 = re.compile(r"^[0-9a-f]{64}$")
IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9._:-]{7,127}$")


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _canonical_digest(receipt: dict) -> str:
    unsigned = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    encoded = json.dumps(unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _synthetic_receipt() -> dict:
    receipt = {
        "schema": "native-wallet-ed25519-corpus-review-deletion-receipt.v1",
        "receipt_id": "deletion-receipt-01",
        "bundle_sha256": "1" * 64,
        "retention_policy_sha256": "2" * 64,
        "workspace_inventory_sha256": "3" * 64,
        "deletion_plan_sha256": "4" * 64,
        "caller_nonce_sha256": "5" * 64,
        "receipt_sha256": "0" * 64,
        "subject_data_class": "external_sensitive_evidence",
        "trigger": "EXPIRED",
        "triggered_at_epoch_ms": 10_000,
        "completed_at_epoch_ms": 11_000,
        "locations_expected": 3,
        "locations_attempted": 3,
        "locations_failed": 0,
        "ordinary_backup_copies_expected": 0,
        "post_deletion_scan_sha256": "6" * 64,
        "executor_domain_id": "executor-domain-a",
        "witness_domain_id": "witness-domain-b",
        "executor_witness_independent": True,
        "outcome": "COMPLETE",
        "physical_erasure_proven": False,
    }
    receipt["receipt_sha256"] = _canonical_digest(receipt)
    return receipt


def _receipt_is_structurally_valid(receipt: dict) -> bool:
    schema = _load(RECEIPT_PATH)
    required = set(schema["required"])
    if set(receipt) != required:
        return False
    if receipt["schema"] != "native-wallet-ed25519-corpus-review-deletion-receipt.v1":
        return False
    if not IDENTIFIER.fullmatch(receipt["receipt_id"]):
        return False
    if any(not HEX64.fullmatch(receipt[field]) for field in [
        "bundle_sha256", "retention_policy_sha256", "workspace_inventory_sha256",
        "deletion_plan_sha256", "caller_nonce_sha256", "post_deletion_scan_sha256",
    ]):
        return False
    if receipt["subject_data_class"] not in {"external_sensitive_evidence", "webauthn_assertion_bytes"}:
        return False
    if receipt["trigger"] not in {"DECISION_FINAL", "EXPIRED", "CONSENT_WITHDRAWN", "INCIDENT"}:
        return False
    if any(
        not isinstance(receipt[field], int) or isinstance(receipt[field], bool) or receipt[field] < 1
        for field in ["triggered_at_epoch_ms", "completed_at_epoch_ms"]
    ) or receipt["completed_at_epoch_ms"] < receipt["triggered_at_epoch_ms"]:
        return False
    if not all(
        isinstance(receipt[field], int) and not isinstance(receipt[field], bool)
        and 1 <= receipt[field] <= 64
        for field in ["locations_expected", "locations_attempted"]
    ):
        return False
    if not isinstance(receipt["locations_failed"], int) or isinstance(receipt["locations_failed"], bool):
        return False
    if not 0 <= receipt["locations_failed"] <= 64:
        return False
    if receipt["outcome"] != "COMPLETE":
        return False
    if receipt["locations_attempted"] != receipt["locations_expected"] or receipt["locations_failed"] != 0:
        return False
    if receipt["ordinary_backup_copies_expected"] != 0:
        return False
    if not all(IDENTIFIER.fullmatch(receipt[field]) for field in ["executor_domain_id", "witness_domain_id"]):
        return False
    if receipt["executor_domain_id"] == receipt["witness_domain_id"]:
        return False
    if receipt["executor_witness_independent"] is not True or receipt["physical_erasure_proven"] is not False:
        return False
    return HEX64.fullmatch(receipt["receipt_sha256"]) is not None and receipt["receipt_sha256"] == _canonical_digest(receipt)


def _receipt_is_consumable(receipt: dict, consumed_receipt_ids: set[str], consumed_nonces: set[str]) -> bool:
    return (
        _receipt_is_structurally_valid(receipt)
        and receipt["receipt_id"] not in consumed_receipt_ids
        and receipt["caller_nonce_sha256"] not in consumed_nonces
    )


def _complete_receipt(receipt: dict) -> bool:
    return (
        receipt.get("outcome") == "COMPLETE"
        and receipt.get("locations_expected", 0) >= 1
        and receipt.get("locations_attempted") == receipt.get("locations_expected")
        and receipt.get("locations_failed") == 0
        and receipt.get("ordinary_backup_copies_expected") == 0
        and receipt.get("executor_domain_id") != receipt.get("witness_domain_id")
        and receipt.get("executor_witness_independent") is True
        and receipt.get("physical_erasure_proven") is False
    )


def test_data_classes_have_closed_storage_and_retention_boundaries():
    policy = _load(POLICY_PATH)
    classes = {item["id"]: item for item in policy["data_classes"]}
    assert set(classes) == {
        "public_contract_material", "hash_only_audit_metadata",
        "external_sensitive_evidence", "webauthn_assertion_bytes", "secrets_and_private_keys",
    }
    assert classes["hash_only_audit_metadata"]["retention_ms"] == 7 * 365 * 24 * 60 * 60 * 1000
    assert classes["external_sensitive_evidence"]["retention_ms"] == 24 * 60 * 60 * 1000
    assert classes["webauthn_assertion_bytes"]["retention_ms"] == 10 * 60 * 1000
    assert classes["secrets_and_private_keys"]["retention_ms"] == 0


def test_audit_allowlist_excludes_identity_credential_content_and_free_text():
    audit = _load(POLICY_PATH)["audit_minimization"]
    assert set(audit["allowed_fields"]) == {
        "event_id", "event_type", "occurred_at_epoch_ms", "actor_domain_id",
        "subject_domain_id", "object_sha256", "policy_sha256", "previous_event_sha256",
        "decision", "reason_code",
    }
    assert {"person_name", "credential_id", "assertion_bytes", "artifact_contents", "free_text"} <= set(audit["forbidden_fields"])
    assert audit["opaque_ids_must_not_embed_personal_data"] is True
    assert audit["free_text_allowed"] is False


def test_deletion_receipt_schema_is_closed_and_claims_no_physical_proof():
    schema = _load(RECEIPT_PATH)
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])
    assert schema["properties"]["physical_erasure_proven"] == {"const": False}
    assert schema["receipt_proves_procedure_not_physical_erasure"] is True
    assert schema["partial_failed_or_unknown_blocks_gate_i09"] is True
    assert schema["single_use_receipt_id_required"] is True
    assert schema["single_use_caller_nonce_required"] is True
    assert schema["replayed_receipt_id_or_caller_nonce_blocks_consumption"] is True
    assert schema["receipt_hash_contract"]["self_digest_binds"] == "all required receipt fields except receipt_sha256"


def test_complete_requires_full_inventory_zero_failures_no_backups_and_witness():
    receipt = {
        "outcome": "COMPLETE", "locations_expected": 3, "locations_attempted": 3,
        "locations_failed": 0, "ordinary_backup_copies_expected": 0,
        "executor_domain_id": "executor-a", "witness_domain_id": "witness-b",
        "executor_witness_independent": True, "physical_erasure_proven": False,
    }
    assert _complete_receipt(receipt)
    mutations = [
        ("outcome", "PARTIAL"), ("locations_attempted", 2), ("locations_failed", 1),
        ("ordinary_backup_copies_expected", 1), ("witness_domain_id", "executor-a"),
        ("executor_witness_independent", False), ("physical_erasure_proven", True),
    ]
    for field, value in mutations:
        changed = deepcopy(receipt)
        changed[field] = value
        assert not _complete_receipt(changed)


def test_external_storage_prevents_repository_and_ordinary_backup_copies():
    policy = _load(POLICY_PATH)
    requirements = " ".join(policy["external_storage_requirements"])
    assert "no ordinary backup or repository synchronization" in requirements
    assert "complete storage-location inventory" in requirements
    assert "automatic expiry plus explicit deletion attempt" in requirements


def test_current_policy_is_not_implemented_and_grants_nothing():
    policy = _load(POLICY_PATH)
    receipt = _load(RECEIPT_PATH)
    for field in ["current_external_workspace_exists", "real_data_present", "policy_implemented", "gate_i09_pass", "selection_allowed", "runtime_integration_allowed"]:
        assert policy[field] is False
    assert receipt["real_receipt_present"] is False
    assert receipt["gate_i09_pass"] is False
    assert receipt["selection_allowed"] is False


def test_receipt_binds_exact_fields_time_order_and_complete_inventory():
    receipt = _synthetic_receipt()
    assert _receipt_is_structurally_valid(receipt)
    mutations = [
        ("bundle_sha256", "a" * 64),
        ("retention_policy_sha256", "b" * 64),
        ("workspace_inventory_sha256", "c" * 64),
        ("deletion_plan_sha256", "d" * 64),
        ("subject_data_class", "webauthn_assertion_bytes"),
        ("trigger", "CONSENT_WITHDRAWN"),
        ("completed_at_epoch_ms", 9_999),
        ("locations_attempted", 2),
        ("locations_failed", 1),
        ("ordinary_backup_copies_expected", 1),
        ("witness_domain_id", "executor-domain-a"),
        ("physical_erasure_proven", True),
    ]
    for field, value in mutations:
        changed = deepcopy(receipt)
        changed[field] = value
        assert not _receipt_is_structurally_valid(changed)


def test_receipt_self_digest_and_single_use_replay_guard_fail_closed():
    receipt = _synthetic_receipt()
    assert _receipt_is_consumable(receipt, set(), set())
    assert not _receipt_is_consumable(receipt, {receipt["receipt_id"]}, set())
    assert not _receipt_is_consumable(receipt, set(), {receipt["caller_nonce_sha256"]})
    changed = deepcopy(receipt)
    changed["locations_expected"] = 4
    assert not _receipt_is_structurally_valid(changed)
    changed["receipt_sha256"] = _canonical_digest(changed)
    assert not _receipt_is_structurally_valid(changed)
