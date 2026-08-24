import os
from pathlib import Path


dsn=os.getenv("TEST_POSTGRES_DSN")
if not dsn:
 print("E0.3 Relay P3 secure correlation rehearsal: skipped (TEST_POSTGRES_DSN unset)")
 raise SystemExit(0)

import psycopg
from psycopg.conninfo import conninfo_to_dict,make_conninfo


ROOT=Path(__file__).resolve().parents[1]
ENVELOPE=(ROOT/"deploy/postgres/proposals/028_e0_relay_acl_envelope.sql").read_text()
PACKAGE=(ROOT/"deploy/postgres/proposals/031_e0_relay_p3_secure_correlation_reads.sql").read_text()


with psycopg.connect(dsn) as conn:
 conn.execute("""CREATE TABLE orders(
  order_id bigserial PRIMARY KEY,user_id bigint NOT NULL,currency text,rub_amount numeric,
  crypto_address text,network text,status text,created_at timestamptz DEFAULT now(),
  updated_at timestamptz DEFAULT now())""")
 conn.execute("""CREATE TABLE payment_sessions(
  id bigserial PRIMARY KEY,session_token text,order_id bigint,status text,created_at timestamptz DEFAULT now())""")
 conn.execute("""CREATE TABLE swap_sessions(
  id bigserial PRIMARY KEY,session_token text UNIQUE,user_id bigint,coin_from text,coin_to text,
  amount_from numeric,address_to text,trocador_id text,trocador_url text,status text,
  provider text,deposit_address text)""")
 conn.execute("""CREATE TABLE payment_notification_outbox(
  id bigserial PRIMARY KEY,order_id bigint,recipient_id bigint,payload jsonb,state text,
  attempts integer DEFAULT 0,claimed_at timestamptz,updated_at timestamptz DEFAULT now())""")
 conn.execute("CREATE TABLE support_tickets(ticket_id bigserial PRIMARY KEY,web_user_id bigint,subject text,status text)")
 conn.execute("CREATE TABLE payment_transition_audit(id bigserial PRIMARY KEY,order_id bigint,from_status text,to_status text,evidence text)")
 conn.execute("""INSERT INTO orders(user_id,currency,rub_amount,crypto_address,network,status,created_at) VALUES
  (7,'BTC',100,'own-destination','MAINNET','pending',now()-interval '10 seconds'),
  (8,'BTC',100,'own-destination','MAINNET','pending',now()-interval '5 seconds'),
  (7,'BTC',100,'old-destination','MAINNET','pending',now()-interval '301 seconds')""")
 conn.execute("""INSERT INTO payment_sessions(session_token,order_id,status,created_at) VALUES
  ('own-old',1,'invoice_created',now()-interval '2 seconds'),
  ('own-latest',1,'awaiting_payment',now()-interval '1 second'),
  ('foreign',2,'invoice_created',now()),('expired',1,'expired',now()+interval '1 second')""")
 conn.execute("""INSERT INTO swap_sessions(session_token,user_id,coin_from,coin_to,amount_from,address_to,
  trocador_id,trocador_url,status,provider,deposit_address) VALUES
  ('swap-own',7,'BTC','LTC',1.25,'owner-destination','external-own','https://provider/own',
   'waiting','trocador','deposit-own'),
  ('swap-foreign',8,'BTC','LTC',9.99,'foreign-destination','external-foreign',
   'https://provider/foreign','waiting','trocador','deposit-foreign')""")
 conn.execute(ENVELOPE)
 conn.execute(PACKAGE)

relay=conninfo_to_dict(dsn)
relay.update(user="obsidian_relay",password="synthetic-rehearsal-only",connect_timeout="2")
relay=make_conninfo(**relay)

with psycopg.connect(relay) as conn:
 duplicate=conn.execute("""SELECT * FROM relay_order_recent_duplicate(
  7,'BTC',100,'own-destination','MAINNET','MAINNET',90::smallint)""").fetchone()
 assert duplicate==(1,'own-latest')
 assert conn.execute("""SELECT * FROM relay_order_recent_duplicate(
  8,'BTC',100,'missing','MAINNET','MAINNET',90::smallint)""").fetchall()==[]
 assert conn.execute("SELECT relay_payment_session_token_matches_order(1,'own-latest')").fetchone()[0] is True
 assert conn.execute("SELECT relay_payment_session_token_matches_order(1,'foreign')").fetchone()[0] is False
 swap=conn.execute("SELECT * FROM relay_swap_get_by_token('swap-own')").fetchone()
 assert swap[0]=='swap-own' and swap[5]=='owner-destination' and swap[10]=='deposit-own'
 assert conn.execute("SELECT * FROM relay_swap_get_by_token('missing')").fetchall()==[]

def denied(statement,params=()):
 try:
  with psycopg.connect(relay) as conn:conn.execute(statement,params)
 except psycopg.Error:return
 raise AssertionError(f"statement unexpectedly allowed: {statement}")

for statement in (
 "SELECT * FROM relay_order_recent_duplicate(7,'BTC',100,'x','MAINNET','MAINNET',301::smallint)",
 "SELECT * FROM relay_order_recent_duplicate(7,'DOGE',100,'x','MAINNET','MAINNET',90::smallint)",
 "SELECT relay_payment_session_token_matches_order(1,'')",
 "SELECT relay_payment_session_token_matches_order(NULL,NULL)",
 "SELECT * FROM relay_swap_get_by_token('')",
 "SELECT * FROM relay_swap_get_by_token(NULL)",
 "SELECT * FROM orders","SELECT * FROM payment_sessions","SELECT * FROM swap_sessions",
):denied(statement)

with psycopg.connect(dsn) as conn:
 assert conn.execute("""SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
  WHERE n.nspname='public' AND p.proname LIKE 'relay_%'
  AND has_function_privilege('obsidian_relay',p.oid,'EXECUTE')""").fetchone()[0]==8
 assert conn.execute("""SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
  WHERE n.nspname='public' AND p.proname IN ('relay_order_recent_duplicate',
   'relay_payment_session_token_matches_order','relay_swap_get_by_token')
  AND has_function_privilege('public',p.oid,'EXECUTE')""").fetchone()[0]==0

print("E0.3 Relay P3 secure duplicate/token correlation rehearsal: OK")
