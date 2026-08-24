import os
from pathlib import Path


dsn=os.getenv("TEST_POSTGRES_DSN")
if not dsn:
 print("E0.3 Relay P7/P1 read rehearsal: skipped (TEST_POSTGRES_DSN unset)")
 raise SystemExit(0)

import psycopg
from psycopg.conninfo import conninfo_to_dict,make_conninfo


ROOT=Path(__file__).resolve().parents[1]
ENVELOPE=(ROOT/"deploy/postgres/proposals/028_e0_relay_acl_envelope.sql").read_text()
PACKAGE=(ROOT/"deploy/postgres/proposals/029_e0_relay_p7_p1_read_functions.sql").read_text()


with psycopg.connect(dsn) as conn:
 conn.execute("""CREATE TABLE orders(
  order_id bigserial PRIMARY KEY,user_id bigint NOT NULL,username text,currency text NOT NULL,
  rub_amount numeric(20,2) NOT NULL,crypto_address text NOT NULL DEFAULT '',status text NOT NULL,
  created_at timestamptz NOT NULL,updated_at timestamptz NOT NULL DEFAULT now(),network text,
  agreed_rate numeric,agreed_crypto_amount numeric,agreed_at timestamptz,paid_btc_tx text,
  web_user_id bigint,rub_volume_counted boolean NOT NULL DEFAULT false,
  verification_requested text,montera_invoice_id text,receipt_sent_at timestamptz,
  receipt_deadline timestamptz)""")
 conn.execute("""CREATE TABLE sell_orders(
  id bigserial PRIMARY KEY,user_id bigint NOT NULL,currency text NOT NULL,crypto_amount numeric,
  rub_amount numeric,sbp_phone text,receive_address text,status text,tx_hash text,
  created_at timestamptz,updated_at timestamptz,payout_method text,payout_bank text,
  payout_details text,payout_name text,payout_provider text,payout_ref text,payout_status text)""")
 conn.execute("CREATE TABLE sent_notifications(order_id bigint,event text,PRIMARY KEY(order_id,event))")
 conn.execute("CREATE TABLE reserves(currency text PRIMARY KEY,amount numeric(30,12) NOT NULL)")
 conn.execute("""CREATE TABLE payment_notification_outbox(
  id bigserial PRIMARY KEY,order_id bigint,recipient_id bigint,payload jsonb,state text,
  attempts integer DEFAULT 0,claimed_at timestamptz,updated_at timestamptz DEFAULT now())""")
 conn.execute("""CREATE TABLE support_tickets(
  ticket_id bigserial PRIMARY KEY,web_user_id bigint,subject text,status text)""")
 conn.execute("""CREATE TABLE payment_transition_audit(
  id bigserial PRIMARY KEY,order_id bigint,from_status text,to_status text,evidence text)""")
 conn.execute("""INSERT INTO orders(user_id,currency,rub_amount,status,created_at) VALUES
  (1,'BTC',100,'sent',date_trunc('day',now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'+interval '1 hour'),
  (2,'BTC',200,'sent',now()-interval '25 hours'),
  (3,'BTC',300,'paid',date_trunc('day',now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'+interval '2 hours'),
  (4,'BTC',400,'pending',date_trunc('day',now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'+interval '3 hours'),
  (5,'BTC',500,'expired',date_trunc('day',now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'+interval '4 hours'),
  (6,'BTC',600,'failed',now()-interval '2 days')""")
 conn.execute("INSERT INTO reserves(currency,amount) VALUES('A_NEG',-1)")
 conn.execute("""INSERT INTO reserves(currency,amount)
  SELECT 'C'||lpad(n::text,2,'0'),n+1 FROM generate_series(0,64) n""")
 conn.execute(ENVELOPE)
 conn.execute(PACKAGE)


relay=conninfo_to_dict(dsn)
relay.update(user="obsidian_relay",password="synthetic-rehearsal-only",connect_timeout="2")
relay=make_conninfo(**relay)


with psycopg.connect(relay) as conn:
 conn.execute("SET TIME ZONE 'Pacific/Honolulu'")
 assert conn.execute("SELECT * FROM relay_runtime_schema_validate_shared()").fetchall()==[]
 assert conn.execute("SELECT * FROM relay_reporting_public_stats()").fetchone()==(1,2,100,300)
 assert conn.execute("SELECT * FROM relay_reporting_site_stats()").fetchone()==(6,3,4)
 assert conn.execute("SELECT * FROM relay_reporting_today_status_counts()").fetchone()==(4,1,2,1)
 all_reserves=conn.execute("SELECT * FROM relay_reporting_reserves(false)").fetchall()
 positive=conn.execute("SELECT * FROM relay_reporting_reserves(true)").fetchall()
 assert len(all_reserves)==len(positive)==64
 assert all_reserves[0][0]=="A_NEG" and all(amount>0 for _,amount in positive)
 try:
  conn.execute("SELECT * FROM relay_reporting_reserves(NULL)")
 except psycopg.Error as exc:
  assert "positive_only_required" in str(exc)
 else:
  raise AssertionError("NULL positive_only unexpectedly accepted")


def denied(statement):
 try:
  with psycopg.connect(relay) as conn:conn.execute(statement)
 except psycopg.Error:return
 raise AssertionError(f"statement unexpectedly allowed: {statement}")


for statement in (
 "SELECT * FROM orders","SELECT * FROM reserves","SELECT * FROM sell_orders",
 "SELECT * FROM sent_notifications","UPDATE reserves SET amount=0",
):denied(statement)


with psycopg.connect(dsn) as conn:
 assert conn.execute("""SELECT
  has_table_privilege('obsidian_relay_metadata_owner','orders','SELECT'),
  has_table_privilege('obsidian_relay_metadata_owner','sell_orders','SELECT'),
  has_table_privilege('obsidian_relay_metadata_owner','sent_notifications','SELECT'),
  has_table_privilege('obsidian_relay_owner','orders','SELECT'),
  has_column_privilege('obsidian_relay_owner','orders','rub_amount','SELECT'),
  has_table_privilege('obsidian_relay','reserves','SELECT')""").fetchone()==(
   False,False,False,False,True,False,
  )
 assert conn.execute("""SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
  WHERE n.nspname='public' AND p.proname LIKE 'relay_%'
    AND has_function_privilege('obsidian_relay',p.oid,'EXECUTE')""").fetchone()[0]==10
 assert conn.execute("""SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
  WHERE n.nspname='public' AND p.proname IN (
   'relay_runtime_schema_validate_shared','relay_reporting_public_stats',
   'relay_reporting_reserves','relay_reporting_site_stats',
   'relay_reporting_today_status_counts')
   AND has_function_privilege('public',p.oid,'EXECUTE')""").fetchone()[0]==0
 conn.execute("ALTER TABLE sell_orders DROP COLUMN payout_name")

with psycopg.connect(relay) as conn:
 missing=conn.execute("SELECT * FROM relay_runtime_schema_validate_shared()").fetchall()
 assert missing==[("sell_orders",["payout_name"])]

print("E0.3 Relay P7 metadata and P1 public aggregate production-body rehearsal: OK")
