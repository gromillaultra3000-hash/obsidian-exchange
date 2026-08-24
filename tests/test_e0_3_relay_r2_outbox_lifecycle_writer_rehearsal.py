import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

dsn=os.getenv("TEST_POSTGRES_DSN")
if not dsn:
 print("E0.3 Relay R2 outbox/lifecycle writer rehearsal: skipped (TEST_POSTGRES_DSN unset)")
 raise SystemExit(0)

import psycopg
from psycopg.conninfo import conninfo_to_dict,make_conninfo

ROOT=Path(__file__).resolve().parents[1]
ENVELOPE=(ROOT/"deploy/postgres/proposals/028_e0_relay_acl_envelope.sql").read_text()
PACKAGE=(ROOT/"deploy/postgres/proposals/038_e0_relay_r2_outbox_lifecycle_writers.sql").read_text()

with psycopg.connect(dsn) as conn:
 conn.execute("CREATE TABLE orders(order_id bigserial PRIMARY KEY,user_id bigint,status text,rub_amount numeric,updated_at timestamptz)")
 conn.execute("""CREATE TABLE payment_notification_outbox(id bigserial PRIMARY KEY,order_id bigint,
  recipient_id bigint,payload jsonb,state text DEFAULT 'pending',attempts integer DEFAULT 0,
  claimed_at timestamptz,sent_at timestamptz,updated_at timestamptz DEFAULT now())""")
 conn.execute("CREATE TABLE payment_transition_audit(id bigserial PRIMARY KEY,order_id bigint,from_status text,to_status text,evidence text)")
 conn.execute("""CREATE TABLE support_tickets(ticket_id bigserial PRIMARY KEY,
  web_user_id bigint,subject text,status text)""")
 conn.execute("""CREATE TABLE order_lifecycle_work(id bigserial PRIMARY KEY,kind text,order_id bigint,
  session_token text,provider text,provider_invoice_id text,user_id bigint,currency text,
  rub_amount numeric,order_status text,has_receipt boolean DEFAULT false,detail text DEFAULT '',
  state text DEFAULT 'pending',attempts integer DEFAULT 0,created_at timestamptz DEFAULT now(),
  claimed_at timestamptz,completed_at timestamptz,updated_at timestamptz DEFAULT now())""")
 conn.execute("""CREATE TABLE sell_settlement_outbox(id bigserial PRIMARY KEY,sell_id bigint,
  recipient_id bigint,rub_amount numeric,state text DEFAULT 'pending',attempts integer DEFAULT 0,
  claimed_at timestamptz,sent_at timestamptz,updated_at timestamptz DEFAULT now())""")
 conn.execute("""INSERT INTO order_lifecycle_work(kind,order_id) SELECT
  CASE WHEN n%2=0 THEN 'provider_cancel' ELSE 'order_expired_notify' END,n FROM generate_series(1,12)n""")
 conn.execute("""INSERT INTO payment_notification_outbox(order_id,recipient_id,payload)
  SELECT n,n,jsonb_build_object('n',n) FROM generate_series(1,12)n""")
 conn.execute("""INSERT INTO sell_settlement_outbox(sell_id,recipient_id,rub_amount)
  SELECT n,n,n*100 FROM generate_series(1,12)n""")
 conn.execute(ENVELOPE)
 conn.execute(PACKAGE)

info=conninfo_to_dict(dsn);info.update(user="obsidian_relay",password="synthetic-rehearsal-only",connect_timeout="5")
relay=make_conninfo(**info)

def call(sql,args=()):
 with psycopg.connect(relay) as conn:return conn.execute(sql,args).fetchone()

def claim_lifecycle(_):return call("SELECT id FROM relay_lifecycle_claim_work(NULL)")[0]
def claim_payment(_):return call("SELECT id FROM relay_payment_claim_notification()")[0]
def claim_sell(_):return call("SELECT id FROM relay_sell_claim_notification()")[0]

with ThreadPoolExecutor(max_workers=12) as pool:lifecycle=list(pool.map(claim_lifecycle,range(12)))
with ThreadPoolExecutor(max_workers=12) as pool:payment=list(pool.map(claim_payment,range(12)))
with ThreadPoolExecutor(max_workers=12) as pool:sell=list(pool.map(claim_sell,range(12)))
assert len(set(lifecycle))==len(set(payment))==len(set(sell))==12

