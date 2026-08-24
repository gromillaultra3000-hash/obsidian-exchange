import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
PLAN=json.loads((ROOT/"docs/e0-3-relay-read-authorization-plan.v1.json").read_text())
READS=json.loads((ROOT/"docs/e0-3-relay-read-matrix.v1.json").read_text())


def test_purpose_packages_cover_every_read_method_exactly_once():
 expected={item["id"] for item in READS["reads"]}
 actual=[method for package in PLAN["packages"] for method in package["methods"]]
 assert len(actual)==len(set(actual))==43
 assert set(actual)==expected


def test_login_has_execute_only_target_and_no_union_role_escape():
 decision=PLAN["decision"]
 assert decision["strategy"]=="ONE_BOUNDED_SECURITY_DEFINER_READ_FUNCTION_PER_METHOD"
 assert decision["directTableSelectGrants"]==[]
 assert decision["directColumnSelectGrants"]==[]
 assert decision["inheritedReadRoles"]==[]
 assert decision["publicExecute"] is decision["ownerLogin"] is False
 assert decision["fixedSearchPath"]=="pg_catalog"
 assert decision["schemaQualifiedRelations"] is True


def test_sensitive_returns_remain_blocked_until_closed_contracts():
 blockers={item["method"]:set(item["columns"]) for item in PLAN["sensitiveReturnBlockers"]}
 assert "payment_session_store.latest_for_authorized_order" not in blockers
 assert "payment_session_store.latest_active_for_authorized_order" not in blockers
 assert not blockers
 assert "support_store.thread_for_web_user" not in blockers
 assert PLAN["status"]=="PURPOSE_PARTITION_AND_SIGNATURES_COMPLETE"
 assert PLAN["productionAuthorization"] is PLAN["implementationDeployed"] is False


def test_multi_purpose_methods_are_explicit_and_rollout_is_fail_closed():
 assert {item["method"] for item in PLAN["multiPurposeMethods"]}=={
  "swap_store.get_by_token","order_workflow_store.mark_sent",
 }
 assert PLAN["rolloutOrder"][-1]=="P5_BACKGROUND_STATE_MACHINE"
 assert PLAN["nextPrerequisite"].startswith("rehearse the eight R5 transition writer")
