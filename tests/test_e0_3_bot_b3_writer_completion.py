import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
PLAN=json.loads((ROOT/'docs/e0-3-bot-acl-plan.v1.json').read_text())

def test_b3_rehearsal_evidence_has_exact_disjoint_coverage():
 paths=[
  'docs/e0-3-bot-b3-1-engagement-non-money-writers-rehearsal.v1.json',
  'docs/e0-3-bot-b3-2a-admin-config-non-money-writers-rehearsal.v1.json',
  'docs/e0-3-bot-b3-2b-owner-order-workflow-writers-rehearsal.v1.json',
 ]
 evidence=[json.loads((ROOT/p).read_text()) for p in paths]
 covered=[method for item in evidence for method in item['methodCoverage']]
 expected={
  'engagement_store.comment_review','engagement_store.disable_broadcast',
  'engagement_store.disable_rates','engagement_store.finalize_review',
  'engagement_store.log_action','engagement_store.rate_review',
  'engagement_store.toggle_rate','engagement_store.update_rates',
  'admin_config_store.block_address','admin_config_store.block_user',
  'admin_config_store.deactivate_staff','admin_config_store.set_reserve',
  'admin_config_store.set_staff','admin_config_store.unblock_addresses',
  'admin_config_store.unblock_user','order_workflow_store.cancel_pending_for_owner',
  'order_workflow_store.retry_amount_for_owner',
 }
 assert len(covered)==len(set(covered))==17
 assert set(covered)==expected
 b3=PLAN['rehearsalPackages'][2]
 assert b3['status']=='REHEARSED'
 assert b3['coverageTest']=='tests/test_e0_3_bot_b3_writer_completion.py'
