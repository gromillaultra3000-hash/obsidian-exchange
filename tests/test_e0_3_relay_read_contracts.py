import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
C=json.loads((ROOT/"docs/e0-3-relay-read-contracts.v1.json").read_text())
M=json.loads((ROOT/"docs/e0-3-relay-read-matrix.v1.json").read_text())
P=json.loads((ROOT/"docs/e0-3-relay-read-authorization-plan.v1.json").read_text())


def test_contract_progress_is_exact_and_bound_to_known_reads_and_packages():
 contracts=C["contracts"]
 assert C["completedCount"]==len(contracts)==43
 assert C["remainingCount"]==C["totalCount"]-C["completedCount"]==0
 assert len({item["id"] for item in contracts})==len(contracts)
 assert {item["id"] for item in contracts}<={item["id"] for item in M["reads"]}
 packages={p["id"] for p in P["packages"]}
 assert all(item["purposePackage"] in packages for item in contracts)


def test_metadata_contract_has_no_business_relation_capability():
 item=next(x for x in C["contracts"] if x["id"]=="runtime_schema_store.validate")
 assert item["inputs"]==[]
 assert set(item["reads"])=={
  "pg_catalog.pg_class","pg_catalog.pg_namespace","pg_catalog.pg_attribute",
 }
 assert item["designCorrection"].startswith("information_schema.columns is privilege-filtered")
 assert [x["name"] for x in item["returns"]["fields"]]==["missing_relation","missing_columns"]
 assert item["owner"]=="obsidian_relay_metadata_owner"
 assert "business table SELECT" in item["forbiddenCapabilities"]


def test_payment_session_returns_are_closed_and_sensitive_fields_removed():
 items={x["id"]:x for x in C["contracts"]}
 active=items["payment_session_store.latest_active_for_authorized_order"]
 latest=items["payment_session_store.latest_for_authorized_order"]
 assert [x["name"] for x in active["returns"]["fields"]]==["session_token"]
 assert [x["name"] for x in latest["returns"]["fields"]]==["session_token","status"]
 sensitive={"client_ip","user_agent","telegram_id","provider_payload","qr_payload"}
 assert not (sensitive & {x["name"] for x in active["returns"]["fields"]})
 assert not (sensitive & {x["name"] for x in latest["returns"]["fields"]})
 source=(ROOT/"relay/repositories/payment_session_store.py").read_text()
 assert "SELECT session_token FROM payment_sessions WHERE order_id=" in source
 assert "SELECT session_token,status FROM payment_sessions WHERE order_id=" in source


def test_contracts_are_design_only_and_next_count_is_truthful():
 assert C["productionAuthorization"] is C["implementationDeployed"] is False
 assert C["status"]=="COMPLETE"
 assert C["nextPrerequisite"].startswith("rehearse the eight R5 transition writer")


def test_sell_settlement_declares_implicit_upsert_read():
 item=next(x for x in C["contracts"] if x["id"]=="sell_settlement_store.settle_vertu")
 assert item["reads"]["user_vip_volume"]==["user_id","total_rub"]


def test_public_aggregate_package_is_complete_and_raw_rows_are_bounded():
 items={x["id"]:x for x in C["contracts"]}
 package=next(x for x in P["packages"] if x["id"]=="P1_PUBLIC_AGGREGATES")
 assert set(package["methods"])<=set(items)
 public=items["reporting_store.public_stats"]
 assert public["inputs"]==[] and public["returns"]["cardinality"]=="EXACTLY_ONE"
 assert public["timeSemantics"][0]=="function TimeZone=UTC"
 site=items["reporting_store.site_stats"]
 assert site["aggregateOnly"] is True and site["rawRowsReturned"] is False
 reserves=items["reporting_store.reserves"]
 assert reserves["limit"]==64
 assert reserves["returns"]["cardinality"]=="ZERO_OR_MORE_BOUNDED_64"
 assert reserves["publicDataClassification"]=="CURATED_DECLARED_RESERVE_NOT_WALLET_BALANCE"


