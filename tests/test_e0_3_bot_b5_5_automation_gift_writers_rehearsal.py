import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
dsn=os.getenv('TEST_POSTGRES_DSN')
if not dsn:print('E0.3 bot B5.5 automation/gifts: skipped');raise SystemExit(0)
import psycopg
from psycopg.conninfo import conninfo_to_dict,make_conninfo
ROOT=Path(__file__).resolve().parents[1]
with psycopg.connect(dsn) as c:
 c.execute('CREATE TABLE blocked_users(user_id bigint PRIMARY KEY,reason text NOT NULL,blocked_at timestamptz NOT NULL DEFAULT now());CREATE TABLE reserves(currency text PRIMARY KEY,amount numeric,updated_at timestamptz NOT NULL DEFAULT now());CREATE TABLE sent_notifications(order_id bigint,event text,PRIMARY KEY(order_id,event))')
 c.execute((ROOT/'deploy/postgres/019_orders.sql').read_text());c.execute((ROOT/'deploy/postgres/006_scheduled_orders.sql').read_text());c.execute((ROOT/'deploy/postgres/005_gift_vouchers.sql').read_text())
 c.execute("INSERT INTO dca_schedules(user_id,currency,rub_amount,crypto_address,interval_days,next_run) VALUES(7,'BTC',100,'a',7,now()-interval '1 minute'),(8,'BTC',100,'a',7,now()+interval '1 day');INSERT INTO limit_orders(user_id,currency,target_rate,direction,rub_amount,crypto_address,payment_method,expires_at) VALUES(7,'BTC',10,'above',100,'a','x',now()+interval '1 hour'),(8,'BTC',10,'above',100,'a','x',now()-interval '1 hour'),(9,'BTC',10,'above',100,'a','x',now()+interval '1 hour');INSERT INTO gift_vouchers(sender_id,currency,rub_amount,code,status) VALUES(7,'BTC',100,'PAID01','paid'),(7,'BTC',100,'PAID02','paid')")
 c.execute((ROOT/'deploy/postgres/proposals/035_e0_bot_b1_role_envelope.sql').read_text());c.execute((ROOT/'deploy/postgres/proposals/050_e0_bot_b5_5_automation_gift_writers.sql').read_text())
 expected_dca=c.execute('SELECT next_run FROM dca_schedules WHERE id=1').fetchone()[0];expected_limit=c.execute('SELECT expires_at FROM limit_orders WHERE id=1').fetchone()[0]
parts=conninfo_to_dict(dsn);parts.update(user='obsidian_exchange_bot',password='synthetic-rehearsal-only');bot=make_conninfo(**parts)
def call(sql,args=()):
 with psycopg.connect(bot) as c:return c.execute(sql,args).fetchone()
with ThreadPoolExecutor(max_workers=8) as p:dca=list(p.map(lambda _:call('SELECT bot_b5_dca_run(1,%s,\'dest\',10,1)',(expected_dca,))[0],range(8)))
with ThreadPoolExecutor(max_workers=8) as p:limit=list(p.map(lambda _:call('SELECT bot_b5_limit_trigger(1,%s,\'dest\',10,1)',(expected_limit,))[0],range(8)))
with ThreadPoolExecutor(max_workers=8) as p:gift=list(p.map(lambda i:call("SELECT bot_b5_gift_redeem(1,%s,'dest',10,1)",(20+i,))[0],range(8)))
assert sum(x is not None for x in dca)==sum(x is not None for x in limit)==sum(x is not None for x in gift)==1
assert call("SELECT * FROM bot_b5_gift_issue(9,'btc',100,' gift02 ','dest',10,1)") is not None
try:call("SELECT * FROM bot_b5_gift_issue(9,'BTC',100,'GIFT02','dest',10,1)")
except psycopg.Error:pass
else:raise AssertionError('gift conflict allowed')
assert call('SELECT bot_b5_dca_cancel(2,8)')==(True,) and call('SELECT bot_b5_limit_cancel(3,9)')==(True,) and call('SELECT bot_b5_limit_expire(100)')==(1,)
for sql in ("SELECT bot_b5_dca_cancel(1,NULL)","SELECT bot_b5_limit_expire(101)","SELECT * FROM orders","UPDATE gift_vouchers SET status='paid'","SELECT nextval('gift_vouchers_id_seq')"):
 try:call(sql)
 except psycopg.Error:continue
 raise AssertionError('unexpectedly allowed: '+sql)
assert call("SELECT bot_b5_gift_redeem(2,7,'x',1,1)")== (None,)
with psycopg.connect(dsn) as c:
 assert c.execute('SELECT runs_total FROM dca_schedules WHERE id=1').fetchone()==(1,)
 assert c.execute("SELECT status FROM limit_orders WHERE id=1").fetchone()==('triggered',)
 assert c.execute("SELECT status,recipient_id FROM gift_vouchers WHERE id=1").fetchone()[0]=='redeemed'
 assert c.execute('SELECT count(*) FROM orders').fetchone()==(4,)
 assert c.execute("SELECT has_table_privilege('obsidian_exchange_bot','gift_vouchers','UPDATE'),has_sequence_privilege('obsidian_exchange_bot','orders_order_id_seq','USAGE')").fetchone()==(False,False)
print('E0.3 bot B5.5 automation/gift single winners, owner cancel, bounded expiry and ambient denial: OK')
