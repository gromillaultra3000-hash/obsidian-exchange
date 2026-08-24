import json,os
from pathlib import Path
dsn=os.getenv('TEST_POSTGRES_DSN')
if not dsn: print('E0.3 bot B2.2c2b reporting reads: skipped'); raise SystemExit(0)
import psycopg
from psycopg.conninfo import conninfo_to_dict,make_conninfo
ROOT=Path(__file__).resolve().parents[1]
with psycopg.connect(dsn) as c:
 c.execute('CREATE TABLE blocked_users(user_id bigint PRIMARY KEY,reason text NOT NULL,blocked_at timestamptz NOT NULL DEFAULT now())')
 c.execute("CREATE TABLE orders(id bigserial PRIMARY KEY,order_id bigint UNIQUE,user_id bigint NOT NULL,created_at timestamptz NOT NULL DEFAULT now(),currency text NOT NULL DEFAULT 'BTC',rub_amount numeric NOT NULL DEFAULT 0,status text NOT NULL,crypto_address text,paid_btc_tx text,receipt_sent_at timestamptz,updated_at timestamptz,network text)")
 c.execute('CREATE TABLE sent_notifications(order_id bigint NOT NULL,event text NOT NULL,PRIMARY KEY(order_id,event))'); c.execute('CREATE TABLE reserves(currency text PRIMARY KEY,amount numeric NOT NULL,updated_at timestamptz NOT NULL DEFAULT now())')
 c.execute((ROOT/'deploy/postgres/006_scheduled_orders.sql').read_text())
 c.execute("INSERT INTO orders(order_id,user_id,created_at,currency,rub_amount,status) VALUES(1,7,CURRENT_DATE-2,'BTC',100,'sent'),(2,7,now(),'BTC',200,'sent'),(3,8,now(),'LTC',300,'pending'),(4,9,now(),'LTC',400,'paid');INSERT INTO reserves VALUES('BTC',1,now()),('LTC',2,now());INSERT INTO limit_orders(user_id,currency,target_rate,direction,rub_amount,crypto_address,payment_method,expires_at) VALUES(7,'BTC',1,'above',1,'a','x',now()+interval '1 day');INSERT INTO dca_schedules(user_id,currency,rub_amount,crypto_address,interval_days,next_run) VALUES(7,'BTC',1,'a',1,now())")
 c.execute((ROOT/'deploy/postgres/proposals/035_e0_bot_b1_role_envelope.sql').read_text()); c.execute((ROOT/'deploy/postgres/proposals/041_e0_bot_b2_2c2b_operator_reporting_reads.sql').read_text())
parts=conninfo_to_dict(dsn);parts.update(user='obsidian_exchange_bot',password='synthetic-rehearsal-only');bot=make_conninfo(**parts)
with psycopg.connect(bot) as c:
 assert c.execute('SELECT jsonb_array_length(bot_b2_reserves_detailed())').fetchone()==(2,)
 today=c.execute('SELECT bot_b2_today_summary()').fetchone()[0]; assert today['today_count']==3 and today['today_sent']==1 and today['active_limits']==1 and today['active_dca']==1
 period=c.execute("SELECT bot_b2_period_order_report(CURRENT_DATE-3,CURRENT_DATE)").fetchone()[0]; assert period['sent_count']==2 and period['total_count']==4 and len(period['currencies'])==1
 stats=c.execute("SELECT bot_b2_cumulative_stats(%s::jsonb,CURRENT_DATE-3,%s::jsonb,%s::jsonb)",(json.dumps({'all':str(__import__('datetime').date.today()-__import__('datetime').timedelta(days=3))}),json.dumps(['BTC','LTC']),json.dumps(['sent','paid']))).fetchone()[0]
 assert stats['periods']['all'][0]==2 and stats['currencies']['BTC'][0]==2 and stats['statuses']['paid']==1
for sql in ("SELECT bot_b2_period_order_report(CURRENT_DATE,CURRENT_DATE-1)","SELECT bot_b2_period_order_report(CURRENT_DATE-367,CURRENT_DATE)","SELECT bot_b2_cumulative_stats('[]',CURRENT_DATE,'[]','[]')","SELECT bot_b2_cumulative_stats('{}',CURRENT_DATE,'[\"\"]','[]')",'SELECT * FROM orders','SELECT * FROM reserves'):
 try:
  with psycopg.connect(bot) as c: c.execute(sql)
 except psycopg.Error: continue
 raise AssertionError('unexpectedly allowed: '+sql)
with psycopg.connect(dsn) as c:
 assert c.execute("SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='public' AND has_function_privilege('obsidian_exchange_bot',p.oid,'EXECUTE')").fetchone()[0]==8
 assert c.execute("SELECT has_table_privilege('obsidian_exchange_bot','orders','SELECT'),has_table_privilege('obsidian_exchange_bot','reserves','SELECT')").fetchone()==(False,False)
print('E0.3 bot B2.2c2b reporting reads and ambient denial: OK')
