import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

dsn=os.getenv("TEST_POSTGRES_DSN")
if not dsn:
 print("E0.3 Relay P5A background claim/poll rehearsal: skipped (TEST_POSTGRES_DSN unset)")
 raise SystemExit(0)

import psycopg
from psycopg.conninfo import conninfo_to_dict,make_conninfo

ROOT=Path(__file__).resolve().parents[1]
ENVELOPE=(ROOT/"deploy/postgres/proposals/028_e0_relay_acl_envelope.sql").read_text()
PACKAGE=(ROOT/"deploy/postgres/proposals/035_e0_relay_p5a_background_claim_poll_bodies.sql").read_text()

with psycopg.connect(dsn) as conn:
 conn.execute("""CREATE TABLE orders(order_id bigserial PRIMARY KEY,user_id bigint NOT NULL,
  status text NOT NULL,rub_amount numeric(20,2) NOT NULL,updated_at timestamptz)""")
 conn.execute("""CREATE TABLE payment_sessions(id bigserial PRIMARY KEY,session_token text,
  provider_invoice_id text,order_id bigint,provider text,status text,created_at timestamptz)""")
 conn.execute("""CREATE TABLE order_lifecycle_work(id bigserial PRIMARY KEY,kind text,state text,
  order_id bigint,session_token text,provider text,provider_invoice_id text,user_id bigint,
  currency text,rub_amount numeric(20,2),order_status text,has_receipt boolean DEFAULT false,
  detail text DEFAULT '',attempts integer DEFAULT 0,created_at timestamptz DEFAULT now(),
  claimed_at timestamptz,completed_at timestamptz,updated_at timestamptz DEFAULT now())""")
 conn.execute("""CREATE TABLE payment_notification_outbox(id bigserial PRIMARY KEY,order_id bigint,
  recipient_id bigint,payload jsonb,state text,attempts integer DEFAULT 0,claimed_at timestamptz,
  updated_at timestamptz DEFAULT now())""")
 conn.execute("""CREATE TABLE sell_orders(id bigserial PRIMARY KEY,user_id bigint,rub_amount numeric(20,2),
  payout_ref text,payout_status text,payout_provider text,updated_at timestamptz)""")
 conn.execute("""CREATE TABLE sell_settlement_outbox(id bigserial PRIMARY KEY,sell_id bigint,
  recipient_id bigint,rub_amount numeric(20,2),state text,attempts integer DEFAULT 0,
  claimed_at timestamptz,updated_at timestamptz DEFAULT now())""")
 conn.execute("CREATE TABLE support_tickets(ticket_id bigserial PRIMARY KEY,web_user_id bigint,subject text,status text)")
 conn.execute("CREATE TABLE payment_transition_audit(id bigserial PRIMARY KEY,order_id bigint,from_status text,to_status text,evidence text)")
 conn.execute("INSERT INTO orders(order_id,user_id,status,rub_amount) VALUES(1,7,'pending',100),(2,8,'paid',200)")
 conn.execute("""INSERT INTO payment_sessions(session_token,provider_invoice_id,order_id,provider,status,created_at)
  SELECT 'v-'||g,'invoice-'||g,1,'vertu','invoice_created',now()-interval '1 minute'
  FROM generate_series(1,105) g""")
 conn.execute("""INSERT INTO payment_sessions(session_token,provider_invoice_id,order_id,provider,status,created_at) VALUES
  ('old','old-invoice',1,'vertu','invoice_created',now()-interval '3 hours'),
  ('wrong-provider','x',1,'other','invoice_created',now()),
  ('wrong-order','x',2,'vertu','invoice_created',now())""")
 conn.execute("""INSERT INTO order_lifecycle_work(kind,state,order_id,user_id,currency,rub_amount,order_status)
  SELECT 'provider_cancel','pending',g,7,'BTC',100,'expired' FROM generate_series(1,12) g""")
 conn.execute("""INSERT INTO payment_notification_outbox(order_id,recipient_id,payload,state)
  SELECT g,7,jsonb_build_object('order_id',g),'pending' FROM generate_series(1,12) g""")
 conn.execute("""INSERT INTO sell_settlement_outbox(sell_id,recipient_id,rub_amount,state)
  SELECT g,7,100,'pending' FROM generate_series(1,12) g""")
 conn.execute("""INSERT INTO sell_orders(user_id,rub_amount,payout_ref,payout_status,payout_provider,updated_at)
  SELECT 7,100,'ref-'||g,'pending','vertu',now()-interval '1 minute'
  FROM generate_series(1,105) g""")
 conn.execute("""INSERT INTO sell_orders(user_id,rub_amount,payout_ref,payout_status,payout_provider,updated_at) VALUES
  (7,100,'paid-ref','paid','vertu',now()),(7,100,'old-ref','pending','vertu',now()-interval '31 days'),
  (7,100,'other-ref','pending','other',now())""")
 conn.execute(ENVELOPE)
 conn.execute(PACKAGE)

