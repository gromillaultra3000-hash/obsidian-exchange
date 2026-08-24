import ast,hashlib,importlib.util,json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
M=json.loads((ROOT/"docs/e0-3-relay-read-matrix.v1.json").read_text())
S=importlib.util.spec_from_file_location("relay_graph",ROOT/"scripts/e0_relay_capability_graph.py")
G=importlib.util.module_from_spec(S);S.loader.exec_module(G)


def test_matrix_covers_every_and_only_select_method_once():
 graph=G.build();expected={(e["repository"],e["method"]) for e in graph["edges"] if "SELECT" in e["operations"]}
 actual={tuple(x["id"].split(".",1)) for x in M["reads"]}
 assert len(M["reads"])==len(actual)==43
 assert actual==expected


def test_matrix_is_bound_to_graph_and_sources():
 graph=G.build();wire=(json.dumps(graph,ensure_ascii=False,sort_keys=True,separators=(",",":"))+"\n").encode()
 assert hashlib.sha256(wire).hexdigest()==M["relayGraphSha256"]
 for module,digest in M["sourceSha256"].items():
  assert hashlib.sha256((ROOT/"relay/repositories"/f"{module}.py").read_bytes()).hexdigest()==digest
 assert 'CREATE TABLE' not in (ROOT/'relay/repositories/receipt_store.py').read_text()
 assert 'ALTER TABLE' not in (ROOT/'relay/repositories/receipt_store.py').read_text()
 for path,digest in M["schemaSha256"].items():
  assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest()==digest
 assert M["productionAuthorization"] is M["valuesIncluded"] is False


def test_columns_are_closed_unique_and_never_wildcard():
 for item in M["reads"]:
  assert item["columns"]
  for relation,columns in item["columns"].items():
   assert relation and columns and len(columns)==len(set(columns))
   assert not ({"*","ALL","UNKNOWN","TBD"}&set(columns))
 assert M["grantPolicy"]=={"tableWideSelect":False,"columnGrantsOnly":True,"metadataViewSeparate":True,"functionBodiesMayReceiveOnlyDeclaredColumns":True}


def test_reachable_wildcards_are_replaced_by_frozen_column_lists():
 assert not M["wildcardDebt"]
 reads={x["id"]:x for x in M["reads"]}
 assert reads["payment_session_store.latest_active_for_authorized_order"]["columns"]["payment_sessions"]==["session_token","order_id","status","created_at","id"]
 assert reads["payment_session_store.latest_for_authorized_order"]["columns"]["payment_sessions"]==["session_token","status","order_id","id"]
 outbox=reads["payment_transition_store.claim_notification"]
 assert outbox["columns"]["payment_notification_outbox"]==[
  "id","order_id","recipient_id","payload","attempts",
 ]
 session_source=(ROOT/"relay/repositories/payment_session_store.py").read_text()
 transition_source=(ROOT/"relay/repositories/payment_transition_store.py").read_text()
 assert "SELECT * FROM payment_sessions WHERE order_id=" not in session_source
 assert "RETURNING o.*" not in transition_source
 assert "CREATE TABLE" not in transition_source and "executescript" not in transition_source


def test_sensitive_reads_remain_explicit_and_acl_is_not_ready():
 reads={x["id"]:x["columns"] for x in M["reads"]}
 assert not ({"client_ip","user_agent","telegram_id","provider_payload","qr_payload"} & set(reads["payment_session_store.latest_for_authorized_order"]["payment_sessions"]))
 assert "payout_details" in reads["sell_order_store.sells_for_user"]["sell_orders"]
 assert "message" in reads["support_store.thread_for_web_user"]["support_messages"]
 assert reads["sell_settlement_store.settle_vertu"]["user_vip_volume"]==["user_id","total_rub"]
 assert M["remainingWork"]==[
  "rehearse the remaining 6 read and 26 writer production-equivalent function bodies in disposable PostgreSQL",
 ]


def test_reachable_count_star_debt_is_closed_with_non_null_keys():
 assert not M["rowCountDebt"]
 wanted={
  "engagement_store":{"referral_stats"},
  "reporting_store":{"admin_analytics","admin_stats","public_stats","site_stats","today_status_counts"},
  "support_store":{"open_count_for_web_user"},
 }
 for module,methods in wanted.items():
  source=(ROOT/"relay/repositories"/f"{module}.py").read_text()
  tree=ast.parse(source)
  definitions=[node for node in ast.walk(tree) if isinstance(node,ast.FunctionDef) and node.name in methods]
  assert {node.name for node in definitions}==methods
  assert all("COUNT(*)" not in ast.get_source_segment(source,node) for node in definitions)
 reads={x["id"]:x["columns"] for x in M["reads"]}
 assert "referred_id" in reads["engagement_store.referral_stats"]["referrals"]
 for method in wanted["reporting_store"]:
  assert "order_id" in reads[f"reporting_store.{method}"]["orders"]
 assert "id" in reads["support_store.open_count_for_web_user"]["support_tickets"]
