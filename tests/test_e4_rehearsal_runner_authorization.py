import copy
import hashlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "relay"))

from core.e4_rehearsal_runner_authorization import (
    MAX_AUTHORIZATION_MS, MAX_EVIDENCE_AGE_MS, authorize_rehearsal_runner,
    build_owner_approval, build_precondition_evidence,
    validate_authorization_receipt, validate_owner_approval,
)
from core.e4_rehearsal_runner_plan import PRECONDITIONS, build_rehearsal_runner_plan

NOW = 1_800_000_000_000
TARGET = "e4_disposable_pg_1"
TARGET_DIGEST = "1" * 64
SNAPSHOT = "2" * 64
MANIFEST = ROOT / "deploy/postgres/proposals/e4_full_snapshot_rehearsal_manifest.json"


def plan():
    return build_rehearsal_runner_plan(
        evidence_manifest_sha256=hashlib.sha256(MANIFEST.read_bytes()).hexdigest())


def approval(value, **changes):
    fields = dict(
        approval_ref="owner_approval_e4_1", plan_id=value["planId"],
        target_ref=TARGET, target_fingerprint_sha256=TARGET_DIGEST,
        snapshot_sha256=SNAPSHOT,
        snapshot_ref_sha256=hashlib.sha256(b"snapshot_ref_1").hexdigest(),
        key_ref_sha256=hashlib.sha256(b"key_handle_1").hexdigest(),
        approved_at_epoch_ms=NOW,
        expires_at_epoch_ms=NOW + MAX_AUTHORIZATION_MS)
    fields.update(changes)
    return build_owner_approval(**fields)


def evidence(value, *, observed=NOW, **outcomes):
    return [build_precondition_evidence(
        plan_id=value["planId"], target_ref=TARGET,
        target_fingerprint_sha256=TARGET_DIGEST, snapshot_sha256=SNAPSHOT,
        check_id=check, observed_at_epoch_ms=observed,
        outcome=outcomes.get(check, "PASS"),
        evidence_sha256=hashlib.sha256(check.encode()).hexdigest())
        for check in PRECONDITIONS]


def authorize(value, items=None, approved=None, assessed=NOW + 1, **changes):
    args = dict(plan=value, target_ref=TARGET,
                target_fingerprint_sha256=TARGET_DIGEST, snapshot_sha256=SNAPSHOT,
                evidence=items if items is not None else evidence(value),
                owner_approval=approved if approved is not None else approval(value),
                assessed_at_epoch_ms=assessed)
    args.update(changes)
    return authorize_rehearsal_runner(**args)


def test_exact_current_evidence_and_approval_are_eligible_for_one_invocation_only():
    assert MAX_AUTHORIZATION_MS == 30 * 60 * 1000
    receipt = authorize(plan())
    assert receipt["status"] == "ELIGIBLE"
    assert receipt["rehearsalExecutionEligible"] is True
    assert receipt["invocationLimit"] == 1 and receipt["blockers"] == []
    assert receipt["executionEffect"] == "NONE"
    assert validate_authorization_receipt(receipt) == receipt
    for field in ("productionDatabaseContactAllowed", "productionNetworkAllowed",
                  "productionCredentialsAllowed", "proposalApplicationAllowed",
                  "persistentTargetAllowed", "automaticRetryAllowed",
                  "promotionAllowed", "actionAllowed"):
        assert receipt[field] is False


def test_owner_approved_thirty_minute_window_is_a_hard_upper_bound():
    value = plan()
    assert approval(value)["expiresAtEpochMs"] == NOW + 30 * 60 * 1000
    with pytest.raises(ValueError, match="lifetime"):
        approval(value, expires_at_epoch_ms=NOW + MAX_AUTHORIZATION_MS + 1)


def test_each_failed_precondition_is_explicit_no_go():
    value = plan()
    for check in PRECONDITIONS:
        receipt = authorize(value, items=evidence(value, **{check: "FAIL"}))
        assert receipt["status"] == "NO_GO" and receipt["blockers"] == [check]


def test_stale_future_or_expired_inputs_fail_closed():
    value = plan()
    stale = authorize(value, items=evidence(value, observed=NOW-MAX_EVIDENCE_AGE_MS-1))
    assert len(stale["blockers"]) == len(PRECONDITIONS)
    future = authorize(value, items=evidence(value, observed=NOW+2_000), assessed=NOW)
    assert all(item.endswith("_FROM_FUTURE") for item in future["blockers"])
    expired = authorize(value, assessed=NOW + MAX_AUTHORIZATION_MS + 1)
    assert "OWNER_APPROVAL_NOT_CURRENT" in expired["blockers"]


def test_plan_target_snapshot_and_fingerprint_drift_are_rejected():
    value = plan()
    with pytest.raises(ValueError, match="binding"):
        authorize(value, snapshot_sha256="3" * 64)
    changed = evidence(value); changed[0] = copy.deepcopy(changed[0])
    changed[0]["targetRef"] = "other_target"
    with pytest.raises(ValueError):
        authorize(value, items=changed)


def test_duplicate_or_missing_evidence_is_rejected():
    value = plan(); items = evidence(value)
    with pytest.raises(ValueError, match="incomplete or duplicated"):
        authorize(value, items=items[:-1])
    with pytest.raises(ValueError, match="incomplete or duplicated"):
        authorize(value, items=items[:-1] + [items[0]])


def test_approval_tamper_cannot_expand_scope():
    value = plan(); approved = approval(value)
    for field in ("productionDatabaseContactAllowed", "productionNetworkAllowed",
                  "productionCredentialsAllowed", "proposalApplicationAllowed",
                  "persistentTargetAllowed", "automaticRetryAllowed",
                  "promotionAllowed", "actionAllowed"):
        changed = copy.deepcopy(approved); changed[field] = True
        with pytest.raises(ValueError):
            validate_owner_approval(changed)


def test_receipt_tamper_cannot_claim_eligibility_scope_or_effect():
    receipt = authorize(plan())
    for field, replacement in (
        ("status", "NO_GO"), ("rehearsalExecutionEligible", False),
        ("productionDatabaseContactAllowed", True), ("promotionAllowed", True),
        ("actionAllowed", True), ("executionEffect", "DATABASE_WRITE"),
        ("receiptId", "e4rrar_" + "0" * 64),
    ):
        changed = copy.deepcopy(receipt); changed[field] = replacement
        with pytest.raises(ValueError):
            validate_authorization_receipt(changed)


def test_contract_has_no_execution_database_network_filesystem_or_secret_surface():
    source = (ROOT / "relay/core/e4_rehearsal_runner_authorization.py").read_text()
    for forbidden in ("open(", "read_text", "read_bytes", "psycopg", "sqlite",
                      "subprocess", "docker", "systemctl", "requests", "httpx",
                      "socket", "os.environ", "password", "apiKey", "time.time"):
        assert forbidden not in source
