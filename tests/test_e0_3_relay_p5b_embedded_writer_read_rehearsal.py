import base64
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

dsn=os.getenv("TEST_POSTGRES_DSN")
if not dsn:
 print("E0.3 Relay P5B embedded-writer read rehearsal: skipped (TEST_POSTGRES_DSN unset)")
 raise SystemExit(0)

import psycopg
from psycopg.conninfo import conninfo_to_dict,make_conninfo

ROOT=Path(__file__).resolve().parents[1]
ENVELOPE=(ROOT/"deploy/postgres/proposals/028_e0_relay_acl_envelope.sql").read_text()
PACKAGE=(ROOT/"deploy/postgres/proposals/036_e0_relay_p5b_embedded_writer_read_bodies.sql").read_text()

with psycopg.connect(dsn) as conn:
 conn.execute("""CREATE TABLE orders(order_id bigserial PRIMARY KEY,user_id bigint NOT NULL,
  username text,currency text NOT NULL,rub_amount numeric(20,2) NOT NULL,crypto_address text DEFAULT 'x',
  status text NOT NULL,created_at timestamptz DEFAULT now(),paid_btc_tx text,updated_at timestamptz)""")
 conn.execute("""CREATE TABLE payment_sessions(id bigserial PRIMARY KEY,session_token text,order_id bigint,
  provider text,provider_invoice_id text,status text,expires_at timestamptz,updated_at timestamptz)""")
 conn.execute("CREATE TABLE order_receipts(order_id bigint PRIMARY KEY)")
 conn.execute("CREATE TABLE sent_notifications(order_id bigint,event text,PRIMARY KEY(order_id,event))")
 conn.execute("""CREATE TABLE order_lifecycle_work(id bigserial PRIMARY KEY,kind text,order_id bigint,
  session_token text,provider text,provider_invoice_id text,user_id bigint,currency text,
  rub_amount numeric(20,2),order_status text,has_receipt boolean DEFAULT false,detail text DEFAULT '',
  state text DEFAULT 'pending',attempts integer DEFAULT 0,created_at timestamptz DEFAULT now(),
  claimed_at timestamptz,completed_at timestamptz,updated_at timestamptz DEFAULT now(),
  UNIQUE(kind,order_id,session_token))""")
 conn.execute("""CREATE TABLE support_tickets(ticket_id bigserial PRIMARY KEY,
  id bigint GENERATED ALWAYS AS (ticket_id) STORED UNIQUE,web_user_id bigint,user_id bigint,
  username text,subject text,status text,updated_at timestamptz DEFAULT now())""")
 conn.execute("""CREATE TABLE support_messages(id bigserial PRIMARY KEY,ticket_id bigint,
  sender text,message text,created_at timestamptz DEFAULT now())""")
 conn.execute("CREATE TABLE gift_vouchers(id bigserial PRIMARY KEY,order_id bigint,status text)")
 conn.execute("""CREATE TABLE payment_transition_audit(id bigserial PRIMARY KEY,order_id bigint,
  provider text,action text,from_status text,to_status text,evidence text)""")
 conn.execute("""CREATE TABLE payment_notification_outbox(id bigserial PRIMARY KEY,order_id bigint UNIQUE,
  recipient_id bigint,payload jsonb,state text DEFAULT 'pending',attempts integer DEFAULT 0,
  claimed_at timestamptz,updated_at timestamptz DEFAULT now())""")
 conn.execute("""CREATE TABLE sell_orders(id bigserial PRIMARY KEY,user_id bigint,currency text DEFAULT 'BTC',
  crypto_amount numeric DEFAULT 1,rub_amount numeric(20,2),receive_address text DEFAULT 'x',
  status text,payout_provider text,payout_ref text,payout_status text,updated_at timestamptz DEFAULT now())""")
 conn.execute("""CREATE TABLE sell_settlement_ledger(sell_id bigint PRIMARY KEY,user_id bigint,
  rub_amount numeric(20,2),payout_provider text,payout_ref text,payout_status text)""")
 conn.execute("CREATE TABLE user_vip_volume(user_id bigint PRIMARY KEY,total_rub numeric(20,2),updated_at timestamptz)")
 conn.execute("""CREATE TABLE sell_settlement_outbox(id bigserial PRIMARY KEY,sell_id bigint UNIQUE,
  recipient_id bigint,rub_amount numeric(20,2),state text DEFAULT 'pending')""")
 conn.execute("""INSERT INTO orders(order_id,user_id,currency,rub_amount,status,created_at) VALUES
  (1,7,'BTC',100,'paid',now()),(2,8,'TON',200,'paid',now()),
  (3,9,'BTC',300,'pending',now()-interval '3 hours'),
  (4,10,'BTC',400,'pending',now()-interval '3 hours'),
  (5,11,'BTC',500,'pending',now()),(6,12,'BTC',600,'pending',now()),
  (7,13,'BTC',700,'pending',now())""")
 conn.execute("INSERT INTO order_receipts(order_id) VALUES(4)")
 conn.execute("""INSERT INTO payment_sessions(session_token,order_id,provider,provider_invoice_id,status,expires_at)
  VALUES('expire-brabus',3,'brabus:tbank','inv-3','failed',now()-interval '1 hour'),
  ('active',4,'vertu','inv-4','invoice_created',now()+interval '1 hour'),
  ('fail-token',5,'vertu','inv-5','invoice_created',now()+interval '1 hour'),
  ('pay-token',6,'vertu','inv-6','invoice_created',now()+interval '1 hour'),
  ('fault-token',7,'vertu','inv-7','invoice_created',now()+interval '1 hour')""")
 conn.execute("INSERT INTO support_tickets(ticket_id,web_user_id,username,subject,status) VALUES(1,70,'owner','Subject','closed')")
 conn.execute("INSERT INTO gift_vouchers(order_id,status) VALUES(6,'pending'),(7,'pending')")
 conn.execute("""INSERT INTO sell_orders(id,user_id,rub_amount,status,payout_provider,payout_ref,payout_status) VALUES
  (1,20,1000,'paying','vertu','settle-1','paid'),
  (2,21,2000,'paying','vertu','settle-fault','paid'),
  (3,22,3000,'pending','vertu','wrong-state','paid')""")
 conn.execute(ENVELOPE)
 conn.execute(PACKAGE)

