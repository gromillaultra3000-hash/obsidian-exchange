import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
dsn=os.getenv('TEST_POSTGRES_DSN')
if not dsn:print('E0.3 bot B5.9 sell lifecycle: skipped');raise SystemExit(0)
import psycopg
from psycopg.conninfo import conninfo_to_dict,make_conninfo
ROOT=Path(__file__).resolve().parents[1]
with psycopg.connect(dsn) as c:
 c.execute("CREATE TABLE blocked_users(user_id bigint PRIMARY KEY,reason text NOT NULL,blocked_at timestamptz NOT NULL DEFAULT now());CREATE TABLE orders(order_id bigint PRIMARY KEY,user_id bigint NOT NULL,created_at timestamptz NOT NULL DEFAULT now(),currency text NOT NULL DEFAULT 'BTC',rub_amount numeric NOT NULL DEFAULT 1,status text NOT NULL,crypto_address text,paid_btc_tx text,receipt_sent_at timestamptz,updated_at timestamptz,network text);CREATE TABLE sent_notifications(order_id bigint,event text,PRIMARY KEY(order_id,event));CREATE TABLE reserves(currency text PRIMARY KEY,amount numeric,updated_at timestamptz NOT NULL DEFAULT now())")
 c.execute((ROOT/'deploy/postgres/010_sell_orders.sql').read_text())
 c.execute("INSERT INTO sell_orders(user_id,currency,crypto_amount,rub_amount,receive_address,tx_hash,status) VALUES(7,'BTC',1,100,'a','tx1','pending'),(8,'BTC',1,100,'a','tx2','cancelled'),(9,'BTC',1,100,'a','tx3','rejected'),(10,'BTC',1,100,'a','tx4','pending')")
 c.execute((ROOT/'deploy/postgres/proposals/035_e0_bot_b1_role_envelope.sql').read_text());c.execute((ROOT/'deploy/postgres/proposals/054_e0_bot_b5_9_sell_safe_lifecycle.sql').read_text())
parts=conninfo_to_dict(dsn);parts.update(user='obsidian_exchange_bot',password='synthetic-rehearsal-only');bot=make_conninfo(**parts)
def claim(i):
 with psycopg.connect(bot) as c:return c.execute('SELECT bot_b5_sell_claim(%s)',(i,)).fetchone()[0]
with ThreadPoolExecutor(max_workers=8) as p:rows=list(p.map(lambda _:claim(1),range(8)))
w=[x for x in rows if x.get('claimed')];assert len(w)==1;token=w[0]['attempt_token']
assert not claim(2)['claimed'] and not claim(3)['claimed']
with psycopg.connect(bot) as c:
 assert c.execute('SELECT bot_b5_sell_release_pre_submit(1,%s,%s)',(token,'a'*64)).fetchone()==(True,)
with ThreadPoolExecutor(max_workers=8) as p:rej=list(p.map(lambda _:claim(4),range(8)))
winner=[x for x in rej if x.get('claimed')][0]
with psycopg.connect(bot) as c:
 assert c.execute('SELECT bot_b5_sell_reject(4)').fetchone()==(False,)
 assert c.execute('SELECT bot_b5_sell_release_pre_submit(4,%s,%s)',(winner['attempt_token'],'b'*64)).fetchone()==(True,)
 assert c.execute('SELECT bot_b5_sell_reject(4)').fetchone()==(True,)
with psycopg.connect(dsn) as c:
 assert c.execute("SELECT status FROM sell_orders WHERE id IN(2,3) ORDER BY id").fetchall()==[('cancelled',),('rejected',)]
 assert c.execute("SELECT count(*) FROM sell_payout_attempts WHERE state='RELEASED'").fetchone()==(2,)
 assert c.execute("SELECT has_table_privilege('obsidian_exchange_bot','sell_orders','UPDATE')").fetchone()==(False,)
print('E0.3 bot B5.9 pending-only claim, terminal non-revival and evidence-bound release: OK')
