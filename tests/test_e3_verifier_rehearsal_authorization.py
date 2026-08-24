import copy
import hashlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "kairos"))

from app.e3_verifier_rehearsal_authorization import (
    MAX_AUTHORIZATION_MS, authorize_rehearsal, build_owner_approval,
    build_precondition_evidence, validate_owner_approval,
)
from app.e3_verifier_rehearsal_plan import PRECONDITIONS, build_verifier_rehearsal_plan

NOW = 1_800_000_000_000
TARGET = "disposable_host_1"
MANIFEST = ROOT / "kairos/deploy/kairos-independent-verifier.manifest.json"


def plan():
    return build_verifier_rehearsal_plan(
        artifact_manifest_sha256=hashlib.sha256(MANIFEST.read_bytes()).hexdigest())


def approval(value, **changes):
    fields = dict(approval_ref="owner_approval_1", plan_id=value["planId"],
                  target_ref=TARGET, approved_at_epoch_ms=NOW,
                  expires_at_epoch_ms=NOW + MAX_AUTHORIZATION_MS)
    fields.update(changes)
    return build_owner_approval(**fields)


def evidence(value, **outcomes):
    return [build_precondition_evidence(
        plan_id=value["planId"], target_ref=TARGET, check_id=check,
        observed_at_epoch_ms=NOW, outcome=outcomes.get(check, "PASS"),
        evidence_sha256=hashlib.sha256(check.encode()).hexdigest())
        for check in PRECONDITIONS]


def test_exact_bounded_approval_and_all_preconditions_are_eligible_only():
    value = plan()
    receipt = authorize_rehearsal(
        plan=value, target_ref=TARGET, evidence=evidence(value),
        owner_approval=approval(value), assessed_at_epoch_ms=NOW + 1)
    assert receipt["status"] == "ELIGIBLE"
    assert receipt["rehearsalExecutionEligible"] is True
    assert receipt["invocationLimit"] == 1
    assert receipt["productionAllowed"] is False
    assert receipt["credentialsAllowed"] is False
    assert receipt["networkAllowed"] is False
    assert receipt["persistentInstallAllowed"] is False
    assert receipt["readinessCheckSatisfied"] is False
    assert receipt["runtimeEnableAllowed"] is False
    assert receipt["actionAllowed"] is False


def test_each_failed_precondition_is_explicit_no_go():
    value = plan()
    for check in PRECONDITIONS:
        receipt = authorize_rehearsal(
            plan=value, target_ref=TARGET, evidence=evidence(value, **{check: "FAIL"}),
            owner_approval=approval(value), assessed_at_epoch_ms=NOW)
        assert receipt["status"] == "NO_GO"
        assert receipt["blockers"] == [check]


def test_expired_approval_is_no_go_and_lifetime_is_bounded():
    value = plan()
    receipt = authorize_rehearsal(
        plan=value, target_ref=TARGET, evidence=evidence(value),
        owner_approval=approval(value), assessed_at_epoch_ms=NOW + MAX_AUTHORIZATION_MS + 1)
    assert receipt["blockers"] == ["OWNER_APPROVAL_NOT_CURRENT"]
    with pytest.raises(ValueError):
        approval(value, expires_at_epoch_ms=NOW + MAX_AUTHORIZATION_MS + 1)


def test_wrong_target_or_plan_and_duplicate_evidence_fail_closed():
    value = plan()
    with pytest.raises(ValueError):
        authorize_rehearsal(plan=value, target_ref="other_host", evidence=evidence(value),
                            owner_approval=approval(value), assessed_at_epoch_ms=NOW)
    duplicated = evidence(value)
    duplicated[-1] = copy.deepcopy(duplicated[0])
    with pytest.raises(ValueError):
        authorize_rehearsal(plan=value, target_ref=TARGET, evidence=duplicated,
                            owner_approval=approval(value), assessed_at_epoch_ms=NOW)


def test_approval_scope_tamper_cannot_expand_to_production_or_network():
    value = plan()
    approved = approval(value)
    for field in ("productionAllowed", "credentialsAllowed", "networkAllowed",
                  "persistentInstallAllowed", "actionAllowed"):
        changed = copy.deepcopy(approved)
        changed[field] = True
        with pytest.raises(ValueError):
            validate_owner_approval(changed)


def test_contract_has_no_execution_network_filesystem_or_secret_surface():
    source = (ROOT / "kairos/app/e3_verifier_rehearsal_authorization.py").read_text()
    for forbidden in ("open(", "read_text", "subprocess", "systemctl", "useradd",
                      "requests", "httpx", "socket", "os.environ", "apiKey",
                      "apiSecret", "time.time"):
        assert forbidden not in source
