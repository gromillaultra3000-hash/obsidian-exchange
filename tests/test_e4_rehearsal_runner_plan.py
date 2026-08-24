import copy
import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "relay"))

from core.e4_rehearsal_runner_plan import (
    PRECONDITIONS, STEPS, build_rehearsal_runner_plan,
    validate_rehearsal_runner_plan,
)

MANIFEST = ROOT / "deploy/postgres/proposals/e4_full_snapshot_rehearsal_manifest.json"


def plan():
    return build_rehearsal_runner_plan(
        evidence_manifest_sha256=hashlib.sha256(MANIFEST.read_bytes()).hexdigest())


def test_plan_is_single_use_owner_gated_isolated_and_non_executing():
    value = plan()
    assert value["targetClass"] == "ISOLATED_DISPOSABLE_POSTGRESQL"
    assert value["invocationLimit"] == 1 and value["ownerApprovalRequired"] is True
    assert [item["checkId"] for item in value["preconditions"]] == list(PRECONDITIONS)
    assert [item["stepId"] for item in value["steps"]] == [item[0] for item in STEPS]
    assert value["executionAuthorized"] is False
    assert value["executionEffect"] == "NONE"
    assert value["promotionAllowed"] is value["actionAllowed"] is False
    assert validate_rehearsal_runner_plan(json.loads(json.dumps(value))) == value


def test_only_fixture_load_may_write_and_post_load_inspection_is_read_only():
    value = plan()
    effects = {item["stepId"]: item["effect"] for item in value["steps"]}
    assert effects["LOAD_SNAPSHOT_INTO_DISPOSABLE_TARGET"] == "BOUNDED_FIXTURE_MUTATION"
    read_steps = ["VERIFY_FULL_SNAPSHOT_MATCH", "CAPTURE_TABLE_INVENTORY",
                  "CAPTURE_ACL_INVENTORY", "VERIFY_ROUTE_GATES_AND_MIGRATION_ABSENCE",
                  "NORMALIZE_SECRET_FREE_EVIDENCE"]
    assert all(effects[item] == "READ_ONLY" for item in read_steps)
    assert value["postLoadWritesAllowed"] is False
    assert value["proposalApplicationAllowed"] is False


def test_teardown_is_mandatory_and_final_absence_check_is_last():
    steps = [item["stepId"] for item in plan()["steps"]]
    assert steps[-2:] == ["DESTROY_DISPOSABLE_TARGET_AND_STAGED_SNAPSHOT",
                          "VERIFY_TARGET_AND_SNAPSHOT_ABSENT"]
    assert steps.index("NORMALIZE_SECRET_FREE_EVIDENCE") < steps.index(
        "DESTROY_DISPOSABLE_TARGET_AND_STAGED_SNAPSHOT")


@pytest.mark.parametrize("field", [
    "productionDatabaseContactAllowed", "productionNetworkAllowed",
    "productionCredentialsAllowed", "proposalApplicationAllowed",
    "postLoadWritesAllowed", "persistentTargetAllowed", "automaticRetryAllowed",
    "executionAuthorized", "containsConnectionMaterial", "promotionAllowed",
    "actionAllowed",
])
def test_tamper_cannot_expand_scope_or_authorize_execution(field):
    changed = copy.deepcopy(plan()); changed[field] = True
    with pytest.raises(ValueError):
        validate_rehearsal_runner_plan(changed)


def test_step_or_precondition_drift_fails_closed():
    for field in ("steps", "preconditions"):
        changed = copy.deepcopy(plan()); changed[field].pop()
        with pytest.raises(ValueError):
            validate_rehearsal_runner_plan(changed)


def test_plan_has_no_execution_database_network_filesystem_or_secret_surface():
    source = (ROOT / "relay/core/e4_rehearsal_runner_plan.py").read_text()
    for forbidden in ("open(", "read_text", "read_bytes", "psycopg", "sqlite",
                      "subprocess", "docker", "systemctl", "requests", "httpx",
                      "socket", "os.environ", "password", "apiKey", "time.time"):
        assert forbidden not in source
