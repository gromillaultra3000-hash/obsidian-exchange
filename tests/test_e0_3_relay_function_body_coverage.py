import hashlib
import json
from pathlib import Path


ROOT=Path(__file__).resolve().parents[1]
C=json.loads((ROOT/"docs/e0-3-relay-function-body-coverage.v1.json").read_text())
CONTRACTS=json.loads((ROOT/"docs/e0-3-relay-read-contracts.v1.json").read_text())
PLAN=json.loads((ROOT/"docs/e0-3-relay-read-authorization-plan.v1.json").read_text())


def test_coverage_arithmetic_is_exact_and_truthfully_partial():
 assert C["totals"]=={"readBodies":43,"writerBodies":26,"allBodies":69}
 assert C["completed"]=={"readBodies":43,"writerBodies":26,"allBodies":69}
 assert C["remaining"]=={"readBodies":0,"writerBodies":0,"allBodies":0}
 assert C["status"]=="RELAY_BODIES_69_OF_69_REHEARSED_E0_3_IN_PROGRESS"
 assert C["productionAuthorization"] is C["implementationDeployed"] is False


def test_completed_ids_are_exactly_rehearsed_contracts():
 packages={p["id"]:set(p["methods"]) for p in PLAN["packages"]}
 expected=(packages["P7_RUNTIME_METADATA"]|packages["P1_PUBLIC_AGGREGATES"]
           |packages["P2_CUSTOMER_SCOPED"]|packages["P3_INTERACTIVE_ORDER_PAYMENT"]
             |packages["P6_PROVIDER_CALLBACK"]|packages["P4_OPERATOR_REPORTING"]
             |{"order_lifecycle_store.claim_work","payment_session_store.pending_vertu",
               "payment_transition_store.claim_notification","sell_order_store.active_vertu_payouts",
               "sell_settlement_store.claim_notification","support_store.user_reply",
               "order_lifecycle_store.expire_due","order_lifecycle_store.fail_session",
               "order_workflow_store.mark_sent","payment_transition_store.mark_paid",
               "sell_settlement_store.settle_vertu"})
 assert set(C["completedReadIds"])==expected
 assert set(C["completedReadIds"])<={x["id"] for x in CONTRACTS["contracts"]}
 assert set(C["completedWriterIds"])=={
  "ops_store.audit","support_store.create","support_store.user_reply",
  "order_lifecycle_store.claim_work","order_lifecycle_store.complete_work",
  "order_lifecycle_store.retry_work","payment_transition_store.claim_notification",
  "payment_transition_store.mark_notification_sent","payment_transition_store.retry_notification",
  "sell_settlement_store.claim_notification","sell_settlement_store.mark_notification_sent",
  "admin_config_store.block_user","admin_config_store.unblock_user","ops_store.cleanup_audit",
  "order_creation_store.create","sell_order_store.create","swap_store.create",
  "order_workflow_store.request_verification","sell_order_store.cancel_pending",
  "swap_store.transition","user_profile_store.set_referral_address",
  "order_lifecycle_store.expire_due","order_lifecycle_store.fail_session",
  "order_workflow_store.mark_sent","payment_transition_store.mark_paid",
  "sell_settlement_store.settle_vertu",
 }


def test_rehearsal_is_bound_to_exact_proposal_and_runner():
 assert len(C["rehearsals"])==13
 for item in C["rehearsals"]:
  for path_key,hash_key in (("proposal","proposalSha256"),("runner","runnerSha256")):
   path=ROOT/item[path_key]
   assert hashlib.sha256(path.read_bytes()).hexdigest()==item[hash_key]
  assert item["containerRemovedAfterRun"] is True
  assert item["productionDatabaseTouched"] is False
  assert len(item["assertions"]) in {8,9}


def test_metadata_correction_preserves_no_business_select_boundary():
 correction=C["designCorrections"][0]
 assert "information_schema.columns is privilege-filtered" in correction
 proposal=(ROOT/C["rehearsals"][0]["proposal"]).read_text()
 assert "pg_catalog.pg_attribute" in proposal
 assert "metadata_owner_business_select" in proposal
 assert proposal.count("SECURITY DEFINER")==5
 p2=(ROOT/C["rehearsals"][1]["proposal"]).read_text()
 assert "relay_order_receipt_order_ids(bigint[],bigint,bigint)" in p2
 assert p2.count("SECURITY DEFINER")==12


