import os
from pathlib import Path


dsn=os.getenv("TEST_POSTGRES_DSN")
if not dsn:
 print("E0.3 Relay P2 customer read rehearsal: skipped (TEST_POSTGRES_DSN unset)")
 raise SystemExit(0)

import psycopg
from psycopg.conninfo import conninfo_to_dict,make_conninfo


ROOT=Path(__file__).resolve().parents[1]
ENVELOPE=(ROOT/"deploy/postgres/proposals/028_e0_relay_acl_envelope.sql").read_text()
PACKAGE=(ROOT/"deploy/postgres/proposals/030_e0_relay_p2_customer_read_functions.sql").read_text()


with psycopg.connect(dsn) as conn:
 conn.execute("""CREATE TABLE orders(
  order_id bigserial PRIMARY KEY,user_id bigint NOT NULL,web_user_id bigint,username text,
  rub_amount numeric(20,2) NOT NULL,crypto_address text NOT NULL,currency text NOT NULL,
  status text NOT NULL,created_at timestamptz NOT NULL DEFAULT now(),paid_btc_tx text,
  network text,receipt_sent_at timestamptz,updated_at timestamptz DEFAULT now())""")
 conn.execute("""CREATE TABLE payment_sessions(
  id bigserial PRIMARY KEY,session_token text,order_id bigint,status text,created_at timestamptz DEFAULT now())""")
 conn.execute("CREATE TABLE order_receipts(order_id bigint PRIMARY KEY)")
 conn.execute("""CREATE TABLE support_tickets(
  ticket_id bigserial PRIMARY KEY,id bigint GENERATED ALWAYS AS (ticket_id) STORED UNIQUE,
  web_user_id bigint,subject text,status text,created_at timestamptz DEFAULT now(),
  updated_at timestamptz DEFAULT now())""")
 conn.execute("""CREATE TABLE support_messages(
  id bigserial PRIMARY KEY,ticket_id bigint,sender text,message text,created_at timestamptz DEFAULT now())""")
 conn.execute("""CREATE TABLE payment_notification_outbox(
  id bigserial PRIMARY KEY,order_id bigint,recipient_id bigint,payload jsonb,state text DEFAULT 'pending',
  attempts integer DEFAULT 0,claimed_at timestamptz,updated_at timestamptz DEFAULT now())""")
 conn.execute("""CREATE TABLE payment_transition_audit(
  id bigserial PRIMARY KEY,order_id bigint,from_status text,to_status text,evidence text)""")
 conn.execute("CREATE TABLE referrals(referrer_id bigint,referred_id bigint,total_bonus_btc numeric(30,12))")
 conn.execute("""CREATE TABLE swap_sessions(
  id bigserial PRIMARY KEY,session_token text,web_user_id bigint,user_id bigint,coin_from text,
  coin_to text,amount_from numeric,status text,created_at timestamptz DEFAULT now())""")
 conn.execute("CREATE TABLE referral_addresses(user_id bigint,currency text,address text,PRIMARY KEY(user_id,currency))")
 conn.execute("""CREATE TABLE sell_orders(
  id bigserial PRIMARY KEY,user_id bigint,currency text,crypto_amount numeric(30,12),
  rub_amount numeric(20,2),sbp_phone text,receive_address text,status text,
  created_at timestamptz DEFAULT now(),payout_method text,payout_details text,payout_bank text)""")
 conn.execute("""INSERT INTO orders(user_id,web_user_id,rub_amount,crypto_address,currency,status,created_at)
  SELECT 7,70,n,'own-'||n,'BTC',CASE WHEN n=1 THEN 'sent' ELSE 'pending' END,now()+n*interval '1 second'
  FROM generate_series(1,105) n""")
 conn.execute("""INSERT INTO orders(user_id,web_user_id,rub_amount,crypto_address,currency,status)
  VALUES(8,80,999,'foreign','BTC','sent'),(9,70,777,'web-own','LTC','pending')""")
 conn.execute("""INSERT INTO payment_sessions(session_token,order_id,status,created_at) VALUES
  ('active-own',105,'invoice_created',now()),('failed-newer',105,'failed',now()+interval '1 minute'),
  ('foreign-token',106,'invoice_created',now())""")
 conn.execute("INSERT INTO order_receipts(order_id) VALUES(1),(105),(106)")
 conn.execute("""INSERT INTO support_tickets(web_user_id,subject,status,created_at,updated_at)
  SELECT 70,'own-'||n,CASE WHEN n=1 THEN 'closed' ELSE 'open' END,now(),now()+n*interval '1 second'
  FROM generate_series(1,105)n""")
 conn.execute("INSERT INTO support_tickets(web_user_id,subject,status) VALUES(80,'foreign','open')")
 conn.execute("""INSERT INTO support_messages(ticket_id,sender,message,created_at)
  SELECT 1,'user','m'||n,now()+n*interval '1 second' FROM generate_series(1,505)n""")
 conn.execute("INSERT INTO support_messages(ticket_id,sender,message) VALUES(106,'user','foreign')")
 conn.execute("INSERT INTO referrals VALUES(7,20,0.1),(7,21,0.2),(8,22,9.9)")
 conn.execute("INSERT INTO orders(user_id,rub_amount,crypto_address,currency,status) VALUES(20,1,'r','BTC','sent')")
 conn.execute("""INSERT INTO swap_sessions(session_token,web_user_id,user_id,coin_from,coin_to,amount_from,status,created_at)
  SELECT 'own-swap-'||n,70,7,'BTC','LTC',n,'waiting',now()+n*interval '1 second'
  FROM generate_series(1,101)n""")
 conn.execute("INSERT INTO swap_sessions(session_token,web_user_id,user_id,coin_from,coin_to,amount_from,status) VALUES('foreign-swap',80,8,'BTC','LTC',999,'waiting')")
 conn.execute("INSERT INTO referral_addresses VALUES(7,'BTC','own-address'),(8,'BTC','foreign-address')")
 conn.execute("""INSERT INTO sell_orders(user_id,currency,crypto_amount,rub_amount,sbp_phone,receive_address,status,payout_method,payout_details,payout_bank,created_at)
  SELECT 7,'BTC',n,n*100,'own-phone-'||n,'own-deposit-'||n,
   CASE WHEN n<=100 THEN 'pending' ELSE 'paid' END,'sbp','own-detail-'||n,'own-bank',now()+n*interval '1 second'
  FROM generate_series(1,101)n""")
 conn.execute("""INSERT INTO sell_orders(user_id,currency,crypto_amount,rub_amount,sbp_phone,receive_address,status,payout_method,payout_details,payout_bank)
  VALUES(8,'BTC',9,999,'foreign-phone','foreign-deposit','pending','sbp','foreign-detail','foreign-bank')""")
 conn.execute(ENVELOPE)
 conn.execute(PACKAGE)


