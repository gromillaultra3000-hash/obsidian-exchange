import os
import pytest
from pathlib import Path
dsn=os.getenv('TEST_POSTGRES_DSN')
if not dsn:
    pytest.skip('TEST_POSTGRES_DSN unset', allow_module_level=True)
import psycopg
from psycopg.conninfo import conninfo_to_dict,make_conninfo
ROOT=Path(__file__).resolve().parents[1]
with psycopg.connect(dsn) as c:
 for sql in (
  'CREATE TABLE blocked_users(user_id bigint PRIMARY KEY,reason text NOT NULL,blocked_at timestamptz NOT NULL DEFAULT now())',
  "CREATE TABLE orders(id bigserial PRIMARY KEY,order_id bigint UNIQUE,user_id bigint NOT NULL,created_at timestamptz NOT NULL DEFAULT now(),currency text NOT NULL DEFAULT 'BTC',rub_amount numeric NOT NULL DEFAULT 0,status text NOT NULL,crypto_address text,paid_btc_tx text,receipt_sent_at timestamptz,updated_at timestamptz,network text)",
  'CREATE TABLE sent_notifications(order_id bigint NOT NULL,event text NOT NULL,PRIMARY KEY(order_id,event))','CREATE TABLE reserves(currency text PRIMARY KEY,amount numeric NOT NULL,updated_at timestamptz NOT NULL DEFAULT now())',
  'CREATE TABLE rate_subscriptions(user_id bigint PRIMARY KEY,enabled boolean NOT NULL DEFAULT true)','CREATE TABLE user_vip_volume(user_id bigint PRIMARY KEY,total_rub numeric NOT NULL)',
  'CREATE TABLE referral_bonuses(id bigserial PRIMARY KEY,referrer_id bigint NOT NULL,bonus_amount numeric NOT NULL,created_at timestamptz NOT NULL DEFAULT now())',
  'CREATE TABLE support_tickets(id bigserial PRIMARY KEY,user_id bigint,subject text NOT NULL,status text NOT NULL,updated_at timestamptz NOT NULL DEFAULT now())',
  'CREATE TABLE support_messages(id bigserial PRIMARY KEY,ticket_id bigint NOT NULL,sender text NOT NULL,message text NOT NULL,created_at timestamptz NOT NULL DEFAULT now())',
  'CREATE TABLE bot_users(user_id bigint PRIMARY KEY,broadcast_enabled boolean NOT NULL DEFAULT true)'):
  c.execute(sql)
 c.execute("INSERT INTO bot_users VALUES(1,true),(2,false),(501,true);INSERT INTO orders(order_id,user_id,status) VALUES(11,7,'pending'),(12,7,'sent'),(13,8,'sent');INSERT INTO referral_bonuses(referrer_id,bonus_amount,created_at) VALUES(7,2,'2026-08-01'),(8,3,'2026-08-02'),(9,99,'2025-01-01')")
 c.execute((ROOT/'deploy/postgres/proposals/035_e0_bot_b1_role_envelope.sql').read_text())
 c.execute((ROOT/'deploy/postgres/proposals/036_e0_bot_b2_1_owner_reads.sql').read_text())
 c.execute((ROOT/'deploy/postgres/proposals/037_e0_bot_b2_2a_operator_engagement_reads.sql').read_text())
parts=conninfo_to_dict(dsn);parts.update(user='obsidian_exchange_bot',password='synthetic-rehearsal-only');bot=make_conninfo(**parts)
with psycopg.connect(bot) as c:
 assert c.execute('SELECT bot_b2_broadcast_count()').fetchone()==(2,)
 assert c.execute('SELECT * FROM bot_b2_broadcast_user_ids(0,1)').fetchall()==[(1,)]
 assert c.execute('SELECT * FROM bot_b2_broadcast_user_ids(1,500)').fetchall()==[(501,)]
 assert c.execute('SELECT * FROM bot_b2_order_customer_ids(0,500)').fetchall()==[(7,),(8,)]
 assert c.execute("SELECT bot_b2_referral_bonus_period('2026-08-01','2026-08-02')").fetchone()==(5,)
for sql in ("SELECT * FROM bot_b2_broadcast_user_ids(0,501)","SELECT * FROM bot_b2_order_customer_ids(-1,1)","SELECT bot_b2_referral_bonus_period('2026-08-02','2026-08-01')","SELECT bot_b2_referral_bonus_period('2025-01-01','2026-08-01')",'SELECT * FROM bot_users','SELECT user_id FROM orders'):
 try:
  with psycopg.connect(bot) as c:c.execute(sql)
 except psycopg.Error:continue
 raise AssertionError('unexpectedly allowed: '+sql)
with psycopg.connect(dsn) as c:
 assert c.execute("SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='public' AND has_function_privilege('obsidian_exchange_bot',p.oid,'EXECUTE')").fetchone()[0]==15
 assert c.execute("SELECT has_table_privilege('obsidian_exchange_bot','bot_users','SELECT'),has_table_privilege('obsidian_exchange_bot','orders','SELECT')").fetchone()==(False,False)
print('E0.3 bot B2.2a operator engagement reads and ambient denial: OK')
