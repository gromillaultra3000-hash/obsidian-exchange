import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
dsn=os.getenv('TEST_POSTGRES_DSN')
if not dsn:print('E0.3 bot B5.4 order creation: skipped');raise SystemExit(0)
import psycopg
from psycopg.conninfo import conninfo_to_dict,make_conninfo
ROOT=Path(__file__).resolve().parents[1]
with psycopg.connect(dsn) as c:
 c.execute('CREATE TABLE blocked_users(user_id bigint PRIMARY KEY,reason text NOT NULL,blocked_at timestamptz NOT NULL DEFAULT now());CREATE TABLE reserves(currency text PRIMARY KEY,amount numeric,updated_at timestamptz NOT NULL DEFAULT now())')
 c.execute((ROOT/'deploy/postgres/019_orders.sql').read_text());c.execute((ROOT/'deploy/postgres/004_rate_locks.sql').read_text());c.execute((ROOT/'deploy/postgres/013_promos.sql').read_text())
 c.execute("INSERT INTO rate_locks(user_id,currency,locked_rate,locked_until) VALUES(7,'BTC',10,now()+interval '1 hour');INSERT INTO promo_codes(code,discount_percent,max_uses,valid_until) VALUES('P',5,1,now()+interval '1 day')")
 c.execute("CREATE FUNCTION fail_order() RETURNS trigger LANGUAGE plpgsql AS $$BEGIN IF NEW.user_id=99 THEN RAISE EXCEPTION 'fault';END IF;RETURN NEW;END$$;CREATE TRIGGER fail_order BEFORE INSERT ON orders FOR EACH ROW EXECUTE FUNCTION fail_order()")
 c.execute((ROOT/'deploy/postgres/proposals/035_e0_bot_b1_role_envelope.sql').read_text());c.execute((ROOT/'deploy/postgres/proposals/049_e0_bot_b5_4_order_creation_writer.sql').read_text())
parts=conninfo_to_dict(dsn);parts.update(user='obsidian_exchange_bot',password='synthetic-rehearsal-only');bot=make_conninfo(**parts)
def create(_):
 with psycopg.connect(bot) as c:return c.execute("SELECT * FROM bot_b5_create_order(7,'u','btc',1000,'addr','btc',10,100,20,50,1,1,11,90,22,45)").fetchone()
with ThreadPoolExecutor(max_workers=8) as p:rows=list(p.map(create,range(8)))
assert len({r[0] for r in rows})==8 and sum(r[1] for r in rows)==1 and sum(r[2] for r in rows)==1
for r in rows:
 expected=(10,100) if r[1] and r[2] else (11,90) if r[1] else (20,50) if r[2] else (22,45)
 assert r[3:]==expected
def call(sql):
 with psycopg.connect(bot) as c:return c.execute(sql).fetchone()
for sql in ("SELECT * FROM bot_b5_create_order(0,NULL,'BTC',1,'a',NULL,1,1,1,1,NULL,NULL,NULL,NULL,NULL,NULL)","SELECT * FROM bot_b5_create_order(1,NULL,'BTC','NaN','a',NULL,1,1,1,1,NULL,NULL,NULL,NULL,NULL,NULL)","SELECT * FROM bot_b5_create_order(1,NULL,'ETH',1,'a',NULL,1,1,1,1,NULL,NULL,NULL,NULL,NULL,NULL)","SELECT * FROM bot_b5_create_order(1,NULL,'BTC',1,'a',NULL,1,1,1,1,NULL,1,NULL,NULL,NULL,NULL)","SELECT * FROM bot_b5_create_order(99,NULL,'BTC',1,'a',NULL,1,1,1,1,NULL,NULL,NULL,NULL,NULL,NULL)",'SELECT * FROM orders','INSERT INTO orders(user_id,currency,rub_amount,crypto_address) VALUES(1,\'BTC\',1,\'a\')',"SELECT nextval('orders_order_id_seq')"):
 try:call(sql)
 except psycopg.Error:continue
 raise AssertionError('unexpectedly allowed: '+sql)
with psycopg.connect(dsn) as c:
 assert c.execute('SELECT count(*) FROM orders').fetchone()==(8,)
 assert c.execute('SELECT count(*) FROM rate_locks WHERE used=true AND order_id IS NOT NULL').fetchone()==(1,)
 assert c.execute('SELECT uses_count FROM promo_codes WHERE id=1').fetchone()==(1,)
 assert c.execute('SELECT count(*) FROM promo_uses').fetchone()==(1,)
 assert c.execute("SELECT has_table_privilege('obsidian_exchange_bot','orders','INSERT'),has_sequence_privilege('obsidian_exchange_bot','orders_order_id_seq','USAGE'),has_function_privilege('public',to_regprocedure('bot_b5_create_order(bigint,text,text,numeric,text,text,numeric,numeric,numeric,numeric,bigint,bigint,numeric,numeric,numeric,numeric)'),'EXECUTE')").fetchone()==(False,False,False)
print('E0.3 bot B5.4 order lock/promo races, quote fallback, rollback and ambient denial: OK')