relay=conninfo_to_dict(dsn)
relay.update(user="obsidian_relay",password="synthetic-rehearsal-only",connect_timeout="2")
relay=make_conninfo(**relay)


with psycopg.connect(relay) as conn:
 assert conn.execute("SELECT relay_support_exists_for_web_user(1,70)").fetchone()[0] is True
 assert conn.execute("SELECT relay_support_exists_for_web_user(1,80)").fetchone()[0] is False
 tickets=conn.execute("SELECT * FROM relay_support_list_for_web_user(70)").fetchall()
 assert len(tickets)==100 and all(row[1]!="foreign" for row in tickets)
 assert conn.execute("SELECT relay_support_open_count_for_web_user(70)").fetchone()[0]==104
 assert conn.execute("SELECT relay_support_open_count_for_web_user(80)").fetchone()[0]==1
 thread=conn.execute("SELECT * FROM relay_support_thread_for_web_user(1,70)").fetchone()
 assert len(thread[3])==500 and thread[3][0]["message"]=="m6" and thread[3][-1]["message"]=="m505"
 assert conn.execute("SELECT * FROM relay_support_thread_for_web_user(1,80)").fetchall()==[]
 referral=conn.execute("SELECT * FROM relay_engagement_referral_stats(7)").fetchone()
 assert referral[:2]==(2,1) and float(referral[2])==0.3
 orders=conn.execute("SELECT * FROM relay_order_customer_orders(7,100::smallint,0)").fetchall()
 assert len(orders)==100 and all("foreign" not in row[2] for row in orders)
 assert orders[0][-1]=="active-own"
 web=conn.execute("SELECT * FROM relay_order_web_customer_orders(70,7,100::smallint)").fetchall()
 assert len(web)==100 and all(row[2]!="foreign" for row in web)
 assert conn.execute("SELECT * FROM relay_order_web_customer_orders(999,NULL,10::smallint)").fetchall()==[]
 receipts=conn.execute("SELECT * FROM relay_order_receipt_order_ids(ARRAY[1,105,106],7,70)").fetchall()
 assert receipts==[(1,),(105,)]
 assert conn.execute("SELECT * FROM relay_order_receipt_order_ids(ARRAY[106],7,70)").fetchall()==[]
 swaps=conn.execute("SELECT * FROM relay_swap_swaps_for_web_user(70,7,100::smallint)").fetchall()
 assert len(swaps)==100 and all(row[0]!="foreign-swap" for row in swaps)
 assert conn.execute("SELECT * FROM relay_user_profile_referral_address(7,'BTC')").fetchall()==[("own-address",)]
 assert conn.execute("SELECT * FROM relay_user_profile_referral_address(7,'LTC')").fetchall()==[]
 pending=conn.execute("SELECT * FROM relay_sell_pending_view_for_user(7,100::smallint)").fetchall()
 history=conn.execute("SELECT * FROM relay_sell_sells_for_user(7,100::smallint)").fetchall()
 assert len(pending)==len(history)==100
 assert all("foreign" not in "|".join(str(v) for v in row) for row in pending+history)