relay_info=conninfo_to_dict(dsn)
relay_info.update(user="obsidian_relay",password="synthetic-rehearsal-only",connect_timeout="5")
relay=make_conninfo(**relay_info)

def claim(sql):
 with psycopg.connect(relay) as conn:
  row=conn.execute(sql).fetchone()
  return row[0] if row else None

for sql in ("SELECT id FROM relay_lifecycle_claim_work(NULL)",
            "SELECT id FROM relay_payment_claim_notification()",
            "SELECT id FROM relay_sell_claim_notification()"):
 with ThreadPoolExecutor(max_workers=12) as pool:
  ids=list(pool.map(lambda _x:claim(sql),range(12)))
 assert len(set(ids))==12 and None not in ids

with psycopg.connect(relay) as conn:
 assert conn.execute("SELECT count(*) FROM relay_payment_pending_vertu()").fetchone()==(100,)
 assert conn.execute("SELECT min(order_id),max(order_id) FROM relay_payment_pending_vertu()").fetchone()==(1,1)
 active=conn.execute("SELECT * FROM relay_sell_active_vertu_payouts(ARRAY['PAID','failed','declined','revoked'],30::smallint)").fetchall()
 assert len(active)==100 and [r[0] for r in active]==sorted(r[0] for r in active)
 assert all(r[4]=='pending' for r in active)

def denied(statement):
 try:
  with psycopg.connect(relay) as conn:conn.execute(statement)
 except psycopg.Error:return
 raise AssertionError(f"statement unexpectedly allowed: {statement}")

for statement in (
 "SELECT * FROM relay_lifecycle_claim_work('bad-kind')",
 "SELECT * FROM relay_sell_active_vertu_payouts(ARRAY[]::text[],3::smallint)",
 "SELECT * FROM relay_sell_active_vertu_payouts(ARRAY['unknown'],3::smallint)",
 "SELECT * FROM relay_sell_active_vertu_payouts(ARRAY['paid'],0::smallint)",
 "SELECT * FROM orders","SELECT * FROM payment_sessions","SELECT * FROM order_lifecycle_work",
 "SELECT * FROM payment_notification_outbox","SELECT * FROM sell_orders",
 "SELECT * FROM sell_settlement_outbox",
):denied(statement)

with psycopg.connect(dsn) as conn:
 assert conn.execute("SELECT count(*) FROM order_lifecycle_work WHERE state='sending' AND attempts=1").fetchone()==(12,)
 assert conn.execute("SELECT count(*) FROM payment_notification_outbox WHERE state='sending' AND attempts=1").fetchone()==(12,)
 assert conn.execute("SELECT count(*) FROM sell_settlement_outbox WHERE state='sending' AND attempts=1").fetchone()==(12,)
 assert conn.execute("""SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
  WHERE n.nspname='public' AND p.proname LIKE 'relay_%'
  AND has_function_privilege('obsidian_relay',p.oid,'EXECUTE')""").fetchone()[0]==10
 assert conn.execute("""SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
  WHERE n.nspname='public' AND p.proname IN ('relay_lifecycle_claim_work',
  'relay_payment_pending_vertu','relay_payment_claim_notification',
  'relay_sell_active_vertu_payouts','relay_sell_claim_notification')
  AND has_function_privilege('public',p.oid,'EXECUTE')""").fetchone()[0]==0

print("E0.3 Relay P5A five bounded background claim/poll bodies rehearsal: OK")
