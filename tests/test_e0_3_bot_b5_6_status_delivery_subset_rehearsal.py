import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
dsn=os.getenv('TEST_POSTGRES_DSN')
if not dsn:print('E0.3 bot B5.6 status subset: skipped');raise SystemExit(0)
import psycopg
from psycopg.conninfo import conninfo_to_dict,make_conninfo
ROOT=Path(__file__).resolve().parents[1]
with psycopg.connect(dsn) as c:
 c.execute("CREATE TABLE blocked_users(user_id bigint PRIMARY KEY,reason text NOT NULL,blocked_at timestamptz NOT NULL DEFAULT now());CREATE TABLE orders(order_id bigint PRIMARY KEY,user_id bigint NOT NULL,created_at timestamptz NOT NULL DEFAULT now(),currency text NOT NULL DEFAULT 'BTC',rub_amount numeric NOT NULL DEFAULT 1,status text NOT NULL,crypto_address text,paid_btc_tx text,receipt_sent_at timestamptz,updated_at timestamptz,network text);CREATE TABLE sent_notifications(order_id bigint,event text,PRIMARY KEY(order_id,event));CREATE TABLE reserves(currency text PRIMARY KEY,amount numeric,updated_at timestamptz NOT NULL DEFAULT now());CREATE TABLE gift_vouchers(id bigserial PRIMARY KEY,order_id bigint,status text NOT NULL)")
 c.execute("INSERT INTO orders(order_id,user_id,status) VALUES(1,7,'paid'),(2,7,'sent'),(3,7,'pending');INSERT INTO gift_vouchers(order_id,status) VALUES(1,'pending')")
 c.execute((ROOT/'deploy/postgres/proposals/035_e0_bot_b1_role_envelope.sql').read_text());c.execute((ROOT/'deploy/postgres/proposals/051_e0_bot_b5_6_status_delivery_subset.sql').read_text())
parts=conninfo_to_dict(dsn);parts.update(user='obsidian_exchange_bot',password='synthetic-rehearsal-only');bot=make_conninfo(**parts)
def call(event):
 with psycopg.connect(bot) as c:return c.execute('SELECT bot_b5_complete_status_delivery(1,%s)',(event,)).fetchone()[0]
with ThreadPoolExecutor(max_workers=8) as p:r=list(p.map(lambda _ :call('paid'),range(8)))
assert sum(r)==1
with psycopg.connect(bot) as c:
 assert c.execute("SELECT bot_b5_complete_status_delivery(2,'sent')").fetchone()==(True,)
 assert c.execute("SELECT bot_b5_complete_status_delivery(3,'paid')").fetchone()==(False,)
 c.commit()
 for event in ('payout_triggered','payout_held'):
  try:c.execute('SELECT bot_b5_complete_status_delivery(1,%s)',(event,))
  except psycopg.Error:c.rollback()
  else:raise AssertionError('payout event allowed')
with psycopg.connect(dsn) as c:
 assert c.execute("SELECT status FROM gift_vouchers WHERE order_id=1").fetchone()==('paid',)
 assert c.execute('SELECT count(*) FROM sent_notifications').fetchone()==(2,)
print('E0.3 bot B5.6 paid/sent subset single marker, gift atomicity and payout-event denial: OK')
