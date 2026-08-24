import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

dsn=os.getenv("TEST_POSTGRES_DSN")
if not dsn:
 print("E0.3 Relay P6 provider callback rehearsal: skipped (TEST_POSTGRES_DSN unset)")
 raise SystemExit(0)

import psycopg
from psycopg.conninfo import conninfo_to_dict,make_conninfo

ROOT=Path(__file__).resolve().parents[1]
ENVELOPE=(ROOT/"deploy/postgres/proposals/028_e0_relay_acl_envelope.sql").read_text()
PACKAGE=(ROOT/"deploy/postgres/proposals/033_e0_relay_p6_provider_callback_bodies.sql").read_text()

with psycopg.connect(dsn) as conn:
 conn.execute("""CREATE TABLE orders(order_id bigserial PRIMARY KEY,user_id bigint NOT NULL,
  status text NOT NULL,rub_amount numeric(20,2) NOT NULL,verification_requested text,
  updated_at timestamptz DEFAULT now())""")
 conn.execute("""CREATE TABLE sell_orders(id bigserial PRIMARY KEY,user_id bigint NOT NULL,
  rub_amount numeric(20,2) NOT NULL,payout_ref text,payout_status text,payout_provider text)""")
 conn.execute("""CREATE TABLE swap_sessions(id bigserial PRIMARY KEY,session_token text,user_id bigint,
  coin_from text,coin_to text,amount_from numeric(30,12),address_to text,trocador_id text,
  trocador_url text,status text,provider text,deposit_address text)""")
 conn.execute("""CREATE TABLE payment_notification_outbox(id bigserial PRIMARY KEY,order_id bigint,
  recipient_id bigint,payload jsonb,state text,attempts integer DEFAULT 0,claimed_at timestamptz,
  updated_at timestamptz DEFAULT now())""")
 conn.execute("CREATE TABLE support_tickets(ticket_id bigserial PRIMARY KEY,web_user_id bigint,subject text,status text)")
 conn.execute("CREATE TABLE payment_transition_audit(id bigserial PRIMARY KEY,order_id bigint,from_status text,to_status text,evidence text)")
 conn.execute("INSERT INTO orders(order_id,user_id,status,rub_amount) VALUES(1,7,'pending',100),(2,8,'paid',200),(3,9,'pending',300)")
 conn.execute("""INSERT INTO sell_orders(id,user_id,rub_amount,payout_ref,payout_status,payout_provider) VALUES
  (1,7,100,'exact-ref','pending','vertu'),(2,8,200,'suffix','pending','vertu'),
  (3,9,300,'collision','pending','vertu'),(4,10,400,'collision','pending','vertu'),
  (5,11,500,'wrong-provider','pending','other')""")
 conn.execute("""INSERT INTO swap_sessions(session_token,user_id,coin_from,coin_to,amount_from,
  address_to,trocador_id,trocador_url,status,provider,deposit_address) VALUES
  ('swap-token',7,'BTC','ETH',1.25,'destination','provider-42','https://provider/42',
   'waiting','trocador','deposit')""")
 conn.execute(ENVELOPE)
 conn.execute(PACKAGE)

relay_info=conninfo_to_dict(dsn)
relay_info.update(user="obsidian_relay",password="synthetic-rehearsal-only",connect_timeout="2")
relay=make_conninfo(**relay_info)

def request_once():
 with psycopg.connect(relay) as conn:
  return conn.execute("SELECT action FROM relay_order_request_verification(1,'video')").fetchone()[0]

with ThreadPoolExecutor(max_workers=12) as pool:
 actions=list(pool.map(lambda _x:request_once(),range(12)))
assert actions.count('requested')==1 and actions.count('conflict')==11

with psycopg.connect(relay) as conn:
 assert conn.execute("SELECT * FROM relay_order_request_verification(2,'pdf-success')").fetchone()[0]=='conflict'
 assert conn.execute("SELECT * FROM relay_order_request_verification(999,'video')").fetchone()==('missing',999,None,None,None)
 assert conn.execute("SELECT id FROM relay_sell_vertu_payout_by_ref('exact-ref')").fetchone()==(1,)
 assert conn.execute("SELECT id FROM relay_sell_vertu_payout_by_ref('callback_suffix')").fetchone()==(2,)
 assert conn.execute("SELECT * FROM relay_sell_vertu_payout_by_ref('callback_collision')").fetchall()==[]
 assert conn.execute("SELECT * FROM relay_sell_vertu_payout_by_ref('wrong-provider')").fetchall()==[]
 swap=conn.execute("SELECT * FROM relay_swap_get_by_external_id('provider-42')").fetchone()
 assert swap==('swap-token',7,'BTC','ETH',1.25,'destination','provider-42',
               'https://provider/42','waiting','trocador','deposit')
 assert conn.execute("SELECT * FROM relay_swap_get_by_external_id('missing')").fetchall()==[]

def denied(statement):
 try:
  with psycopg.connect(relay) as conn:conn.execute(statement)
 except psycopg.Error:return
 raise AssertionError(f"statement unexpectedly allowed: {statement}")

for statement in (
 "SELECT * FROM relay_order_request_verification(0,'video')",
 "SELECT * FROM relay_order_request_verification(1,'other')",
 "SELECT * FROM relay_sell_vertu_payout_by_ref('')",
 "SELECT * FROM relay_swap_get_by_external_id(repeat('x',257))",
 "SELECT * FROM orders","SELECT * FROM sell_orders","SELECT * FROM swap_sessions",
 "UPDATE orders SET status='paid' WHERE order_id=3",
):denied(statement)

with psycopg.connect(dsn) as conn:
 conn.execute("""CREATE FUNCTION fail_verification_update() RETURNS trigger LANGUAGE plpgsql AS $$
  BEGIN RAISE EXCEPTION 'injected verification fault'; END $$""")
 conn.execute("""CREATE TRIGGER fail_verification BEFORE UPDATE ON orders
  FOR EACH ROW WHEN (OLD.order_id=3) EXECUTE FUNCTION fail_verification_update()""")
try:
 with psycopg.connect(relay) as conn:conn.execute("SELECT * FROM relay_order_request_verification(3,'video')")
except psycopg.Error:
 pass
else:
 raise AssertionError("injected fault unexpectedly committed")
with psycopg.connect(dsn) as conn:
 assert conn.execute("SELECT verification_requested FROM orders WHERE order_id=3").fetchone()==(None,)
 assert conn.execute("""SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
  WHERE n.nspname='public' AND p.proname LIKE 'relay_%'
  AND has_function_privilege('obsidian_relay',p.oid,'EXECUTE')""").fetchone()[0]==8
 assert conn.execute("""SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
  WHERE n.nspname='public' AND p.proname IN ('relay_order_request_verification',
  'relay_sell_vertu_payout_by_ref','relay_swap_get_by_external_id')
  AND has_function_privilege('public',p.oid,'EXECUTE')""").fetchone()[0]==0

print("E0.3 Relay P6 three provider callback bodies rehearsal: OK")
