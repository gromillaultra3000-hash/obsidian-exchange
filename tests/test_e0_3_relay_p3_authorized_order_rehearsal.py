import os
from pathlib import Path


dsn=os.getenv("TEST_POSTGRES_DSN")
if not dsn:
 print("E0.3 Relay P3 authorized order rehearsal: skipped (TEST_POSTGRES_DSN unset)")
 raise SystemExit(0)

import psycopg
from psycopg.conninfo import conninfo_to_dict,make_conninfo


ROOT=Path(__file__).resolve().parents[1]
ENVELOPE=(ROOT/"deploy/postgres/proposals/028_e0_relay_acl_envelope.sql").read_text()
PACKAGE=(ROOT/"deploy/postgres/proposals/032_e0_relay_p3_authorized_order_reads.sql").read_text()


with psycopg.connect(dsn) as conn:
 conn.execute("""CREATE TABLE orders(
  order_id bigserial PRIMARY KEY,user_id bigint NOT NULL,username text,currency text NOT NULL,
  rub_amount numeric(20,2) NOT NULL,crypto_address text NOT NULL,status text NOT NULL,
  created_at timestamptz DEFAULT now(),paid_btc_tx text,updated_at timestamptz,
  web_user_id bigint,rub_volume_counted boolean DEFAULT false,verification_requested text,
  montera_invoice_id text,receipt_deadline timestamptz,receipt_sent_at timestamptz,
  network text,agreed_rate numeric(30,12),agreed_crypto_amount numeric(30,12),agreed_at timestamptz)""")
 conn.execute("""CREATE TABLE payment_sessions(
  id bigserial PRIMARY KEY,session_token text,order_id bigint,amount numeric,provider text,
  status text,provider_invoice_id text,provider_payload text,qr_payload text,
  expires_at timestamptz,created_at timestamptz DEFAULT now())""")
 conn.execute("CREATE TABLE order_receipts(order_id bigint PRIMARY KEY)")
 conn.execute("CREATE TABLE swap_sessions(id bigserial PRIMARY KEY)")
 conn.execute("""CREATE TABLE payment_notification_outbox(
  id bigserial PRIMARY KEY,order_id bigint,recipient_id bigint,payload jsonb,state text,
  attempts integer DEFAULT 0,claimed_at timestamptz,updated_at timestamptz DEFAULT now())""")
 conn.execute("CREATE TABLE support_tickets(ticket_id bigserial PRIMARY KEY,web_user_id bigint,subject text,status text)")
 conn.execute("CREATE TABLE payment_transition_audit(id bigserial PRIMARY KEY,order_id bigint,from_status text,to_status text,evidence text)")
 conn.execute("""INSERT INTO orders(order_id,user_id,username,currency,rub_amount,crypto_address,
  status,receipt_sent_at,network) VALUES
  (1,7,'owner','BTC',100,'owner-destination','pending',NULL,'MAINNET'),
  (2,8,'foreign','BTC',200,'foreign-destination','pending',now(),'MAINNET')""")
 conn.execute("""INSERT INTO payment_sessions(session_token,order_id,amount,provider,status,
  provider_invoice_id,provider_payload,qr_payload,expires_at,created_at) VALUES
  ('owner-old',1,100,'brabus:tbank_deeplink','failed','old','{}',NULL,NULL,now()-interval '2 seconds'),
  ('owner-token',1,100,'brabus:tbank_deeplink','invoice_created','owner-invoice',
   '{"requisites":{}}','https://pay/owner',now()+interval '10 minutes',now()),
  ('foreign-token',2,200,'vertu','invoice_created','foreign-invoice','{}',NULL,NULL,now())""")
 conn.execute("INSERT INTO order_receipts(order_id) VALUES(1),(2)")
 conn.execute(ENVELOPE)
 conn.execute(PACKAGE)

