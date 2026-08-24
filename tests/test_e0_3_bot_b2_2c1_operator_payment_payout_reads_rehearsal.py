import os
from pathlib import Path
dsn=os.getenv('TEST_POSTGRES_DSN')
if not dsn: print('E0.3 bot B2.2c1 payment/payout reads: skipped'); raise SystemExit(0)
import psycopg
from psycopg.conninfo import conninfo_to_dict,make_conninfo
ROOT=Path(__file__).resolve().parents[1]
with psycopg.connect(dsn) as c:
 c.execute('CREATE TABLE blocked_users(user_id bigint PRIMARY KEY,reason text NOT NULL,blocked_at timestamptz NOT NULL DEFAULT now())')
 c.execute("""CREATE TABLE orders(id bigserial PRIMARY KEY,order_id bigint UNIQUE,user_id bigint NOT NULL,username text,currency text NOT NULL DEFAULT 'BTC',rub_amount numeric NOT NULL DEFAULT 0,crypto_address text,status text NOT NULL,created_at timestamptz NOT NULL DEFAULT now(),paid_btc_tx text,updated_at timestamptz,web_user_id bigint,rub_volume_counted boolean,verification_requested text,montera_invoice_id text,receipt_deadline timestamptz,receipt_sent_at timestamptz,network text,agreed_rate numeric,agreed_crypto_amount numeric,agreed_at timestamptz)""")
 for sql in ('CREATE TABLE sent_notifications(order_id bigint NOT NULL,event text NOT NULL,PRIMARY KEY(order_id,event))','CREATE TABLE reserves(currency text PRIMARY KEY,amount numeric NOT NULL,updated_at timestamptz NOT NULL DEFAULT now())','CREATE TABLE rate_subscriptions(user_id bigint PRIMARY KEY,enabled boolean NOT NULL DEFAULT true)','CREATE TABLE user_vip_volume(user_id bigint PRIMARY KEY,total_rub numeric NOT NULL)','CREATE TABLE referral_bonuses(id bigserial PRIMARY KEY,referrer_id bigint NOT NULL,bonus_amount numeric NOT NULL,created_at timestamptz NOT NULL DEFAULT now())','CREATE TABLE support_tickets(id bigserial PRIMARY KEY,user_id bigint,subject text NOT NULL,status text NOT NULL,updated_at timestamptz NOT NULL DEFAULT now())','CREATE TABLE support_messages(id bigserial PRIMARY KEY,ticket_id bigint NOT NULL,sender text NOT NULL,message text NOT NULL,created_at timestamptz NOT NULL DEFAULT now())','CREATE TABLE bot_users(user_id bigint PRIMARY KEY,broadcast_enabled boolean NOT NULL DEFAULT true)'): c.execute(sql)
 c.execute((ROOT/'deploy/postgres/001_payout_core.sql').read_text()); c.execute((ROOT/'deploy/postgres/007_payment_sessions.sql').read_text())
 c.execute("INSERT INTO orders(order_id,user_id,status) VALUES(101,7,'paid'),(102,8,'pending')")
 c.execute("INSERT INTO payment_sessions(session_token,order_id,amount,provider,status,provider_invoice_id,created_at) VALUES('old',101,10,'montera','failed','i1',now()-interval '1 hour'),('new',101,10,'montera-v2','invoice_created','i2',now())")
 c.execute("INSERT INTO payout_intents(order_id,idempotency_key,state,source,rub_amount,crypto_amount,currency,destination) VALUES(101,'o1','review','test',10,.1,'BTC','dest')")
 c.execute("INSERT INTO referral_payout_intents(user_id,idempotency_key,state,crypto_amount,destination) VALUES(7,'r1','processing',.01,'dest')")
 for p in ('035_e0_bot_b1_role_envelope.sql','036_e0_bot_b2_1_owner_reads.sql','037_e0_bot_b2_2a_operator_engagement_reads.sql','038_e0_bot_b2_2b_operator_order_reads.sql','039_e0_bot_b2_2c1_operator_payment_payout_reads.sql'): c.execute((ROOT/'deploy/postgres/proposals'/p).read_text())
parts=conninfo_to_dict(dsn);parts.update(user='obsidian_exchange_bot',password='synthetic-rehearsal-only');bot=make_conninfo(**parts)
with psycopg.connect(bot) as c:
 assert c.execute("SELECT bot_b2_payment_latest(101)->>'session_token'").fetchone()==('new',)
 assert c.execute('SELECT jsonb_array_length(bot_b2_payment_recent(101,2))').fetchone()==(2,)
 assert c.execute("SELECT bot_b2_payment_provider_invoice(101,'montera',true)->>'provider_invoice_id'").fetchone()==('i2',)
 assert c.execute("SELECT bot_b2_payout_order(101)->>'state',bot_b2_payout_order_exists(101)").fetchone()==('review',True)
 assert c.execute("SELECT bot_b2_payout_referral(1)->>'state'").fetchone()==('processing',)
 assert c.execute('SELECT jsonb_array_length(bot_b2_payout_review(100)),jsonb_array_length(bot_b2_referral_payout_review(100))').fetchone()==(1,1)
for sql in ('SELECT bot_b2_payment_latest(0)','SELECT bot_b2_payment_recent(101,101)',"SELECT bot_b2_payment_provider_invoice(101,'',false)",'SELECT bot_b2_payout_order(0)','SELECT bot_b2_payout_referral(0)','SELECT bot_b2_payout_review(101)','SELECT bot_b2_referral_payout_review(0)','SELECT * FROM payment_sessions','SELECT * FROM payout_intents'):
 try:
  with psycopg.connect(bot) as c: c.execute(sql)
 except psycopg.Error: continue
 raise AssertionError('unexpectedly allowed: '+sql)
with psycopg.connect(dsn) as c:
 assert c.execute("SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='public' AND has_function_privilege('obsidian_exchange_bot',p.oid,'EXECUTE')").fetchone()[0]==33
 assert c.execute("SELECT has_table_privilege('obsidian_exchange_bot','payment_sessions','SELECT'),has_table_privilege('obsidian_exchange_bot','payout_intents','SELECT')").fetchone()==(False,False)
print('E0.3 bot B2.2c1 payment/payout reads and ambient denial: OK')
