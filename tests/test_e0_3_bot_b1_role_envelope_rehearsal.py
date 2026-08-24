import os
import pytest
from pathlib import Path

dsn=os.getenv('TEST_POSTGRES_DSN')
if not dsn:
 pytest.skip('TEST_POSTGRES_DSN unset', allow_module_level=True)
import psycopg
from psycopg.conninfo import conninfo_to_dict,make_conninfo

ROOT=Path(__file__).resolve().parents[1]
proposal=(ROOT/'deploy/postgres/proposals/035_e0_bot_b1_role_envelope.sql').read_text()
with psycopg.connect(dsn) as c:
 c.execute('CREATE TABLE blocked_users(user_id bigint PRIMARY KEY,reason text NOT NULL,blocked_at timestamptz NOT NULL DEFAULT now())')
 c.execute('CREATE TABLE orders(order_id bigserial PRIMARY KEY,user_id bigint NOT NULL,created_at timestamptz NOT NULL DEFAULT now(),currency text NOT NULL,rub_amount numeric NOT NULL,status text NOT NULL,crypto_address text,paid_btc_tx text,receipt_sent_at timestamptz,updated_at timestamptz,network text)')
 c.execute('CREATE TABLE sent_notifications(order_id bigint NOT NULL,event text NOT NULL,PRIMARY KEY(order_id,event))')
 c.execute('CREATE TABLE reserves(currency text PRIMARY KEY,amount numeric NOT NULL,updated_at timestamptz NOT NULL DEFAULT now())')
 c.execute("INSERT INTO blocked_users(user_id,reason) VALUES(9,'fraud')")
 c.execute("INSERT INTO orders(user_id,currency,rub_amount,status,network) VALUES(7,'BTC',100,'paid','bitcoin'),(7,'USDT',200,'sent','tron'),(8,'BTC',300,'paid','bitcoin')")
 c.execute("INSERT INTO sent_notifications VALUES(3,'payout_triggered')")
 c.execute("INSERT INTO reserves(currency,amount) VALUES('BTC',1),('USDT',2)")
 c.execute(proposal)

parts=conninfo_to_dict(dsn);parts.update(user='obsidian_exchange_bot',password='synthetic-rehearsal-only',connect_timeout='2');bot_dsn=make_conninfo(**parts)
def denied(sql,args=()):
 try:
  with psycopg.connect(bot_dsn) as c:c.execute(sql,args)
 except psycopg.Error:return
 raise AssertionError('unexpectedly allowed: '+sql)

with psycopg.connect(bot_dsn) as c:
 assert c.execute('SHOW statement_timeout').fetchone()[0]=='5s'
 assert c.execute('SELECT user_id FROM bot_b1_blocked_users(100)').fetchall()==[(9,)]
 assert c.execute('SELECT order_id FROM bot_b1_customer_history(7,100)').fetchall()==[(2,),(1,)]
 assert c.execute('SELECT order_id FROM bot_b1_payout_candidates(24,100)').fetchall()==[(1,)]
 assert c.execute('SELECT currency FROM bot_b1_reserves_detailed()').fetchall()==[('BTC',),('USDT',)]
for sql in ('SELECT * FROM orders','UPDATE orders SET status=\'sent\'','CREATE TABLE forbidden(id int)','CREATE TEMP TABLE forbidden(id int)',"SELECT nextval('orders_order_id_seq')"):
 denied(sql)
for sql in ('SELECT * FROM bot_b1_blocked_users(0)','SELECT * FROM bot_b1_blocked_users(101)','SELECT * FROM bot_b1_customer_history(0,10)','SELECT * FROM bot_b1_customer_history(7,101)','SELECT * FROM bot_b1_payout_candidates(169,1)','SELECT * FROM bot_b1_payout_candidates(24,101)'):
 denied(sql)

held=[]
try:
 for _ in range(10):held.append(psycopg.connect(bot_dsn))
 try:psycopg.connect(bot_dsn)
 except psycopg.Error as e:assert 'too many connections' in str(e).lower()
 else:raise AssertionError('eleventh bot connection unexpectedly succeeded')
finally:
 for c in held:c.close()

with psycopg.connect(dsn) as c:
 assert c.execute("SELECT rolcanlogin,rolconnlimit,rolsuper,rolinherit,rolbypassrls FROM pg_roles WHERE rolname='obsidian_exchange_bot'").fetchone()==(True,10,False,False,False)
 assert c.execute("SELECT rolcanlogin FROM pg_roles WHERE rolname='obsidian_exchange_bot_owner'").fetchone()==(False,)
 assert c.execute("SELECT count(*) FROM pg_auth_members WHERE roleid IN(SELECT oid FROM pg_roles WHERE rolname LIKE 'obsidian_exchange_bot%') OR member IN(SELECT oid FROM pg_roles WHERE rolname LIKE 'obsidian_exchange_bot%')").fetchone()[0]==0
 assert c.execute("SELECT has_table_privilege('obsidian_exchange_bot','orders','SELECT'),has_schema_privilege('obsidian_exchange_bot','public','CREATE'),has_database_privilege('obsidian_exchange_bot',current_database(),'TEMPORARY')").fetchone()==(False,False,False)
 assert c.execute("SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='public' AND has_function_privilege('obsidian_exchange_bot',p.oid,'EXECUTE')").fetchone()[0]==4
print('E0.3 bot B1 role envelope, bounded reads, denial and connection limit: OK')
