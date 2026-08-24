import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
dsn=os.getenv('TEST_POSTGRES_DSN')
if not dsn: print('E0.3 bot B3.1 engagement writers: skipped'); raise SystemExit(0)
import psycopg
from psycopg.conninfo import conninfo_to_dict,make_conninfo
ROOT=Path(__file__).resolve().parents[1]
with psycopg.connect(dsn) as c:
 c.execute('CREATE TABLE blocked_users(user_id bigint PRIMARY KEY,reason text NOT NULL,blocked_at timestamptz NOT NULL DEFAULT now())')
 c.execute("CREATE TABLE orders(id bigserial PRIMARY KEY,order_id bigint UNIQUE,user_id bigint NOT NULL,created_at timestamptz NOT NULL DEFAULT now(),currency text NOT NULL DEFAULT 'BTC',rub_amount numeric NOT NULL DEFAULT 0,status text NOT NULL,crypto_address text,paid_btc_tx text,receipt_sent_at timestamptz,updated_at timestamptz,network text)")
 c.execute('CREATE TABLE sent_notifications(order_id bigint NOT NULL,event text NOT NULL,PRIMARY KEY(order_id,event))'); c.execute('CREATE TABLE reserves(currency text PRIMARY KEY,amount numeric NOT NULL,updated_at timestamptz NOT NULL DEFAULT now())')
 c.execute('CREATE TABLE admin_log(id bigserial PRIMARY KEY,admin_id bigint NOT NULL,action text NOT NULL,target_id bigint,details text,created_at timestamptz DEFAULT now())')
 c.execute('CREATE TABLE bot_users(user_id bigint PRIMARY KEY,broadcast_enabled boolean NOT NULL DEFAULT true)')
 c.execute('CREATE TABLE rate_subscriptions(user_id bigint PRIMARY KEY,enabled boolean DEFAULT true,last_notified double precision DEFAULT 0,last_btc numeric DEFAULT 0,last_ltc numeric DEFAULT 0,last_usdt numeric DEFAULT 0)')
 c.execute("CREATE TABLE reviews(id bigserial PRIMARY KEY,order_id bigint UNIQUE NOT NULL,user_id bigint NOT NULL,rating integer,comment text,status text NOT NULL DEFAULT 'pending_rating')")
 c.execute("INSERT INTO orders(order_id,user_id,status) VALUES(101,7,'sent'),(102,8,'sent');INSERT INTO reviews(order_id,user_id) VALUES(101,7),(102,8);INSERT INTO bot_users VALUES(7,true),(8,true);INSERT INTO rate_subscriptions(user_id) VALUES(7)")
 c.execute("CREATE FUNCTION fail_audit() RETURNS trigger LANGUAGE plpgsql AS $$BEGIN IF NEW.action='fault' THEN RAISE EXCEPTION 'injected'; END IF; RETURN NEW; END$$;CREATE TRIGGER fail_audit BEFORE INSERT ON admin_log FOR EACH ROW EXECUTE FUNCTION fail_audit()")
 c.execute((ROOT/'deploy/postgres/proposals/035_e0_bot_b1_role_envelope.sql').read_text()); c.execute((ROOT/'deploy/postgres/proposals/042_e0_bot_b3_1_engagement_non_money_writers.sql').read_text())
parts=conninfo_to_dict(dsn);parts.update(user='obsidian_exchange_bot',password='synthetic-rehearsal-only');bot=make_conninfo(**parts)
with psycopg.connect(bot) as c:
 assert c.execute("SELECT bot_b3_log_action(9,'ok',7,'detail')>0").fetchone()==(True,)
 assert c.execute('SELECT bot_b3_disable_broadcast(7),bot_b3_disable_rates(7)').fetchone()==(True,True)
 assert c.execute('SELECT bot_b3_update_rates(7,1,2,3,4)').fetchone()==(True,)
 assert c.execute('SELECT bot_b3_rate_review(101,7,5)').fetchone()==(True,)
 assert c.execute("SELECT bot_b3_comment_review(101,7,'great')").fetchone()==(True,)
 assert c.execute("SELECT bot_b3_finalize_review(101,7)->>'status'").fetchone()==('published',)
 assert c.execute('SELECT bot_b3_rate_review(102,7,5),bot_b3_comment_review(102,7,\'x\'),bot_b3_finalize_review(102,7)').fetchone()==(False,False,None)
def toggle(_):
 with psycopg.connect(bot) as c: return c.execute('SELECT bot_b3_toggle_rate(99)').fetchone()[0]
with ThreadPoolExecutor(max_workers=8) as pool: states=list(pool.map(toggle,range(8)))
assert states.count(True)==4 and states.count(False)==4
for sql in ("SELECT bot_b3_log_action(0,'x',NULL,NULL)","SELECT bot_b3_log_action(9,'',NULL,NULL)","SELECT bot_b3_log_action(9,'fault',NULL,NULL)",'SELECT bot_b3_toggle_rate(0)','SELECT bot_b3_update_rates(7,-1,2,3,4)','SELECT bot_b3_rate_review(101,7,6)',"SELECT bot_b3_comment_review(101,7,repeat('x',2001))",'UPDATE bot_users SET broadcast_enabled=true','SELECT * FROM reviews'):
 try:
  with psycopg.connect(bot) as c: c.execute(sql)
 except psycopg.Error: continue
 raise AssertionError('unexpectedly allowed: '+sql)
with psycopg.connect(dsn) as c:
 assert c.execute("SELECT count(*) FROM admin_log WHERE action='fault'").fetchone()==(0,)
 assert c.execute('SELECT enabled FROM rate_subscriptions WHERE user_id=99').fetchone()==(True,)
 assert c.execute("SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='public' AND has_function_privilege('obsidian_exchange_bot',p.oid,'EXECUTE')").fetchone()[0]==12
 assert c.execute("SELECT has_table_privilege('obsidian_exchange_bot','reviews','UPDATE'),has_table_privilege('obsidian_exchange_bot','admin_log','INSERT')").fetchone()==(False,False)
print('E0.3 bot B3.1 engagement writers, concurrency, rollback and ambient denial: OK')
