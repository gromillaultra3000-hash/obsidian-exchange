import copy
import hashlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "relay"))

from core.e4_rehearsal_runner_authorization import (  # noqa: E402
    MAX_AUTHORIZATION_MS, PRECONDITIONS, authorize_rehearsal_runner,
    build_owner_approval, build_precondition_evidence,
)
from core.e4_rehearsal_runner_boundary import (  # noqa: E402
    POSTGRES_IMAGE, build_runner_boundary, target_spec_fingerprint,
    target_spec, validate_runner_boundary,
)
from core.e4_rehearsal_runner_plan import build_rehearsal_runner_plan  # noqa: E402

NOW = 1_800_000_000_000
TARGET = "e4-disposable-pg-1"
TARGET_DIGEST = target_spec_fingerprint(target_ref=TARGET)
SNAPSHOT = "2" * 64
MANIFEST = ROOT / "deploy/postgres/proposals/e4_full_snapshot_rehearsal_manifest.json"


def plan():
    return build_rehearsal_runner_plan(
        evidence_manifest_sha256=hashlib.sha256(MANIFEST.read_bytes()).hexdigest())


def receipt(value, *, failed=None):
    approval = build_owner_approval(
        approval_ref="owner_approval_e4_boundary_1", plan_id=value["planId"],
        target_ref=TARGET, target_fingerprint_sha256=TARGET_DIGEST,
        snapshot_sha256=SNAPSHOT,
        snapshot_ref_sha256=hashlib.sha256(b"snapshot_ref_1").hexdigest(),
        key_ref_sha256=hashlib.sha256(b"key_handle_1").hexdigest(),
        approved_at_epoch_ms=NOW,
        expires_at_epoch_ms=NOW + MAX_AUTHORIZATION_MS)
    evidence = [build_precondition_evidence(
        plan_id=value["planId"], target_ref=TARGET,
        target_fingerprint_sha256=TARGET_DIGEST, snapshot_sha256=SNAPSHOT,
        check_id=check, observed_at_epoch_ms=NOW,
        outcome="FAIL" if check == failed else "PASS",
        evidence_sha256=hashlib.sha256(check.encode()).hexdigest())
        for check in PRECONDITIONS]
    return authorize_rehearsal_runner(
        plan=value, target_ref=TARGET, target_fingerprint_sha256=TARGET_DIGEST,
        snapshot_sha256=SNAPSHOT, evidence=evidence,
        owner_approval=approval, assessed_at_epoch_ms=NOW + 1)


def boundary():
    value = plan()
    return value, receipt(value), build_runner_boundary(
        plan=value, receipt=receipt(value), snapshot_ref="snapshot_ref_1",
        key_ref="key_handle_1")


def test_boundary_is_pinned_to_one_networkless_fixture_and_teardown():
    value, approved, result = boundary()
    assert result["rehearsalInvocationAllowed"] is True
    assert result["moneyActionAllowed"] is False
    assert result["executionEffect"] == "NONE"
    assert result["target"] == target_spec(target_ref=TARGET)
    assert result["target"]["image"] == POSTGRES_IMAGE
    assert result["target"]["network"] == "none"
    assert result["target"]["readOnlyRoot"] is True
    assert result["target"]["persistentVolume"] is False
    assert result["target"]["publishedPorts"] is False
    assert [item["operation"] for item in result["phases"]] == [
        "VERIFY_TARGET_ABSENT", "CREATE_DISPOSABLE_POSTGRESQL_TARGET",
        "LOAD_ENCRYPTED_SNAPSHOT", "REVOKE_POST_LOAD_WRITE_CAPABILITY",
        "COLLECT_SECRET_FREE_READ_ONLY_EVIDENCE",
        "DESTROY_DISPOSABLE_TARGET_AND_STAGED_SNAPSHOT",
        "VERIFY_TARGET_AND_SNAPSHOT_ABSENT",
    ]
    assert validate_runner_boundary(
        result, plan=value, receipt=approved,
        snapshot_ref="snapshot_ref_1", key_ref="key_handle_1") == result


def test_target_fingerprint_is_deterministic_and_ref_bound():
    assert target_spec_fingerprint(target_ref=TARGET) == TARGET_DIGEST
    assert target_spec_fingerprint(target_ref="e4-disposable-pg-2") != TARGET_DIGEST
    with pytest.raises(ValueError):
        target_spec(target_ref="obsidian-postgres")


def test_signed_digest_refs_do_not_expose_snapshot_or_ssh_key_names():
    value = plan()
    approved = receipt(value)
    snapshot_digest_ref = "sha256_" + approved["snapshotRefSha256"]
    key_digest_ref = "sha256_" + approved["keyRefSha256"]
    result = build_runner_boundary(
        plan=value, receipt=approved, snapshot_ref=snapshot_digest_ref,
        key_ref=key_digest_ref)
    assert result["phases"][2]["snapshotRef"] == snapshot_digest_ref
    assert result["phases"][2]["keyRef"] == key_digest_ref
    assert "ssh-ed25519" not in str(result)
    with pytest.raises(ValueError, match="references"):
        build_runner_boundary(
            plan=value, receipt=approved, snapshot_ref="snapshot_ref_1",
            key_ref="sha256_" + "f" * 64)


def test_boundary_requires_eligible_receipt_and_exact_target_fingerprint():
    value = plan()
    rejected = receipt(value, failed=PRECONDITIONS[0])
    with pytest.raises(ValueError, match="eligible"):
        build_runner_boundary(plan=value, receipt=rejected,
                              snapshot_ref="snapshot_ref_1", key_ref="key_handle_1")
    changed = copy.deepcopy(receipt(value))
    changed["targetFingerprintSha256"] = "f" * 64
    with pytest.raises(ValueError):
        build_runner_boundary(plan=value, receipt=changed,
                              snapshot_ref="snapshot_ref_1", key_ref="key_handle_1")


@pytest.mark.parametrize("field", ["snapshotRef", "keyRef"])
def test_secret_or_path_like_refs_are_rejected(field):
    value, approved, _ = boundary()
    kwargs = {"snapshot_ref": "snapshot_ref_1", "key_ref": "key_handle_1"}
    kwargs["snapshot_ref" if field == "snapshotRef" else "key_ref"] = "/tmp/secret"
    with pytest.raises(ValueError):
        build_runner_boundary(plan=value, receipt=approved, **kwargs)


def test_boundary_tamper_cannot_change_phase_scope():
    value, approved, result = boundary()
    changed = copy.deepcopy(result)
    changed["target"]["network"] = "host"
    with pytest.raises(ValueError):
        validate_runner_boundary(
            changed, plan=value, receipt=approved,
            snapshot_ref="snapshot_ref_1", key_ref="key_handle_1")
    changed = copy.deepcopy(result)
    changed["phases"][1]["argv"].append("-p")
    with pytest.raises(ValueError):
        validate_runner_boundary(
            changed, plan=value, receipt=approved,
            snapshot_ref="snapshot_ref_1", key_ref="key_handle_1")


def test_boundary_has_no_runtime_or_production_connection_surface():
    source = (ROOT / "relay/core/e4_rehearsal_runner_boundary.py").read_text()
    for forbidden in (
        "subprocess", "os.environ", "psycopg", "sqlite", "requests", "httpx",
        "socket", "systemctl", "obsidian-postgres", "DATABASE_URL",
    ):
        assert forbidden not in source
