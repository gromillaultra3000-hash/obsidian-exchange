import copy
import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "kairos"))

from app.e3_verifier_rehearsal_plan import (
    PRECONDITIONS, STEPS, build_verifier_rehearsal_plan,
    validate_verifier_rehearsal_plan,
)

MANIFEST_PATH = ROOT / "kairos/deploy/kairos-independent-verifier.manifest.json"


def plan():
    return build_verifier_rehearsal_plan(
        artifact_manifest_sha256=hashlib.sha256(MANIFEST_PATH.read_bytes()).hexdigest())


def test_plan_is_isolated_reversible_non_executing_and_owner_gated():
    value = plan()
    assert value["targetClass"] == "DISPOSABLE_ISOLATED_NON_PRODUCTION_HOST"
    assert [item["checkId"] for item in value["preconditions"]] == list(PRECONDITIONS)
    assert [item["stepId"] for item in value["steps"]] == [item[0] for item in STEPS]
    assert all(item["automaticRetryAllowed"] is False for item in value["steps"])
    assert value["productionAllowed"] is False
    assert value["credentialsAllowed"] is False
    assert value["networkAllowed"] is False
    assert value["persistentInstallAllowed"] is False
    assert value["executionAuthorized"] is False
    assert value["runtimeEnableAllowed"] is False
    assert value["actionAllowed"] is False
    assert validate_verifier_rehearsal_plan(json.loads(json.dumps(value))) == value


def test_rollback_is_mandatory_and_finishes_with_absence_verification():
    steps = [item["stepId"] for item in plan()["steps"]]
    assert steps[-3:] == ["REMOVE_INPUT_AND_ARTIFACTS", "REMOVE_SERVICE_IDENTITY",
                          "VERIFY_TARGET_ABSENT_AFTER_ROLLBACK"]
    assert steps.index("VERIFY_TARGET_ABSENT") < steps.index("CREATE_NON_LOGIN_IDENTITY")
    assert steps.index("COLLECT_SECRET_FREE_MEASUREMENT") < steps.index(
        "REMOVE_INPUT_AND_ARTIFACTS")


@pytest.mark.parametrize("field", [
    "productionAllowed", "credentialsAllowed", "networkAllowed",
    "persistentInstallAllowed", "executionAuthorized", "runtimeEnableAllowed",
    "actionAllowed",
])
def test_plan_tamper_cannot_authorize_execution_or_expand_scope(field):
    changed = copy.deepcopy(plan())
    changed[field] = True
    with pytest.raises(ValueError):
        validate_verifier_rehearsal_plan(changed)


def test_plan_step_or_precondition_removal_fails_closed():
    for field in ("steps", "preconditions"):
        changed = copy.deepcopy(plan())
        changed[field].pop()
        with pytest.raises(ValueError):
            validate_verifier_rehearsal_plan(changed)


def test_plan_contract_has_no_execution_filesystem_network_or_secret_surface():
    source = (ROOT / "kairos/app/e3_verifier_rehearsal_plan.py").read_text()
    for forbidden in ("open(", "read_text", "read_bytes", "subprocess", "systemctl",
                      "useradd", "install ", "requests", "httpx", "socket",
                      "os.environ", "apiKey", "apiSecret", "time.time"):
        assert forbidden not in source
