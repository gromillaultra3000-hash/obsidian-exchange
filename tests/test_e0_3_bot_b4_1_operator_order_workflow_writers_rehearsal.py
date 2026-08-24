import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
dsn=os.getenv('TEST_POSTGRES_DSN')
if not dsn: print('E0.3 bot B4.1 operator order-workflow writers: skipped'); raise SystemExit(0)
import psycopg
from psycopg.conninfo import conninfo_to_dict,make_conninfo
ROOT=Path(__file__).resolve().parents[1]
with psycopg.connect(dsn) as c:
 c.execute('CREATE TABLE blocked_users(user_id bigint PRIMARY KEY,reason text NOT NULL,blocked_at timestamptz NOT NULL DEFAULT now())')
 c.execute("CREATE TABLE orders(id bigserial PRIMARY KEY,order_id bigint UNIQUE,user_id bigint NOT NULL,created_at timestamptz NOT NULL DEFAULT now(),currency text NOT NULL DEFAULT 'BTC',rub_amount numeric NOT NULL DEFAULT 1,status text NOT NULL,crypto_address text,paid_btc_tx text,receipt_sent_at timestamptz,updated_at timestamptz,network text,verification_requested text,montera_invoice_id text,receipt_deadline timestamptz)")
 c.execute('CREATE TABLE sent_notifications(order_id bigint NOT NULL,event text NOT NULL,PRIMARY KEY(order_id,event))')
 c.execute('CREATE TABLE reserves(currency text PRIMARY KEY,amount numeric NOT NULL,updated_at timestamptz NOT NULL DEFAULT now())')
 c.execute("INSERT INTO orders(order_id,user_id,status,verification_requested) VALUES(101,7,'pending','video'),(102,7,'pending',NULL),(103,7,'expired',NULL),(104,7,'paid',NULL),(105,7,'pending',NULL),(106,7,'pending',NULL),(107,7,'pending',NULL)")
 c.execute("CREATE FUNCTION fail_marker() RETURNS trigger LANGUAGE plpgsql AS $$BEGIN IF NEW.order_id=105 THEN RAISE EXCEPTION 'marker_fault'; END IF; RETURN NEW; END$$;CREATE TRIGGER fail_marker BEFORE INSERT ON sent_notifications FOR EACH ROW EXECUTE FUNCTION fail_marker()")
 c.execute("CREATE FUNCTION fail_invoice() RETURNS trigger LANGUAGE plpgsql AS $$BEGIN IF NEW.order_id=107 AND NEW.montera_invoice_id IS NOT NULL THEN RAISE EXCEPTION 'invoice_fault'; END IF; RETURN NEW; END$$;CREATE TRIGGER fail_invoice BEFORE UPDATE ON orders FOR EACH ROW EXECUTE FUNCTION fail_invoice()")
 c.execute((ROOT/'deploy/postgres/proposals/035_e0_bot_b1_role_envelope.sql').read_text()); c.execute((ROOT/'deploy/postgres/proposals/045_e0_bot_b4_1_operator_order_workflow_writers.sql').read_text())
parts=conninfo_to_dict(dsn);parts.update(user='obsidian_exchange_bot',password='synthetic-rehearsal-only');bot=make_conninfo(**parts)
def call(sql):
 with psycopg.connect(bot) as c: return c.execute(sql).fetchone()[0]
with ThreadPoolExecutor(max_workers=8) as pool: clear=list(pool.map(lambda _:call("SELECT bot_b4_clear_verification(101,'video')"),range(8)))
assert clear.count(True)==1 and clear.count(False)==7
with ThreadPoolExecutor(max_workers=8) as pool: reject=list(pool.map(lambda _:call('SELECT bot_b4_reject_review(102)'),range(8)))
assert reject.count(True)==1 and reject.count(False)==7
with ThreadPoolExecutor(max_workers=8) as pool: reopen=list(pool.map(lambda _:call('SELECT bot_b4_reopen_review(103)'),range(8)))
assert reopen.count(True)==1 and reopen.count(False)==7
def invoice(i): return call("SELECT bot_b4_set_montera_invoice(106,'deal-%s','2026-09-01T00:00:00Z')"%i)
with ThreadPoolExecutor(max_workers=8) as pool: invoices=list(pool.map(invoice,range(8)))
assert invoices.count(True)==1 and invoices.count(False)==7
chosen='deal-%s'%invoices.index(True)
with psycopg.connect(bot) as c:
 assert c.execute("SELECT bot_b4_set_montera_invoice(106,%s,'2026-09-02T00:00:00Z')",(chosen,)).fetchone()==(True,)
 assert c.execute('SELECT bot_b4_reject_review(104),bot_b4_reopen_review(104)').fetchone()==(False,False)
for sql in ("SELECT bot_b4_clear_verification(NULL,'video')","SELECT bot_b4_clear_verification(1,'sms')",'SELECT bot_b4_reject_review(0)','SELECT bot_b4_reopen_review(NULL)',"SELECT bot_b4_set_montera_invoice(106,'',now())","SELECT bot_b4_set_montera_invoice(106,repeat('x',256),now())","SELECT bot_b4_set_montera_invoice(106,'x',NULL)",'SELECT bot_b4_reject_review(105)',"SELECT bot_b4_set_montera_invoice(107,'fault',now())",'UPDATE orders SET status=\'sent\'','INSERT INTO sent_notifications VALUES(9,\'x\')','SELECT * FROM orders'):
 try:
  with psycopg.connect(bot) as c: c.execute(sql)
 except psycopg.Error: continue
 raise AssertionError('unexpectedly allowed: '+sql)
with psycopg.connect(dsn) as c:
 assert c.execute('SELECT verification_requested FROM orders WHERE order_id=101').fetchone()==(None,)
 assert c.execute('SELECT status FROM orders WHERE order_id=102').fetchone()==('cancelled',)
 assert c.execute("SELECT count(*) FROM sent_notifications WHERE order_id=102 AND event='receipt_rejected'").fetchone()==(1,)
 assert c.execute('SELECT status FROM orders WHERE order_id=103').fetchone()==('pending',)
 assert c.execute('SELECT status FROM orders WHERE order_id=105').fetchone()==('pending',)
 assert c.execute('SELECT montera_invoice_id,receipt_deadline FROM orders WHERE order_id=107').fetchone()==(None,None)
 assert c.execute("SELECT has_table_privilege('obsidian_exchange_bot','orders','UPDATE'),has_table_privilege('obsidian_exchange_bot','sent_notifications','INSERT')").fetchone()==(False,False)
 assert c.execute("SELECT count(*) FROM pg_proc p WHERE p.proname LIKE 'bot_b4_%' AND has_function_privilege('public',p.oid,'EXECUTE')").fetchone()==(0,)
print('E0.3 bot B4.1 operator workflow CAS, concurrency, atomic rollback and ambient denial: OK')
