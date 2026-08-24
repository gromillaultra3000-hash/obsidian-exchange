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
  'CREATE TABLE orders(id bigserial PRIMARY KEY,order_id bigint UNIQUE,user_id bigint NOT NULL,created_at timestamptz NOT NULL DEFAULT now(),currency text NOT NULL DEFAULT \'BTC\',rub_amount numeric NOT NULL DEFAULT 0,status text NOT NULL,crypto_address text,paid_btc_tx text,receipt_sent_at timestamptz,updated_at timestamptz,network text)',
  'CREATE TABLE sent_notifications(order_id bigint NOT NULL,event text NOT NULL,PRIMARY KEY(order_id,event))','CREATE TABLE reserves(currency text PRIMARY KEY,amount numeric NOT NULL,updated_at timestamptz NOT NULL DEFAULT now())',
  'CREATE TABLE rate_subscriptions(user_id bigint PRIMARY KEY,enabled boolean NOT NULL DEFAULT true)','CREATE TABLE user_vip_volume(user_id bigint PRIMARY KEY,total_rub numeric NOT NULL)',
  'CREATE TABLE referral_bonuses(id bigserial PRIMARY KEY,referrer_id bigint NOT NULL,bonus_amount numeric NOT NULL,created_at timestamptz NOT NULL DEFAULT now())',
  'CREATE TABLE support_tickets(id bigserial PRIMARY KEY,user_id bigint,subject text NOT NULL,status text NOT NULL,updated_at timestamptz NOT NULL DEFAULT now())',
  'CREATE TABLE support_messages(id bigserial PRIMARY KEY,ticket_id bigint NOT NULL,sender text NOT NULL,message text NOT NULL,created_at timestamptz NOT NULL DEFAULT now())'):
  c.execute(sql)
 c.execute("INSERT INTO rate_subscriptions VALUES(7,true),(8,false);INSERT INTO user_vip_volume VALUES(7,1000),(8,9000);INSERT INTO referral_bonuses(referrer_id,bonus_amount) VALUES(7,1),(8,9);INSERT INTO orders(order_id,user_id,status,created_at) VALUES(101,7,'pending',now()),(102,8,'pending',now());INSERT INTO support_tickets(user_id,subject,status) VALUES(7,'owner-seven','open'),(8,'owner-eight','open');INSERT INTO support_messages(ticket_id,sender,message) VALUES(1,'user','secret-seven'),(2,'user','secret-eight')")
 c.execute((ROOT/'deploy/postgres/proposals/035_e0_bot_b1_role_envelope.sql').read_text())
 c.execute((ROOT/'deploy/postgres/proposals/036_e0_bot_b2_1_owner_reads.sql').read_text())
parts=conninfo_to_dict(dsn);parts.update(user='obsidian_exchange_bot',password='synthetic-rehearsal-only');bot=make_conninfo(**parts)
with psycopg.connect(bot) as c:
 assert c.execute('SELECT bot_b2_rate_enabled(7),bot_b2_vip_total(7),bot_b2_referral_bonus_owner(7)').fetchone()==(True,1000,1)
 assert c.execute("SELECT daily_count,cooldown_active FROM bot_b2_creation_limit_state(7,now()-interval '1 day',now()-interval '1 hour')").fetchone()==(1,True)
 assert c.execute('SELECT subject FROM bot_b2_support_list(7,100)').fetchall()==[('owner-seven',)]
 assert c.execute('SELECT bot_b2_support_open_count(7)').fetchone()==(1,)
 assert c.execute('SELECT subject,messages->0->>\'message\' FROM bot_b2_support_thread(1,7)').fetchone()==('owner-seven','secret-seven')
 assert c.execute('SELECT * FROM bot_b2_support_thread(2,7)').fetchall()==[]
 assert c.execute('SELECT * FROM bot_b2_support_thread(1,8)').fetchall()==[]
for sql in ('SELECT bot_b2_rate_enabled(0)','SELECT * FROM bot_b2_support_list(7,101)','SELECT * FROM bot_b2_support_thread(1,0)','SELECT * FROM support_tickets','SELECT * FROM referral_bonuses'):
 try:
  with psycopg.connect(bot) as c:c.execute(sql)
 except psycopg.Error:continue
 raise AssertionError('unexpectedly allowed: '+sql)
with psycopg.connect(dsn) as c:
 assert c.execute("SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='public' AND has_function_privilege('obsidian_exchange_bot',p.oid,'EXECUTE')").fetchone()[0]==11
 assert c.execute("SELECT has_table_privilege('obsidian_exchange_bot','support_tickets','SELECT')").fetchone()==(False,)
print('E0.3 bot B2.1 owner reads and cross-owner denial: OK')