def denied(statement,params=()):
 try:
  with psycopg.connect(relay) as conn:conn.execute(statement,params)
 except psycopg.Error:return
 raise AssertionError(f"statement unexpectedly allowed: {statement}")


for statement,params in (
 ("SELECT * FROM relay_order_customer_orders(7,101::smallint,0)",()),
 ("SELECT * FROM relay_order_customer_orders(7,1::smallint,1000001)",()),
 ("SELECT * FROM relay_order_web_customer_orders(70,7,101::smallint)",()),
 ("SELECT * FROM relay_order_receipt_order_ids(%s,7,70)",([*range(1,102)],)),
 ("SELECT * FROM relay_order_receipt_order_ids(ARRAY[1],NULL,NULL)",()),
 ("SELECT * FROM relay_swap_swaps_for_web_user(70,7,101::smallint)",()),
 ("SELECT * FROM relay_user_profile_referral_address(7,'ETH')",()),
 ("SELECT * FROM relay_sell_sells_for_user(7,101::smallint)",()),
):denied(statement,params)

for table in ("orders","payment_sessions","order_receipts","support_tickets","support_messages",
 "referrals","swap_sessions","referral_addresses","sell_orders"):
 denied(f"SELECT * FROM {table}")


with psycopg.connect(dsn) as conn:
 assert conn.execute("""SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
  WHERE n.nspname='public' AND p.proname LIKE 'relay_%'
  AND has_function_privilege('obsidian_relay',p.oid,'EXECUTE')""").fetchone()[0]==17
 assert conn.execute("""SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
  WHERE n.nspname='public' AND p.proname NOT LIKE 'relay_rehearsal_%'
  AND has_function_privilege('public',p.oid,'EXECUTE')""").fetchone()[0]==0
 assert conn.execute("""SELECT
  has_table_privilege('obsidian_relay','orders','SELECT'),
  has_table_privilege('obsidian_relay_owner','orders','SELECT'),
  has_column_privilege('obsidian_relay_owner','orders','user_id','SELECT'),
  has_table_privilege('obsidian_relay','sell_orders','SELECT')""").fetchone()==(
   False,False,True,False,
  )

print("E0.3 Relay P2 owner scope, bounds, sensitive return and denial rehearsal: OK")
