import os
from decimal import Decimal
from pathlib import Path
dsn=os.getenv('TEST_POSTGRES_DSN')
if not dsn: print('E0.3 bot B2.2b operator order reads: skipped'); raise SystemExit(0)
import psycopg
from psycopg.conninfo import conninfo_to_dict,make_conninfo
ROOT=Path(__file__).resolve().parents[1]
with psycopg.connect(dsn) as c:
 c.execute('CREATE TABLE blocked_users(user_id bigint PRIMARY KEY,reason text NOT NULL,blocked_at timestamptz NOT NULL DEFAULT now())')
 c.execute("""CREATE TABLE orders(id bigserial PRIMARY KEY,order_id bigint UNIQUE,user_id bigint NOT NULL,username text,currency text NOT NULL DEFAULT 'BTC',rub_amount numeric NOT NULL DEFAULT 0,crypto_address text,status text NOT NULL,created_at timestamptz NOT NULL DEFAULT now(),paid_btc_tx text,updated_at timestamptz,web_user_id bigint,rub_volume_counted boolean,verification_requested text,montera_invoice_id text,receipt_deadline timestamptz,receipt_sent_at timestamptz,network text,agreed_rate numeric,agreed_crypto_amount numeric,agreed_at timestamptz)""")
 for sql in ('CREATE TABLE sent_notifications(order_id bigint NOT NULL,event text NOT NULL,PRIMARY KEY(order_id,event))','CREATE TABLE reserves(currency text PRIMARY KEY,amount numeric NOT NULL,updated_at timestamptz NOT NULL DEFAULT now())','CREATE TABLE rate_subscriptions(user_id bigint PRIMARY KEY,enabled boolean NOT NULL DEFAULT true)','CREATE TABLE user_vip_volume(user_id bigint PRIMARY KEY,total_rub numeric NOT NULL)','CREATE TABLE referral_bonuses(id bigserial PRIMARY KEY,referrer_id bigint NOT NULL,bonus_amount numeric NOT NULL,created_at timestamptz NOT NULL DEFAULT now())','CREATE TABLE support_tickets(id bigserial PRIMARY KEY,user_id bigint,subject text NOT NULL,status text NOT NULL,updated_at timestamptz NOT NULL DEFAULT now())','CREATE TABLE support_messages(id bigserial PRIMARY KEY,ticket_id bigint NOT NULL,sender text NOT NULL,message text NOT NULL,created_at timestamptz NOT NULL DEFAULT now())','CREATE TABLE bot_users(user_id bigint PRIMARY KEY,broadcast_enabled boolean NOT NULL DEFAULT true)'): c.execute(sql)
 c.execute("""INSERT INTO orders(order_id,user_id,username,currency,rub_amount,crypto_address,status,created_at,agreed_rate,agreed_crypto_amount) VALUES
 (101,7,'alice','BTC',1000,'a','sent',now()-interval '3 days',10,.1),(102,7,'alice','BTC',2000,'b','sent',now()-interval '2 days',20,.2),(103,7,'alice','LTC',3000,'c','pending',now()-interval '1 day',NULL,NULL),(104,8,'bob','BTC',4000,'d','paid',now(),40,.4)""")
 for proposal in ('035_e0_bot_b1_role_envelope.sql','036_e0_bot_b2_1_owner_reads.sql','037_e0_bot_b2_2a_operator_engagement_reads.sql','038_e0_bot_b2_2b_operator_order_reads.sql'): c.execute((ROOT/'deploy/postgres/proposals'/proposal).read_text())
parts=conninfo_to_dict(dsn);parts.update(user='obsidian_exchange_bot',password='synthetic-rehearsal-only');bot=make_conninfo(**parts)
with psycopg.connect(bot) as c:
 assert c.execute('SELECT * FROM bot_b2_agreed_quote(102)').fetchone()==(Decimal('20'),Decimal('.2'))
 assert c.execute("SELECT bot_b2_order_snapshot(102)->>'crypto_address'").fetchone()==('b',)
 assert c.execute('SELECT jsonb_array_length(bot_b2_customer_history(7,100))').fetchone()==(3,)
 assert c.execute('SELECT bot_b2_latest_customer_order_id(7)').fetchone()==(103,)
 assert c.execute("SELECT bot_b2_customer_aggregates(7)->>'favorite_currency'").fetchone()==('BTC',)
 assert c.execute('SELECT bot_b2_provider_success_count(7)').fetchone()==(2,)
 assert c.execute("SELECT bot_b2_find_customer('alice')->>'sent_cnt'").fetchone()==('2',)
 assert c.execute("SELECT bot_b2_operator_dashboard(100)->>'paid_count'").fetchone()==('1',)
 assert {r[0] for r in c.execute('SELECT * FROM bot_b2_active_customer_ids(365,1000)')}=={7,8}
 assert c.execute('SELECT jsonb_array_length(bot_b2_export_recent(2))').fetchone()==(2,)
for sql in ('SELECT * FROM bot_b2_agreed_quote(0)','SELECT * FROM bot_b2_agreed_quote(999)','SELECT bot_b2_customer_history(7,101)','SELECT bot_b2_latest_customer_order_id(0)',"SELECT bot_b2_find_customer('')",'SELECT bot_b2_operator_dashboard(101)','SELECT * FROM bot_b2_active_customer_ids(366,1)','SELECT bot_b2_export_recent(10001)','SELECT * FROM orders'):
 try:
  with psycopg.connect(bot) as c: c.execute(sql)
 except psycopg.Error: continue
 raise AssertionError('unexpectedly allowed: '+sql)
with psycopg.connect(dsn) as c:
 assert c.execute("SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='public' AND has_function_privilege('obsidian_exchange_bot',p.oid,'EXECUTE')").fetchone()[0]==25
 assert c.execute("SELECT has_table_privilege('obsidian_exchange_bot','orders','SELECT')").fetchone()==(False,)
print('E0.3 bot B2.2b operator order reads and ambient denial: OK')
