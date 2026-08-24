import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
PLAN=json.loads((ROOT/"docs/e0-3-relay-acl-plan.v1.json").read_text())
WRITERS=json.loads((ROOT/"docs/e0-3-relay-writer-matrix.v1.json").read_text())


def test_plan_is_nonproduction_and_fail_closed_on_read_columns_and_signatures():
    assert PLAN["status"]=="IN_PROGRESS"
    assert PLAN["productionAuthorization"] is PLAN["implementationDeployed"] is False
    assert PLAN["readAuthorization"]["status"]=="ALL_43_BODIES_REHEARSED"
    assert PLAN["readAuthorization"]["strategy"]=="ONE_BOUNDED_SECURITY_DEFINER_READ_FUNCTION_PER_METHOD"
    assert PLAN["readAuthorization"]["directColumnSelectGrants"]==[]
    assert PLAN["readAuthorization"]["inheritedReadRoles"]==[]
    assert PLAN["readAuthorization"]["columnEvidence"]=="docs/e0-3-relay-read-matrix.v1.json"
    assert PLAN["readAuthorization"]["directTableSelectGrants"]==[]
    assert PLAN["writerAuthorization"]["signatureStatus"]==(
        "ALL_26_WRITER_BODIES_REHEARSED_PROPOSAL_ONLY"
    )


def test_every_writer_is_in_exactly_one_ordered_package():
    expected={item["id"] for item in WRITERS["writers"]}
    flattened=[writer for package in PLAN["packages"] for writer in package["writers"]]
    assert len(flattened)==len(set(flattened))==26
    assert set(flattened)==expected
    assert PLAN["rolloutOrder"]==[package["id"] for package in PLAN["packages"]]


def test_target_roles_and_ambient_policy_are_least_privilege():
    roles=PLAN["roles"]
    assert roles["login"]=="obsidian_relay"
    assert roles["functionOwner"]=="obsidian_relay_owner"
    assert roles["functionOwnerLogin"] is False
    assert all(roles[key] is False for key in ("inherit","superuser","createDb","createRole","replication","bypassRls"))
    assert roles["connectionLimitStatus"]=="REHEARSED_DISPOSABLE_POSTGRESQL_17"
    assert roles["connectionLimit"]==12
    required={"PUBLIC_CONNECT_TEMP_SCHEMA_FUNCTION_REVOKED","NO_DIRECT_TABLE_DML","NO_DIRECT_SEQUENCE_ACCESS","FIXED_PG_CATALOG_SEARCH_PATH"}
    assert required <= set(PLAN["ambientPolicy"])


def test_writer_authority_is_execute_only_after_body_rehearsal():
    auth=PLAN["writerAuthorization"]
    assert auth["strategy"]=="ONE_SECURITY_DEFINER_FUNCTION_PER_WRITER_METHOD"
    assert auth["directRelationPrivileges"]==auth["directSequencePrivileges"]==[]
    assert auth["publicExecute"] is False
    acceptance=set(PLAN["functionAcceptance"])
    assert "all writer-matrix invariants enforced inside one transaction" in acceptance
    assert "malicious input and concurrent/fault rollback tests" in acceptance


def test_money_transitions_are_late_and_settlement_is_last():
    packages={item["id"]:item["writers"] for item in PLAN["packages"]}
    assert "payment_transition_store.mark_paid" in packages["R5_ORDER_SESSION_SWAP_PAYOUT_METADATA_TRANSITIONS"]
    assert "user_profile_store.set_referral_address" in packages["R5_ORDER_SESSION_SWAP_PAYOUT_METADATA_TRANSITIONS"]
    assert packages["R6_SELL_SETTLEMENT"]==["sell_settlement_store.settle_vertu"]
    assert PLAN["roles"]["connectionLimit"]==12
    assert PLAN["roles"]["connectionLimitStatus"]=="REHEARSED_DISPOSABLE_POSTGRESQL_17"
    assert PLAN["nextPrerequisite"].startswith("build the exact exchange-bot caller")