relay_info=conninfo_to_dict(dsn)
relay_info.update(user="obsidian_relay",password="synthetic-rehearsal-only",connect_timeout="5")
relay=make_conninfo(**relay_info)
HEX='ab'*32
TON=base64.b64encode(bytes(range(32))).decode()

with psycopg.connect(relay) as conn:
 assert conn.execute("SELECT * FROM relay_support_user_reply(1,71,'foreign')").fetchall()==[]
 assert conn.execute("SELECT * FROM relay_support_user_reply(1,70,' hello ')").fetchone()==('Subject','owner')
 assert conn.execute("SELECT relay_lifecycle_expire_due(100::smallint)").fetchone()==(1,)
 assert conn.execute("SELECT relay_lifecycle_expire_due(100::smallint)").fetchone()==(0,)
 assert conn.execute("SELECT status FROM relay_order_mark_sent(1,%s)",(HEX,)).fetchone()==('sent',)
 assert conn.execute("SELECT action FROM relay_order_mark_sent(1,%s)",(HEX,)).fetchone()==('status_conflict',)
 ton=conn.execute("SELECT action,txid FROM relay_order_mark_sent(2,%s)",(TON,)).fetchone()
 assert ton==('transitioned',bytes(range(32)).hex())
 assert conn.execute("SELECT action FROM relay_order_mark_sent(999,%s)",(HEX,)).fetchone()==('missing',)
 assert conn.execute("SELECT action FROM relay_order_mark_sent(5,'https://bad')").fetchone()==('invalid_txid',)
 assert conn.execute("SELECT action FROM relay_sell_settle_vertu(3,'wrong-state')").fetchone()==('status_conflict',)

def call(sql,args=()):
 with psycopg.connect(relay) as conn:return conn.execute(sql,args).fetchone()[0]

with ThreadPoolExecutor(max_workers=2) as pool:
 results=list(pool.map(lambda _x:call("SELECT action FROM relay_lifecycle_fail_session(5,'fail-token','vertu','detail')"),range(2)))
assert sorted(results)==['conflict','failed']
with ThreadPoolExecutor(max_workers=2) as pool:
 results=list(pool.map(lambda _x:call("SELECT action FROM relay_payment_mark_paid(6,'vertu','verified','pay-token')"),range(2)))
assert sorted(results)==['already_paid','transitioned']
with ThreadPoolExecutor(max_workers=2) as pool:
 results=list(pool.map(lambda _x:call("SELECT action FROM relay_sell_settle_vertu(1,'settle-1')"),range(2)))
assert sorted(results)==['already_settled','settled']

def denied(statement):
 try:
  with psycopg.connect(relay) as conn:conn.execute(statement)
 except psycopg.Error:return
 raise AssertionError(f"statement unexpectedly allowed: {statement}")