def test_p3_is_complete_after_atomic_authority_refactor():
 p3=next(p for p in C["packages"] if p["id"]=="P3_INTERACTIVE_ORDER_PAYMENT")
 assert p3=={"id":"P3_INTERACTIVE_ORDER_PAYMENT","status":"REHEARSED",
            "completed":8,"total":8}
 assert C["authorizationBlockers"]==[]
 proposal=(ROOT/C["rehearsals"][3]["proposal"]).read_text()
 assert proposal.count("SECURITY DEFINER")==6
 assert "order_id-only" in C["authorizationRefactors"][0]
 assert C["supersededRehearsalOnlyFunction"].startswith(
  "relay_payment_session_token_matches_order")


def test_p6_is_complete_with_unique_provider_scoped_correlation():
 p6=next(p for p in C["packages"] if p["id"]=="P6_PROVIDER_CALLBACK")
 assert p6=={"id":"P6_PROVIDER_CALLBACK","status":"REHEARSED",
            "completed":3,"total":3}
 proposal=(ROOT/C["rehearsals"][4]["proposal"]).read_text()
 assert proposal.count("SECURITY DEFINER")==3
 assert "payout_provider='vertu'" in proposal
 assert "count(c.id)" in proposal


def test_p4_is_complete_with_bounded_utc_operator_reporting():
 p4=next(p for p in C["packages"] if p["id"]=="P4_OPERATOR_REPORTING")
 assert p4=={"id":"P4_OPERATOR_REPORTING","status":"REHEARSED",
            "completed":4,"total":4}
 proposal=(ROOT/C["rehearsals"][5]["proposal"]).read_text()
 assert proposal.count("SECURITY DEFINER")==4
 assert "SET TimeZone='UTC'" in proposal
 assert "LIMIT 64" in proposal and "LIMIT 20" in proposal


def test_p5_reads_are_complete_but_not_writer_completion():
 p5=next(p for p in C["packages"] if p["id"]=="P5_BACKGROUND_STATE_MACHINE_READS")
 assert p5=={"id":"P5_BACKGROUND_STATE_MACHINE_READS","status":"REHEARSED",
            "completed":11,"total":11}
 proposal=(ROOT/C["rehearsals"][6]["proposal"]).read_text()
 assert proposal.count("SECURITY DEFINER")==5
 assert proposal.count("SKIP LOCKED")==3
 p5b=(ROOT/C["rehearsals"][7]["proposal"]).read_text()
 assert p5b.count("SECURITY DEFINER")==6
 assert "ON CONFLICT ON CONSTRAINT user_vip_volume_pkey" in p5b
 assert set(C["completedWriterIds"])=={
  "ops_store.audit","support_store.create","support_store.user_reply",
  "order_lifecycle_store.claim_work","order_lifecycle_store.complete_work",
  "order_lifecycle_store.retry_work","payment_transition_store.claim_notification",
  "payment_transition_store.mark_notification_sent","payment_transition_store.retry_notification",
  "sell_settlement_store.claim_notification","sell_settlement_store.mark_notification_sent",
  "admin_config_store.block_user","admin_config_store.unblock_user","ops_store.cleanup_audit",
  "order_creation_store.create","sell_order_store.create","swap_store.create",
  "order_workflow_store.request_verification","sell_order_store.cancel_pending",
  "swap_store.transition","user_profile_store.set_referral_address",
  "order_lifecycle_store.expire_due","order_lifecycle_store.fail_session",
  "order_workflow_store.mark_sent","payment_transition_store.mark_paid",
  "sell_settlement_store.settle_vertu",
 }
 r1=(ROOT/C["rehearsals"][8]["proposal"]).read_text()
 assert r1.count("SECURITY DEFINER")==3
 assert "p_user_id" in r1 and "p_web_user_id" in r1
 r2=(ROOT/C["rehearsals"][9]["proposal"]).read_text()
 assert r2.count("SECURITY DEFINER")==8
 assert r2.count("SKIP LOCKED")==3
 r3=(ROOT/C["rehearsals"][10]["proposal"]).read_text()
 assert r3.count("SECURITY DEFINER")==3
 assert "interval '90 days'" in r3
 r4=(ROOT/C["rehearsals"][11]["proposal"]).read_text()
 assert r4.count("SECURITY DEFINER")==3
 assert "'pending'" in r4 and "'waiting'" in r4
