import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

dsn=os.getenv("TEST_POSTGRES_DSN")
if not dsn:
 print("E0.3 Relay R4 intent-creation writer rehearsal: skipped (TEST_POSTGRES_DSN unset)")
 raise SystemExit(0)

import psycopg
from psycopg.conninfo import conninfo_to_dict,make_conninfo

ROOT=Path(__file__).resolve().parents[1]
ENVELOPE=(ROOT/"deploy/postgres/proposals/028_e0_relay_acl_envelope.sql").read_text()
PACKAGE=(ROOT/"deploy/postgres/proposals/040_e0_relay_r4_intent_creation_writers.sql").read_text()

with psycopg.connect(dsn) as conn:
 conn.execute("""CREATE TABLE orders(order_id bigserial PRIMARY KEY,user_id bigint,username text,
  currency text,rub_amount numeric,crypto_address text,status text,created_at timestamptz DEFAULT now(),
  updated_at timestamptz,web_user_id bigint,network text,agreed_rate numeric,
  agreed_crypto_amount numeric,agreed_at timestamptz)""")
 conn.execute("""CREATE TABLE sell_orders(id bigserial PRIMARY KEY,user_id bigint,currency text,
  crypto_amount numeric,rub_amount numeric,sbp_phone text,receive_address text,status text,
  payout_method text,payout_bank text,payout_details text,payout_name text,created_at timestamptz DEFAULT now())""")
 conn.execute("""CREATE TABLE swap_sessions(id bigserial PRIMARY KEY,session_token text UNIQUE,user_id bigint,
  coin_from text,coin_to text,amount_from numeric,address_to text,trocador_id text,trocador_url text,
  status text,web_user_id bigint,provider text,deposit_address text,created_at timestamptz DEFAULT now())""")
 conn.execute("""CREATE TABLE payment_notification_outbox(id bigserial PRIMARY KEY,order_id bigint,
  recipient_id bigint,payload jsonb,state text,attempts integer,claimed_at timestamptz,updated_at timestamptz)""")
 conn.execute("CREATE TABLE payment_transition_audit(id bigserial PRIMARY KEY,order_id bigint,from_status text,to_status text,evidence text)")
 conn.execute("CREATE TABLE support_tickets(ticket_id bigserial PRIMARY KEY,web_user_id bigint,subject text,status text)")
 conn.execute(ENVELOPE);conn.execute(PACKAGE)

info=conninfo_to_dict(dsn);info.update(user="obsidian_relay",password="synthetic-rehearsal-only",connect_timeout="5")
relay=make_conninfo(**info)
def call(sql,args=()):
 with psycopg.connect(relay) as conn:return conn.execute(sql,args).fetchone()[0]

def create_order(n):return call("SELECT relay_order_create(%s,'u','btc',100,'addr',NULL,'btc',10,0.1)",(n+1,))
def create_sell(n):return call("SELECT relay_sell_create(%s,'btc',0.1,100,'','recv','sbp','bank','details','name')",(n+1,))
def create_swap(n):return call("SELECT relay_swap_create(%s,%s,'btc','ltc',0.1,'addr',%s,'url','waiting',NULL,'swapuz','deposit')",(f'token-{n:020d}',n+1,f'external-{n}'))
with ThreadPoolExecutor(max_workers=12) as pool:orders=list(pool.map(create_order,range(12)))
with ThreadPoolExecutor(max_workers=12) as pool:sells=list(pool.map(create_sell,range(12)))
with ThreadPoolExecutor(max_workers=12) as pool:swaps=list(pool.map(create_swap,range(12)))
assert len(set(orders))==len(set(sells))==len(set(swaps))==12
web_swap=call("SELECT relay_swap_create('token-web-0000000001',-7,'btc','eth',1,'addr','ext-web','url','waiting',7,'swapuz','deposit')")

def denied(statement):
 try:
  with psycopg.connect(relay) as conn:conn.execute(statement)
 except psycopg.Error:return
 raise AssertionError(f"statement unexpectedly allowed: {statement}")
for statement in (
 "SELECT relay_order_create(0,NULL,'BTC',1,'a',NULL,NULL,1,1)",
 "SELECT relay_sell_create(1,'BTC',0,1,'','a',NULL,NULL,NULL,NULL)",
 "SELECT relay_swap_create('short',1,'BTC','BTC',1,'a','e','u','waiting',NULL,'swapuz','d')",
 "SELECT relay_swap_create('token-invalid-0001',1,'BTC','ETH',1,'a','e','u','paid',NULL,'swapuz','d')",
 "SELECT * FROM orders","INSERT INTO orders(user_id,currency,rub_amount,crypto_address,status) VALUES(1,'BTC',1,'a','sent')",
 "SELECT * FROM sell_orders","SELECT * FROM swap_sessions",
):denied(statement)

with psycopg.connect(dsn) as conn:
 assert conn.execute("SELECT count(*),min(status),max(status) FROM orders").fetchone()==(12,'pending','pending')
 assert conn.execute("SELECT count(*),min(status),max(status) FROM sell_orders").fetchone()==(12,'pending','pending')
 assert conn.execute("SELECT status,provider,user_id,web_user_id FROM swap_sessions WHERE id=%s",(web_swap,)).fetchone()==('waiting','swapuz',-7,7)
 assert conn.execute("SELECT count(*) FROM swap_sessions").fetchone()==(13,)
 conn.execute("""CREATE FUNCTION fail_order_create() RETURNS trigger LANGUAGE plpgsql AS $$
  BEGIN IF NEW.crypto_address='fault' THEN RAISE EXCEPTION 'injected create fault';END IF;RETURN NEW;END $$""")
 conn.execute("CREATE TRIGGER fail_create BEFORE INSERT ON orders FOR EACH ROW EXECUTE FUNCTION fail_order_create()")
for sql in ("SELECT relay_order_create(1,NULL,'BTC',1,'fault',NULL,NULL,1,1)",):
 try:call(sql)
 except psycopg.Error:pass
 else:raise AssertionError('injected creation fault unexpectedly committed')
with psycopg.connect(dsn) as conn:
 assert conn.execute("SELECT count(*) FROM orders").fetchone()==(12,)
 assert conn.execute("""SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
  WHERE n.nspname='public' AND p.proname IN ('relay_order_create','relay_sell_create','relay_swap_create')
  AND has_function_privilege('public',p.oid,'EXECUTE')""").fetchone()==(0,)
print("E0.3 Relay R4 intent-creation writer rehearsal: OK")