relay=conninfo_to_dict(dsn)
relay.update(user="obsidian_relay",password="synthetic-rehearsal-only",connect_timeout="2")
relay=make_conninfo(**relay)

with psycopg.connect(relay) as conn:
 assert conn.execute("SELECT order_id,user_id FROM relay_order_authorized_snapshot(1,7,NULL)").fetchone()==(1,7)
 assert conn.execute("SELECT order_id FROM relay_order_authorized_snapshot(1,8,NULL)").fetchall()==[]
 assert conn.execute("SELECT order_id FROM relay_order_authorized_snapshot(1,NULL,'owner-token')").fetchone()==(1,)
 assert conn.execute("SELECT order_id FROM relay_order_authorized_snapshot(1,NULL,'foreign-token')").fetchall()==[]
 session=conn.execute("SELECT * FROM relay_payment_session_get_by_token('owner-token')").fetchone()
 assert session[0]==100 and session[1]==1 and session[2]=='invoice_created'
 assert session[3]=='{"requisites":{}}' and session[4]=='https://pay/owner'
 assert conn.execute("SELECT * FROM relay_payment_session_get_by_token('foreign')").fetchall()==[]
 assert conn.execute("SELECT * FROM relay_payment_session_latest_for_authorized_order(1,7,NULL)").fetchone()==('owner-token','invoice_created')
 assert conn.execute("SELECT * FROM relay_payment_session_latest_active_for_authorized_order(1,NULL,'owner-token')").fetchone()==('owner-token',)
 assert conn.execute("SELECT * FROM relay_payment_session_latest_active_for_authorized_order(1,8,NULL)").fetchall()==[]
 assert conn.execute("""SELECT * FROM relay_payment_session_latest_provider_invoice_for_authorized_order(
  1,'brabus',true,7,NULL)""").fetchone()==('owner-invoice','brabus:tbank_deeplink')
 assert conn.execute("""SELECT * FROM relay_payment_session_latest_provider_invoice_for_authorized_order(
  1,'vertu',false,7,NULL)""").fetchall()==[]
 assert conn.execute("SELECT relay_receipt_authorized_state(1,7,NULL)").fetchone()==('stored',)
 assert conn.execute("SELECT relay_receipt_authorized_state(2,NULL,'foreign-token')").fetchone()==('sent',)
 assert conn.execute("SELECT relay_receipt_authorized_state(2,7,NULL)").fetchone()==('',)

def denied(statement):
 try:
  with psycopg.connect(relay) as conn:conn.execute(statement)
 except psycopg.Error:return
 raise AssertionError(f"statement unexpectedly allowed: {statement}")

for statement in (
 "SELECT * FROM relay_order_authorized_snapshot(1,NULL,NULL)",
 "SELECT * FROM relay_order_authorized_snapshot(1,-1,NULL)",
 "SELECT * FROM relay_payment_session_get_by_token('')",
 "SELECT * FROM relay_payment_session_latest_for_authorized_order(1,NULL,'')",
 "SELECT * FROM relay_payment_session_latest_provider_invoice_for_authorized_order(1,'vertu',true,7,NULL)",
 "SELECT relay_receipt_authorized_state(1,NULL,NULL)",
 "SELECT * FROM orders","SELECT * FROM payment_sessions","SELECT * FROM order_receipts",
):denied(statement)

with psycopg.connect(dsn) as conn:
 assert conn.execute("""SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
  WHERE n.nspname='public' AND p.proname LIKE 'relay_%'
  AND has_function_privilege('obsidian_relay',p.oid,'EXECUTE')""").fetchone()[0]==11
 assert conn.execute("""SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
  WHERE n.nspname='public' AND (p.proname LIKE '%authorized%'
   OR p.proname='relay_payment_session_get_by_token')
  AND has_function_privilege('public',p.oid,'EXECUTE')""").fetchone()[0]==0

print("E0.3 Relay P3 six token/owner authorized reads rehearsal: OK")