for statement in (
 "SELECT * FROM relay_support_user_reply(1,70,'')",
 "SELECT relay_lifecycle_expire_due(0::smallint)",
 "SELECT * FROM relay_lifecycle_fail_session(5,'','vertu','x')",
 "SELECT * FROM relay_payment_mark_paid(6,'','x',NULL)",
 "SELECT * FROM relay_sell_settle_vertu(1,'')",
 "SELECT * FROM orders","SELECT * FROM payment_sessions","SELECT * FROM sell_orders",
 "SELECT * FROM support_messages","SELECT * FROM sell_settlement_ledger",
):denied(statement)

with psycopg.connect(dsn) as conn:
 assert conn.execute("SELECT count(*) FROM support_messages WHERE ticket_id=1").fetchone()==(1,)
 assert conn.execute("SELECT status FROM support_tickets WHERE id=1").fetchone()==('open',)
 assert conn.execute("SELECT status FROM orders WHERE order_id=3").fetchone()==('expired',)
 assert conn.execute("SELECT count(*) FROM order_lifecycle_work WHERE order_id=3").fetchone()==(2,)
 assert conn.execute("SELECT status FROM payment_sessions WHERE session_token='fail-token'").fetchone()==('failed',)
 assert conn.execute("SELECT count(*) FROM order_lifecycle_work WHERE order_id=5").fetchone()==(2,)
 assert conn.execute("SELECT status FROM gift_vouchers WHERE order_id=6").fetchone()==('paid',)
 assert conn.execute("SELECT count(*) FROM payment_transition_audit WHERE order_id=6").fetchone()==(1,)
 assert conn.execute("SELECT count(*) FROM payment_notification_outbox WHERE order_id=6").fetchone()==(1,)
 assert conn.execute("SELECT status FROM sell_orders WHERE id=1").fetchone()==('paid',)
 assert conn.execute("SELECT total_rub FROM user_vip_volume WHERE user_id=20").fetchone()==(1000,)
 assert conn.execute("SELECT count(*) FROM sell_settlement_outbox WHERE sell_id=1").fetchone()==(1,)
 conn.execute("""CREATE FUNCTION fail_payment_audit() RETURNS trigger LANGUAGE plpgsql AS $$
  BEGIN IF NEW.order_id=7 THEN RAISE EXCEPTION 'injected payment fault';END IF;RETURN NEW;END $$""")
 conn.execute("CREATE TRIGGER fail_payment BEFORE INSERT ON payment_transition_audit FOR EACH ROW EXECUTE FUNCTION fail_payment_audit()")
 conn.execute("""CREATE FUNCTION fail_sell_outbox() RETURNS trigger LANGUAGE plpgsql AS $$
  BEGIN IF NEW.sell_id=2 THEN RAISE EXCEPTION 'injected sell fault';END IF;RETURN NEW;END $$""")
 conn.execute("CREATE TRIGGER fail_sell BEFORE INSERT ON sell_settlement_outbox FOR EACH ROW EXECUTE FUNCTION fail_sell_outbox()")

for sql in ("SELECT * FROM relay_payment_mark_paid(7,'vertu','fault','fault-token')",
            "SELECT * FROM relay_sell_settle_vertu(2,'settle-fault')"):
 try:
  with psycopg.connect(relay) as conn:conn.execute(sql)
 except psycopg.Error:pass
 else:raise AssertionError('injected fault unexpectedly committed')

with psycopg.connect(dsn) as conn:
 assert conn.execute("SELECT status FROM orders WHERE order_id=7").fetchone()==('pending',)
 assert conn.execute("SELECT status FROM payment_sessions WHERE session_token='fault-token'").fetchone()==('invoice_created',)
 assert conn.execute("SELECT status FROM gift_vouchers WHERE order_id=7").fetchone()==('pending',)
 assert conn.execute("SELECT status FROM sell_orders WHERE id=2").fetchone()==('paying',)
 assert conn.execute("SELECT count(*) FROM sell_settlement_ledger WHERE sell_id=2").fetchone()==(0,)
 assert conn.execute("SELECT count(*) FROM user_vip_volume WHERE user_id=21").fetchone()==(0,)
 assert conn.execute("""SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
  WHERE n.nspname='public' AND p.proname LIKE 'relay_%'
  AND has_function_privilege('obsidian_relay',p.oid,'EXECUTE')""").fetchone()[0]==11
 assert conn.execute("""SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
  WHERE n.nspname='public' AND p.proname IN ('relay_support_user_reply','relay_lifecycle_expire_due',
  'relay_lifecycle_fail_session','relay_order_mark_sent','relay_payment_mark_paid','relay_sell_settle_vertu')
  AND has_function_privilege('public',p.oid,'EXECUTE')""").fetchone()[0]==0

print("E0.3 Relay P5B six embedded-writer read bodies rehearsal: OK")
