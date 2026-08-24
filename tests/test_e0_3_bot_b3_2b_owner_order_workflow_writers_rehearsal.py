import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
dsn=os.getenv('TEST_POSTGRES_DSN')
if not dsn: print('E0.3 bot B3.2b owner order-workflow writers: skipped'); raise SystemExit(0)
import psycopg
from psycopg.conninfo import conninfo_to_dict,make_conninfo
ROOT=Path(__file__).resolve().parents[1]
with psycopg.connect(dsn) as c:
 c.execute('CREATE TABLE blocked_users(user_id bigint PRIMARY KEY,reason text NOT NULL,blocked_at timestamptz NOT NULL DEFAULT now())')
 c.execute("CREATE TABLE orders(id bigserial PRIMARY KEY,order_id bigint UNIQUE,user_id bigint NOT NULL,created_at timestamptz NOT NULL DEFAULT now(),currency text NOT NULL DEFAULT 'BTC',rub_amount numeric(20,2) NOT NULL CHECK(rub_amount>0),status text NOT NULL,crypto_address text,paid_btc_tx text,receipt_sent_at timestamptz,updated_at timestamptz,network text)")
 c.execute('CREATE TABLE sent_notifications(order_id bigint NOT NULL,event text NOT NULL,PRIMARY KEY(order_id,event))')
 c.execute('CREATE TABLE reserves(currency text PRIMARY KEY,amount numeric NOT NULL,updated_at timestamptz NOT NULL DEFAULT now())')
 c.execute("INSERT INTO orders(order_id,user_id,rub_amount,status) VALUES(101,7,1000,'pending'),(102,8,1000,'pending'),(103,7,1000,'paid'),(104,7,1000,'pending'),(105,7,1000,'pending')")
 c.execute("CREATE FUNCTION fail_owner_update() RETURNS trigger LANGUAGE plpgsql AS $$BEGIN IF NEW.order_id=105 THEN RAISE EXCEPTION 'injected'; END IF; RETURN NEW; END$$;CREATE TRIGGER fail_owner_update BEFORE UPDATE ON orders FOR EACH ROW EXECUTE FUNCTION fail_owner_update()")
 c.execute((ROOT/'deploy/postgres/proposals/035_e0_bot_b1_role_envelope.sql').read_text()); c.execute((ROOT/'deploy/postgres/proposals/044_e0_bot_b3_2b_owner_order_workflow_writers.sql').read_text())
parts=conninfo_to_dict(dsn);parts.update(user='obsidian_exchange_bot',password='synthetic-rehearsal-only');bot=make_conninfo(**parts)
with psycopg.connect(bot) as c:
 assert c.execute('SELECT bot_b3_owner_cancel_pending(102,7),bot_b3_owner_retry_amount(102,7,2000)').fetchone()==(False,False)
 assert c.execute('SELECT bot_b3_owner_cancel_pending(103,7),bot_b3_owner_retry_amount(103,7,2000)').fetchone()==(False,False)
 assert c.execute('SELECT bot_b3_owner_retry_amount(104,7,2500.50)').fetchone()==(True,)
 assert c.execute('SELECT bot_b3_owner_retry_amount(104,7,2500.50)').fetchone()==(True,)
def cancel(_):
 with psycopg.connect(bot) as c: return c.execute('SELECT bot_b3_owner_cancel_pending(101,7)').fetchone()[0]
with ThreadPoolExecutor(max_workers=12) as pool: wins=list(pool.map(cancel,range(12)))
assert wins.count(True)==1 and wins.count(False)==11
for sql in ('SELECT bot_b3_owner_cancel_pending(NULL,7)','SELECT bot_b3_owner_cancel_pending(0,7)','SELECT bot_b3_owner_cancel_pending(101,0)','SELECT bot_b3_owner_retry_amount(104,NULL,1)','SELECT bot_b3_owner_retry_amount(104,7,0)','SELECT bot_b3_owner_retry_amount(104,7,-1)',"SELECT bot_b3_owner_retry_amount(104,7,'NaN'::numeric)","SELECT bot_b3_owner_retry_amount(104,7,'Infinity'::numeric)",'SELECT bot_b3_owner_retry_amount(104,7,1000000000000000000)','SELECT bot_b3_owner_retry_amount(105,7,3000)','UPDATE orders SET status=\'cancelled\'','SELECT * FROM orders'):
 try:
  with psycopg.connect(bot) as c: c.execute(sql)
 except psycopg.Error: continue
 raise AssertionError('unexpectedly allowed: '+sql)
with psycopg.connect(dsn) as c:
 assert c.execute('SELECT status FROM orders WHERE order_id=101').fetchone()==('cancelled',)
 assert c.execute('SELECT user_id,rub_amount,status FROM orders WHERE order_id=102').fetchone()==(8,1000,'pending')
 assert c.execute('SELECT rub_amount,status FROM orders WHERE order_id=103').fetchone()==(1000,'paid')
 assert c.execute('SELECT rub_amount,status FROM orders WHERE order_id=104').fetchone()==(2500.50,'pending')
 assert c.execute('SELECT rub_amount,status FROM orders WHERE order_id=105').fetchone()==(1000,'pending')
 assert c.execute("SELECT has_table_privilege('obsidian_exchange_bot','orders','UPDATE'),has_table_privilege('obsidian_exchange_bot','orders','SELECT')").fetchone()==(False,False)
 assert c.execute("SELECT has_function_privilege('public',p.oid,'EXECUTE') FROM pg_proc p WHERE p.proname='bot_b3_owner_cancel_pending'").fetchone()==(False,)
print('E0.3 bot B3.2b owner workflow ownership, CAS, concurrency, rollback and ambient denial: OK')
