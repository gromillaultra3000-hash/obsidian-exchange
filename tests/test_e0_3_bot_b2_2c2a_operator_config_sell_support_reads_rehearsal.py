import os
from pathlib import Path
dsn=os.getenv('TEST_POSTGRES_DSN')
if not dsn: print('E0.3 bot B2.2c2a config/sell/support reads: skipped'); raise SystemExit(0)
import psycopg
from psycopg.conninfo import conninfo_to_dict,make_conninfo
ROOT=Path(__file__).resolve().parents[1]
with psycopg.connect(dsn) as c:
 c.execute('CREATE TABLE blocked_users(user_id bigint PRIMARY KEY,reason text NOT NULL,blocked_at timestamptz NOT NULL DEFAULT now())')
 c.execute("CREATE TABLE orders(id bigserial PRIMARY KEY,order_id bigint UNIQUE,user_id bigint NOT NULL,created_at timestamptz NOT NULL DEFAULT now(),currency text NOT NULL DEFAULT 'BTC',rub_amount numeric NOT NULL DEFAULT 0,status text NOT NULL,crypto_address text,paid_btc_tx text,receipt_sent_at timestamptz,updated_at timestamptz,network text)")
 c.execute('CREATE TABLE sent_notifications(order_id bigint NOT NULL,event text NOT NULL,PRIMARY KEY(order_id,event))'); c.execute('CREATE TABLE reserves(currency text PRIMARY KEY,amount numeric NOT NULL,updated_at timestamptz NOT NULL DEFAULT now())')
 for schema in ('008_support.sql','010_sell_orders.sql','013_promos.sql','018_provider_health.sql'):
  text=(ROOT/'deploy/postgres'/schema).read_text()
  if schema=='013_promos.sql': text=text[text.index('CREATE TABLE promo_codes'):text.index('CREATE TABLE sent_notifications')]
  c.execute(text)
 c.execute("INSERT INTO promo_codes(code,discount_percent,max_uses,valid_until,is_active) VALUES('ON',5,2,now()+interval '1 day',true),('OFF',5,2,now()+interval '1 day',false)")
 c.execute("INSERT INTO provider_health(provider,avg_response_time,failed_count,is_healthy,status,blocker) VALUES('p1',.2,1,true,'READY','');INSERT INTO provider_attempts VALUES('p1',now(),true),('p1',now(),false)")
 c.execute("INSERT INTO sell_orders(user_id,currency,crypto_amount,rub_amount,receive_address,status) VALUES(7,'BTC',.1,1000,'addr','pending')")
 c.execute("INSERT INTO support_tickets(user_id,username,subject,status,updated_at) VALUES(7,'a','old','open',now()-interval '1 hour'),(8,'b','new','answered',now()),(9,'c','closed','closed',now())")
 c.execute((ROOT/'deploy/postgres/proposals/035_e0_bot_b1_role_envelope.sql').read_text()); c.execute((ROOT/'deploy/postgres/proposals/040_e0_bot_b2_2c2a_operator_config_sell_support_reads.sql').read_text())
parts=conninfo_to_dict(dsn);parts.update(user='obsidian_exchange_bot',password='synthetic-rehearsal-only');bot=make_conninfo(**parts)
with psycopg.connect(bot) as c:
 assert c.execute('SELECT jsonb_array_length(bot_b2_active_promos(100))').fetchone()==(1,)
 assert c.execute("SELECT bot_b2_provider_health_all()->0->>'provider'").fetchone()==('p1',)
 assert c.execute("SELECT bot_b2_provider_attempt_stats('p1',now()-interval '1 day')->>'success'").fetchone()==('1',)
 assert c.execute("SELECT bot_b2_sell_order(1)->>'currency'").fetchone()==('BTC',)
 assert c.execute('SELECT bot_b2_support_open_count()').fetchone()==(2,)
 assert c.execute("SELECT bot_b2_support_staff_new(100)->0->>'subject'").fetchone()==('old',)
 assert c.execute("SELECT bot_b2_support_staff_open(100)->0->>'subject'").fetchone()==('new',)
for sql in ('SELECT bot_b2_active_promos(101)',"SELECT bot_b2_provider_attempt_stats('',now())","SELECT bot_b2_provider_attempt_stats('p1',now()-interval '32 days')",'SELECT bot_b2_sell_order(0)','SELECT bot_b2_support_staff_new(0)','SELECT bot_b2_support_staff_open(101)','SELECT * FROM promo_codes','SELECT * FROM sell_orders','SELECT * FROM support_tickets'):
 try:
  with psycopg.connect(bot) as c: c.execute(sql)
 except psycopg.Error: continue
 raise AssertionError('unexpectedly allowed: '+sql)
with psycopg.connect(dsn) as c:
 assert c.execute("SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='public' AND has_function_privilege('obsidian_exchange_bot',p.oid,'EXECUTE')").fetchone()[0]==11
 assert c.execute("SELECT has_table_privilege('obsidian_exchange_bot','promo_codes','SELECT'),has_table_privilege('obsidian_exchange_bot','sell_orders','SELECT'),has_table_privilege('obsidian_exchange_bot','support_tickets','SELECT')").fetchone()==(False,False,False)
print('E0.3 bot B2.2c2a config/sell/support reads and ambient denial: OK')
