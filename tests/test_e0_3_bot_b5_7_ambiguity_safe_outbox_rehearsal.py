import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
dsn=os.getenv('TEST_POSTGRES_DSN')
if not dsn:print('E0.3 bot B5.7 outbox: skipped');raise SystemExit(0)
import psycopg
from psycopg.conninfo import conninfo_to_dict,make_conninfo
ROOT=Path(__file__).resolve().parents[1]
with psycopg.connect(dsn) as c:
 c.execute("CREATE TABLE blocked_users(user_id bigint PRIMARY KEY,reason text NOT NULL,blocked_at timestamptz NOT NULL DEFAULT now());CREATE TABLE orders(order_id bigint PRIMARY KEY,user_id bigint NOT NULL,created_at timestamptz NOT NULL DEFAULT now(),currency text NOT NULL DEFAULT 'BTC',rub_amount numeric NOT NULL DEFAULT 1,status text NOT NULL,crypto_address text,paid_btc_tx text,receipt_sent_at timestamptz,updated_at timestamptz,network text);CREATE TABLE sent_notifications(order_id bigint,event text,PRIMARY KEY(order_id,event));CREATE TABLE reserves(currency text PRIMARY KEY,amount numeric,updated_at timestamptz NOT NULL DEFAULT now());CREATE TABLE notification_outbox(id bigserial PRIMARY KEY,topic text NOT NULL,aggregate_id text NOT NULL,recipient_id bigint NOT NULL,payload jsonb NOT NULL,state text NOT NULL DEFAULT 'pending' CHECK(state IN('pending','sending','sent')),attempts integer NOT NULL DEFAULT 0,created_at timestamptz NOT NULL DEFAULT now(),claimed_at timestamptz,sent_at timestamptz,updated_at timestamptz NOT NULL DEFAULT now(),UNIQUE(topic,aggregate_id))")
 c.execute("INSERT INTO notification_outbox(topic,aggregate_id,recipient_id,payload) SELECT 't',g::text,g,'{}' FROM generate_series(1,8) g")
 c.execute((ROOT/'deploy/postgres/proposals/035_e0_bot_b1_role_envelope.sql').read_text());c.execute((ROOT/'deploy/postgres/proposals/052_e0_bot_b5_7_ambiguity_safe_outbox.sql').read_text())
parts=conninfo_to_dict(dsn);parts.update(user='obsidian_exchange_bot',password='synthetic-rehearsal-only');bot=make_conninfo(**parts)
def claim(_):
 with psycopg.connect(bot) as c:return c.execute('SELECT * FROM bot_b5_outbox_claim()').fetchone()
with ThreadPoolExecutor(max_workers=8) as p:rows=list(p.map(claim,range(8)))
assert len({r[0] for r in rows})==8 and all(r[5]==1 and len(r[6])==32 for r in rows)
with psycopg.connect(bot) as c:
 assert c.execute('SELECT bot_b5_outbox_mark_sent(%s,%s)',(rows[0][0],rows[0][6])).fetchone()==(True,)
 assert c.execute('SELECT bot_b5_outbox_retry_pre_submit(%s,%s,%s)',(rows[1][0],rows[1][6],'a'*64)).fetchone()==(True,)
 assert c.execute('SELECT bot_b5_outbox_mark_uncertain(%s,%s,%s)',(rows[2][0],rows[2][6],'ambiguous_send')).fetchone()==(True,)
 assert c.execute('SELECT bot_b5_outbox_retry_pre_submit(%s,%s,%s)',(rows[2][0],rows[2][6],'b'*64)).fetchone()==(False,)
with psycopg.connect(dsn) as c:
 assert c.execute("SELECT state,count(*) FROM notification_outbox GROUP BY state ORDER BY state").fetchall()==[('pending',1),('review',1),('sending',5),('sent',1)]
 assert c.execute("SELECT has_table_privilege('obsidian_exchange_bot','notification_outbox','UPDATE')").fetchone()==(False,)
print('E0.3 bot B5.7 token-bound claim, pre-submit retry and ambiguous-review: OK')