with psycopg.connect(relay) as conn:
 for ident in lifecycle[:6]:assert conn.execute("SELECT relay_lifecycle_complete_work(%s)",(ident,)).fetchone()==(True,)
 for ident in lifecycle[6:]:assert conn.execute("SELECT relay_lifecycle_retry_work(%s)",(ident,)).fetchone()==(True,)
 for ident in payment[:6]:assert conn.execute("SELECT relay_payment_mark_notification_sent(%s)",(ident,)).fetchone()==(True,)
 for ident in payment[6:]:assert conn.execute("SELECT relay_payment_retry_notification(%s)",(ident,)).fetchone()==(True,)
 for ident in sell[:6]:assert conn.execute("SELECT relay_sell_mark_notification_sent(%s)",(ident,)).fetchone()==(True,)
 for ident in sell[6:]:assert conn.execute("SELECT relay_sell_mark_notification_sent(%s)",(ident,)).fetchone()==(True,)
 assert conn.execute("SELECT relay_lifecycle_complete_work(%s)",(lifecycle[0],)).fetchone()==(False,)
 assert conn.execute("SELECT relay_payment_mark_notification_sent(%s)",(payment[0],)).fetchone()==(False,)
 assert conn.execute("SELECT relay_sell_mark_notification_sent(%s)",(sell[0],)).fetchone()==(False,)

def denied(statement):
 try:
  with psycopg.connect(relay) as conn:conn.execute(statement)
 except psycopg.Error:return
 raise AssertionError(f"statement unexpectedly allowed: {statement}")

for statement in (
 "SELECT * FROM relay_lifecycle_claim_work('bad')",
 "SELECT relay_lifecycle_complete_work(0)",
 "SELECT relay_payment_mark_notification_sent(0)",
 "SELECT relay_payment_retry_notification(0)",
 "SELECT relay_sell_mark_notification_sent(0)",
 "SELECT * FROM order_lifecycle_work","UPDATE order_lifecycle_work SET state='done'",
 "SELECT * FROM payment_notification_outbox","UPDATE payment_notification_outbox SET state='sent'",
 "SELECT * FROM sell_settlement_outbox","UPDATE sell_settlement_outbox SET state='sent'",
):denied(statement)

with psycopg.connect(dsn) as conn:
 assert conn.execute("SELECT state,count(*) FROM order_lifecycle_work GROUP BY state ORDER BY state").fetchall()==[('done',6),('pending',6)]
 assert conn.execute("SELECT state,count(*) FROM payment_notification_outbox GROUP BY state ORDER BY state").fetchall()==[('pending',6),('sent',6)]
 assert conn.execute("SELECT state,count(*) FROM sell_settlement_outbox GROUP BY state ORDER BY state").fetchall()==[('sent',12)]
 assert conn.execute("SELECT min(attempts),max(attempts) FROM order_lifecycle_work").fetchone()==(1,1)
 conn.execute("""CREATE FUNCTION fail_lifecycle_done() RETURNS trigger LANGUAGE plpgsql AS $$
  BEGIN IF NEW.state='done' THEN RAISE EXCEPTION 'injected lifecycle fault';END IF;RETURN NEW;END $$""")
 conn.execute("CREATE TRIGGER fail_done BEFORE UPDATE ON order_lifecycle_work FOR EACH ROW EXECUTE FUNCTION fail_lifecycle_done()")

fault_id=call("SELECT id FROM relay_lifecycle_claim_work(NULL)")[0]
try:call("SELECT relay_lifecycle_complete_work(%s)",(fault_id,))
except psycopg.Error:pass
else:raise AssertionError("injected lifecycle fault unexpectedly committed")

with psycopg.connect(dsn) as conn:
 assert conn.execute("SELECT state FROM order_lifecycle_work WHERE id=%s",(fault_id,)).fetchone()==('sending',)
 assert conn.execute("""SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
  WHERE n.nspname='public' AND p.proname IN ('relay_lifecycle_claim_work','relay_lifecycle_complete_work',
  'relay_lifecycle_retry_work','relay_payment_claim_notification','relay_payment_mark_notification_sent',
  'relay_payment_retry_notification','relay_sell_claim_notification','relay_sell_mark_notification_sent')
  AND has_function_privilege('public',p.oid,'EXECUTE')""").fetchone()==(0,)

print("E0.3 Relay R2 outbox/lifecycle writer rehearsal: OK")
