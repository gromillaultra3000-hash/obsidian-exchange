import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

dsn=os.getenv('TEST_POSTGRES_DSN')
if not dsn: print('E0.3 bot B5.3 notifications: skipped'); raise SystemExit(0)
import psycopg
from psycopg.conninfo import conninfo_to_dict,make_conninfo
ROOT=Path(__file__).resolve().parents[1]
with psycopg.connect(dsn) as c:
 c.execute("CREATE TABLE blocked_users(user_id bigint PRIMARY KEY,reason text NOT NULL,blocked_at timestamptz NOT NULL DEFAULT now());CREATE TABLE orders(order_id bigint PRIMARY KEY,user_id bigint NOT NULL,created_at timestamptz NOT NULL,currency text NOT NULL,rub_amount numeric NOT NULL,status text NOT NULL,crypto_address text,paid_btc_tx text,receipt_sent_at timestamptz,receipt_deadline timestamptz,montera_invoice_id text,updated_at timestamptz,network text);CREATE TABLE sent_notifications(order_id bigint NOT NULL,event text NOT NULL,PRIMARY KEY(order_id,event));CREATE TABLE reserves(currency text PRIMARY KEY,amount numeric,updated_at timestamptz NOT NULL DEFAULT now());CREATE TABLE payment_sessions(id bigserial PRIMARY KEY,order_id bigint NOT NULL,status text NOT NULL,session_token text NOT NULL);CREATE TABLE order_receipts(order_id bigint NOT NULL);CREATE TABLE promo_codes(id bigserial PRIMARY KEY,code text UNIQUE NOT NULL,discount_percent numeric NOT NULL,max_uses integer NOT NULL,uses_count integer NOT NULL DEFAULT 0,valid_until timestamptz NOT NULL,is_active boolean NOT NULL DEFAULT true);CREATE TABLE bot_notification_jobs(id bigserial PRIMARY KEY,kind text NOT NULL,dedupe_key text NOT NULL,payload jsonb NOT NULL,state text NOT NULL DEFAULT 'pending',attempts integer NOT NULL DEFAULT 0,created_at timestamptz NOT NULL DEFAULT now(),claimed_at timestamptz,sent_at timestamptz,updated_at timestamptz NOT NULL DEFAULT now(),UNIQUE(kind,dedupe_key))")
 now=c.execute('SELECT now()').fetchone()[0]
 c.execute("INSERT INTO orders VALUES(1,101,%s-'10 minutes'::interval,'BTC',1000,'pending',NULL,NULL,NULL,NULL,NULL,%s-'10 minutes'::interval,NULL),(2,102,%s,'BTC',1000,'pending',NULL,NULL,NULL,%s+'10 minutes'::interval,'INV',%s,NULL),(3,103,%s-'1 hour'::interval,'LTC',1000,'paid',NULL,'',NULL,NULL,NULL,%s-'30 minutes'::interval,NULL),(4,104,%s-'20 days'::interval,'BTC',1000,'sent',NULL,'tx',NULL,NULL,NULL,%s-'20 days'::interval,NULL),(5,105,%s-'3 hours'::interval,'BTC',1000,'expired',NULL,NULL,NULL,NULL,NULL,%s-'2 hours'::interval,NULL)",(now,now,now,now,now,now,now,now,now,now,now))
 c.execute("INSERT INTO payment_sessions(order_id,status,session_token) VALUES(1,'created','tok')")
 c.execute((ROOT/'deploy/postgres/proposals/035_e0_bot_b1_role_envelope.sql').read_text());c.execute((ROOT/'deploy/postgres/proposals/048_e0_bot_b5_3_notification_queue_writers.sql').read_text())
parts=conninfo_to_dict(dsn);parts.update(user='obsidian_exchange_bot',password='synthetic-rehearsal-only');bot=make_conninfo(**parts)
def call(sql,args=()):
 with psycopg.connect(bot) as c:return c.execute(sql,args).fetchone()
assert call('SELECT bot_b5_queue_due_abandoned(%s,200)',(now,))==(1,)
assert call('SELECT bot_b5_queue_due_montera(%s,200)',(now,))==(1,)
assert call('SELECT bot_b5_queue_due_payout_delays(15,%s,200)',(now,))==(1,)
assert call('SELECT bot_b5_queue_due_recalls(%s,200)',(now,))==(1,)
assert call('SELECT bot_b5_queue_due_winbacks(5,72,%s,200)',(now,))==(1,)
assert call('SELECT bot_b5_queue_due_abandoned(%s,200)',(now,))==(0,)
def claim(_):return call('SELECT id,kind,dedupe_key,payload,attempts FROM bot_b5_notification_claim(NULL)')
with ThreadPoolExecutor(max_workers=8) as p:claimed=list(p.map(claim,range(8)))
items=[x for x in claimed if x]
assert len(items)==6 and len({x[0] for x in items})==6 and all(x[4]==1 for x in items)
assert call('SELECT bot_b5_notification_mark_sent(%s)',(items[0][0],))==(True,)
assert call('SELECT bot_b5_notification_mark_sent(%s)',(items[0][0],))==(False,)
assert call('SELECT bot_b5_notification_retry(%s)',(items[1][0],))==(True,)
for sql in ("SELECT * FROM bot_b5_notification_claim('bad')","SELECT bot_b5_notification_mark_sent(0)","SELECT bot_b5_queue_due_payout_delays(-1,now(),1)","SELECT bot_b5_queue_due_winbacks('NaN',1,now(),1)","SELECT * FROM bot_notification_jobs","UPDATE bot_notification_jobs SET state='sent'","SELECT nextval('bot_notification_jobs_id_seq')"):
 try:call(sql)
 except psycopg.Error:continue
 raise AssertionError('unexpectedly allowed: '+sql)
with psycopg.connect(dsn) as c:
 assert c.execute('SELECT count(*) FROM sent_notifications').fetchone()==(5,)
 assert c.execute('SELECT count(*) FROM bot_notification_jobs').fetchone()==(6,)
 assert c.execute("SELECT count(*) FROM bot_notification_jobs WHERE kind LIKE 'montera_%'").fetchone()==(2,)
 assert c.execute("SELECT count(*) FROM promo_codes WHERE max_uses=1").fetchone()==(1,)
 assert c.execute("SELECT has_table_privilege('obsidian_exchange_bot','bot_notification_jobs','SELECT'),has_table_privilege('obsidian_exchange_bot','sent_notifications','INSERT'),has_sequence_privilege('obsidian_exchange_bot','bot_notification_jobs_id_seq','USAGE')").fetchone()==(False,False,False)
print('E0.3 bot B5.3 queue selection, atomic markers, claims and ambient denial: OK')
