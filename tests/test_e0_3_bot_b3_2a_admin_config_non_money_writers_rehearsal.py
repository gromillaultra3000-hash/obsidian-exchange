import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
dsn=os.getenv('TEST_POSTGRES_DSN')
if not dsn: print('E0.3 bot B3.2a admin/config writers: skipped'); raise SystemExit(0)
import psycopg
from psycopg.conninfo import conninfo_to_dict,make_conninfo
ROOT=Path(__file__).resolve().parents[1]
with psycopg.connect(dsn) as c:
 c.execute('CREATE TABLE blocked_users(user_id bigint PRIMARY KEY,reason text NOT NULL,blocked_at timestamptz NOT NULL DEFAULT now())')
 c.execute("CREATE TABLE orders(id bigserial PRIMARY KEY,order_id bigint UNIQUE,user_id bigint NOT NULL,created_at timestamptz NOT NULL DEFAULT now(),currency text NOT NULL DEFAULT 'BTC',rub_amount numeric NOT NULL DEFAULT 0,status text NOT NULL,crypto_address text,paid_btc_tx text,receipt_sent_at timestamptz,updated_at timestamptz,network text)")
 c.execute('CREATE TABLE sent_notifications(order_id bigint NOT NULL,event text NOT NULL,PRIMARY KEY(order_id,event))')
 c.execute('CREATE TABLE blocked_addresses(address text PRIMARY KEY,reason text NOT NULL,blocked_by bigint NOT NULL,created_at timestamptz NOT NULL DEFAULT now())')
 c.execute('CREATE TABLE operators(user_id bigint PRIMARY KEY,username text,added_by bigint NOT NULL,added_at timestamptz NOT NULL DEFAULT now(),is_active boolean NOT NULL DEFAULT true)')
 c.execute('CREATE TABLE workers(LIKE operators INCLUDING ALL)')
 c.execute('CREATE TABLE reserves(currency text PRIMARY KEY,amount numeric NOT NULL,updated_at timestamptz NOT NULL DEFAULT now())')
 c.execute("CREATE FUNCTION fail_reserve() RETURNS trigger LANGUAGE plpgsql AS $$BEGIN IF NEW.currency='FAIL' THEN RAISE EXCEPTION 'injected'; END IF; RETURN NEW; END$$;CREATE TRIGGER fail_reserve BEFORE INSERT OR UPDATE ON reserves FOR EACH ROW EXECUTE FUNCTION fail_reserve()")
 c.execute((ROOT/'deploy/postgres/proposals/035_e0_bot_b1_role_envelope.sql').read_text()); c.execute((ROOT/'deploy/postgres/proposals/043_e0_bot_b3_2a_admin_config_non_money_writers.sql').read_text())
parts=conninfo_to_dict(dsn);parts.update(user='obsidian_exchange_bot',password='synthetic-rehearsal-only');bot=make_conninfo(**parts)
with psycopg.connect(bot) as c:
 assert c.execute("SELECT bot_b3_admin_block_user(7,'fraud'),bot_b3_admin_block_user(7,'changed')").fetchone()==(True,False)
 c.execute("SELECT bot_b3_admin_block_address('addr1','reason1',9),bot_b3_admin_block_address('addr1','reason2',10)")
 c.execute("SELECT bot_b3_admin_set_staff('worker',11,'first',9),bot_b3_admin_set_staff('worker',11,'second',10)")
 assert c.execute("SELECT bot_b3_admin_deactivate_staff('worker',11),bot_b3_admin_deactivate_staff('worker',11)").fetchone()==(True,False)
 c.execute("SELECT bot_b3_admin_set_reserve('btc',12.5)")
 assert c.execute("SELECT bot_b3_admin_unblock_addresses(ARRAY['addr1','addr1']),bot_b3_admin_unblock_user(7)").fetchone()==(1,True)
def blocker(_):
 with psycopg.connect(bot) as c: return c.execute("SELECT bot_b3_admin_block_user(99,'one')").fetchone()[0]
with ThreadPoolExecutor(max_workers=8) as pool: wins=list(pool.map(blocker,range(8)))
assert wins.count(True)==1 and wins.count(False)==7
for sql in ("SELECT bot_b3_admin_block_user(0,'x')","SELECT bot_b3_admin_block_user(1,'')","SELECT bot_b3_admin_block_address('','x',1)","SELECT bot_b3_admin_unblock_addresses(ARRAY(SELECT 'x'||g FROM generate_series(1,101) g))","SELECT bot_b3_admin_set_staff('root',1,'x',2)","SELECT bot_b3_admin_set_staff('worker',1,'x',0)","SELECT bot_b3_admin_set_reserve('B T C',1)","SELECT bot_b3_admin_set_reserve('BTC',-1)","SELECT bot_b3_admin_set_reserve('FAIL',1)",'DELETE FROM blocked_users','SELECT * FROM reserves'):
 try:
  with psycopg.connect(bot) as c: c.execute(sql)
 except psycopg.Error: continue
 raise AssertionError('unexpectedly allowed: '+sql)
with psycopg.connect(dsn) as c:
 assert c.execute("SELECT reason,blocked_by FROM blocked_addresses WHERE address='addr1'").fetchone() is None
 assert c.execute("SELECT username,added_by,is_active FROM workers WHERE user_id=11").fetchone()==('second',9,False)
 assert c.execute("SELECT amount FROM reserves WHERE currency='BTC'").fetchone()==(12.5,)
 assert c.execute("SELECT count(*) FROM reserves WHERE currency='FAIL'").fetchone()==(0,)
 assert c.execute("SELECT has_table_privilege('obsidian_exchange_bot','blocked_users','DELETE'),has_table_privilege('obsidian_exchange_bot','reserves','UPDATE')").fetchone()==(False,False)
print('E0.3 bot B3.2a admin/config writers, concurrency, rollback and ambient denial: OK')