def test_support_contracts_bind_owner_and_bound_every_collection():
 items={x["id"]:x for x in C["contracts"]}
 support={key:value for key,value in items.items() if key.startswith("support_store.")}
 assert set(support)=={
  "support_store.exists_for_web_user","support_store.list_for_web_user",
  "support_store.open_count_for_web_user","support_store.thread_for_web_user",
  "support_store.user_reply",
 }
 assert all(any("web_user_id" in predicate for predicate in item["fixedPredicates"])
            for item in support.values())
 assert support["support_store.list_for_web_user"]["limit"]==100
 thread=support["support_store.thread_for_web_user"]
 messages=next(x for x in thread["returns"]["fields"] if x["name"]=="messages")
 assert messages["itemSchema"]["maxItems"]==500
 assert thread["crossUserResult"]=="zero rows"
 reply=support["support_store.user_reply"]
 assert reply["lock"]=="FOR UPDATE"
 assert reply["crossUserResult"]=="zero rows and no writes"
 source=(ROOT/"relay/repositories/support_store.py").read_text()
 assert source.count("ORDER BY updated_at DESC,id DESC LIMIT 100")==2
 assert source.count("ORDER BY created_at DESC,id DESC LIMIT 500")==2


def test_customer_history_contracts_bind_identity_and_bounds():
 items={x["id"]:x for x in C["contracts"]}
 customer=items["order_read_store.customer_orders"]
 assert customer["limit"]==100
 assert customer["inputs"][2]["constraints"]==["0..1000000"]
 web=items["order_read_store.web_customer_orders"]
 assert "authenticated web-user link" in web["inputs"][1]["constraints"][1]
 assert web["crossUserResult"]=="zero rows"
 receipts=items["order_read_store.receipt_order_ids"]
 assert receipts["limit"]==100 and receipts["oversizeResult"]=="receipt_order_ids_too_many"
 assert receipts["function"].endswith("(bigint[],bigint,bigint)")
 assert receipts["designCorrection"].startswith("the former bigint[]-only signature")
 swaps=items["swap_store.swaps_for_web_user"]
 assert swaps["limit"]==100 and swaps["crossUserResult"]=="zero rows"
 assert items["engagement_store.referral_stats"]["aggregateOnly"] is True
 assert items["user_profile_store.referral_address"]["crossUserResult"]=="zero rows"
 order_source=(ROOT/"relay/repositories/order_read_store.py").read_text()
 swap_source=(ROOT/"relay/repositories/swap_store.py").read_text()
 assert order_source.count("min(100, max(1, int(limit)))")==6
 assert order_source.count("receipt_order_ids_too_many")==2
 assert swap_source.count("min(100,max(1,int(limit)))")==3


def test_sell_payout_details_are_owner_scoped_bounded_and_justified():
 items={x["id"]:x for x in C["contracts"]}
 pending=items["sell_order_store.pending_view_for_user"]
 history=items["sell_order_store.sells_for_user"]
 assert pending["limit"]==history["limit"]==100
 assert pending["fixedPredicates"]==["user_id=$1","status='pending'"]
 assert history["fixedPredicates"]==["user_id=$1"]
 assert pending["crossUserResult"]==history["crossUserResult"]=="zero rows"
 assert pending["sensitiveFields"]["destinationFallback"]==["payout_details","sbp_phone"]
 assert "legacy rows" in history["sensitiveFields"]["justification"]
 source=(ROOT/"relay/repositories/sell_order_store.py").read_text()
 assert source.count("min(100,max(0,int(limit)))")==4


def test_operator_package_is_closed_bounded_and_admin_only():
 items={x["id"]:x for x in C["contracts"]}
 package=next(x for x in P["packages"] if x["id"]=="P4_OPERATOR_REPORTING")
 assert set(package["methods"])<=set(items)
 assert all(items[method]["publicExposure"] is False for method in package["methods"])
 assert items["admin_config_store.blocked_user_rows"]["limit"]==100
 assert items["order_read_store.admin_recent"]["limit"]==100
 analytics=items["reporting_store.admin_analytics"]
 assert analytics["collectionBounds"]=={
  "daily":15,"hourly":24,"by_currency":32,"by_status":32,
  "providers":64,"recent":20,"totals":1,
 }
 assert analytics["timeSemantics"][0]=="function TimeZone=UTC"
 today=items["reporting_store.today_status_counts"]
 assert today["purposePackage"]=="P1_PUBLIC_AGGREGATES"
 assert today["aggregateOnly"] is today["publicExposure"] is True
 admin_source=(ROOT/"relay/repositories/admin_config_store.py").read_text()
 order_source=(ROOT/"relay/repositories/order_read_store.py").read_text()
 reporting_source=(ROOT/"relay/repositories/reporting_store.py").read_text()
 assert admin_source.count("min(100,max(1,int(limit)))")==2
 assert order_source.count("min(100, max(1, int(limit)))")>=6
 assert reporting_source.count("LIMIT 32")==4
 assert reporting_source.count("LIMIT 64")==2


def test_interactive_order_payment_package_is_closed_and_minimal():
 items={x["id"]:x for x in C["contracts"]}
 package=next(x for x in P["packages"] if x["id"]=="P3_INTERACTIVE_ORDER_PAYMENT")
 assert set(package["methods"])<=set(items)
 duplicate=items["order_creation_store.recent_duplicate"]
 assert duplicate["inputs"][-1]["constraints"]==["1..300"]
 assert duplicate["crossUserResult"]=="zero rows"
 snapshot=items["order_read_store.authorized_snapshot"]
 assert len(snapshot["returns"]["fields"])==20
 assert snapshot["crossAuthorityResult"]=="zero rows"
 invoice=items["payment_session_store.latest_provider_invoice_for_authorized_order"]
 assert [x["name"] for x in invoice["returns"]["fields"]]==[
  "provider_invoice_id","provider",
 ]
 assert set(invoice["returns"])=={"cardinality","fields"}
 assert invoice["crossAuthorityResult"]=="zero rows"
 receipt=items["receipt_store.authorized_state"]
 assert receipt["returns"]["fields"][0]["enum"]==["","stored","sent"]
 session=items["payment_session_store.get_by_token"]
 assert [x["name"] for x in session["returns"]["fields"]]==[
  "amount","order_id","status","provider_payload","qr_payload","expires_at"]
 assert session["crossTokenResult"]=="zero rows"
 swap=items["swap_store.get_by_token"]
 assert swap["crossTokenResult"]=="zero rows"
 source=(ROOT/"relay/repositories/order_creation_store.py").read_text()
 assert source.count("min(300, max(1, int(query.get(\"seconds\", 90))))")==2


def test_provider_callback_package_uses_bounded_correlation_only():
 items={x["id"]:x for x in C["contracts"]}
 package=next(x for x in P["packages"] if x["id"]=="P6_PROVIDER_CALLBACK")
 assert set(package["methods"])<=set(items)
 verification=items["order_workflow_store.request_verification"]
 assert verification["inputs"][1]["constraints"]==["enum video,pdf-success"]
 assert verification["callerAuthorization"].startswith("verified Montera")
 payout=items["sell_order_store.vertu_payout_by_ref"]
 swap=items["swap_store.get_by_external_id"]
 assert "authoritative payout status" in payout["callbackTrust"]
 assert "authoritative status" in swap["callbackTrust"]
 assert payout["inputs"][0]["constraints"][1]=="length <=256"
 assert swap["inputs"][0]["constraints"][1]=="length <=256"
 sell_source=(ROOT/"relay/repositories/sell_order_store.py").read_text()
 swap_source=(ROOT/"relay/repositories/swap_store.py").read_text()
 assert sell_source.count("not value or len(value)>256")==2
 assert swap_source.count("value and len(value)<=256")==4


def test_background_state_machine_package_is_closed_atomic_and_bounded():
 items={x["id"]:x for x in C["contracts"]}
 package=next(x for x in P["packages"] if x["id"]=="P5_BACKGROUND_STATE_MACHINE")
 assert set(package["methods"])<=set(items)
 assert items["order_lifecycle_store.claim_work"]["lock"]=="FOR UPDATE SKIP LOCKED"
 assert items["order_lifecycle_store.expire_due"]["limit"]==1000
 assert items["payment_session_store.pending_vertu"]["limit"]==100
 assert items["sell_order_store.active_vertu_payouts"]["limit"]==100
 assert items["payment_transition_store.claim_notification"]["removedReturnFields"]==[
  "state","created_at","claimed_at","sent_at","updated_at",
 ]
 assert items["sell_settlement_store.claim_notification"]["removedReturnFields"]==[
  "state","created_at","claimed_at","sent_at","updated_at",
 ]
 assert "one transaction" in items["payment_transition_store.mark_paid"]["stateChange"]
 assert "single transaction" in items["sell_settlement_store.settle_vertu"]["stateChange"]
 lifecycle=(ROOT/"relay/repositories/order_lifecycle_store.py").read_text()
 sessions=(ROOT/"relay/repositories/payment_session_store.py").read_text()
 payouts=(ROOT/"relay/repositories/sell_order_store.py").read_text()
 assert lifecycle.count("not token or len(token)>256")==2
 assert sessions.count("ORDER BY ps.id LIMIT 100")==2
 assert payouts.count("ORDER BY id LIMIT 100")==2
