import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

dsn=os.getenv('TEST_POSTGRES_DSN')
if not dsn: print('E0.3 bot B5.2 residual writers: skipped'); raise SystemExit(0)
import psycopg
from psycopg.conninfo import conninfo_to_dict,make_conninfo
ROOT=Path(__file__).resolve().parents[1]
with psycopg.connect(dsn) as c:
 c.execute("CREATE TABLE blocked_users(user_id bigint PRIMARY KEY,reason text NOT NULL,blocked_at timestamptz NOT NULL DEFAULT now());CREATE TABLE orders(order_id bigint PRIMARY KEY,user_id bigint NOT NULL,created_at timestamptz NOT NULL DEFAULT now(),currency text NOT NULL DEFAULT 'BTC',rub_amount numeric NOT NULL DEFAULT 1,status text NOT NULL DEFAULT 'pending',crypto_address text,paid_btc_tx text,receipt_sent_at timestamptz,updated_at timestamptz,network text);CREATE TABLE reserves(currency text PRIMARY KEY,amount numeric,updated_at timestamptz NOT NULL DEFAULT now())")
 c.execute((ROOT/'deploy/postgres/008_support.sql').read_text());c.execute((ROOT/'deploy/postgres/011_user_profiles.sql').read_text());c.execute((ROOT/'deploy/postgres/013_promos.sql').read_text());c.execute((ROOT/'deploy/postgres/018_provider_health.sql').read_text())
 c.execute("INSERT INTO provider_health(provider,failed_count,is_healthy,status,blocker) VALUES('Vertu',4,false,'DOWN','x');INSERT INTO support_tickets(user_id,subject,status) VALUES(20,'help','open')")
 c.execute("CREATE FUNCTION fail_b52() RETURNS trigger LANGUAGE plpgsql AS $$BEGIN IF NEW.message='FAULT' THEN RAISE EXCEPTION 'fault'; END IF; RETURN NEW; END$$;CREATE TRIGGER fail_support BEFORE INSERT ON support_messages FOR EACH ROW EXECUTE FUNCTION fail_b52()")
 c.execute((ROOT/'deploy/postgres/proposals/035_e0_bot_b1_role_envelope.sql').read_text());c.execute((ROOT/'deploy/postgres/proposals/047_e0_bot_b5_2_residual_identity_support_config_writers.sql').read_text())
parts=conninfo_to_dict(dsn);parts.update(user='obsidian_exchange_bot',password='synthetic-rehearsal-only');bot=make_conninfo(**parts)
def call(sql,args=()):
 with psycopg.connect(bot) as c:return c.execute(sql,args).fetchone()
with ThreadPoolExecutor(max_workers=8) as p: claims=list(p.map(lambda i:call('SELECT bot_b5_claim_referrer(30,%s)',(100+i,))[0],range(8)))
assert sum(claims)==1
promo=call("SELECT bot_b5_create_promo(' test_1 ',5,10,now()+interval '1 day')")[0]
assert call("SELECT bot_b5_reset_provider('Vertu')")== (True,)
assert call("SELECT * FROM bot_b5_admin_reply(1,'answer')")== (20,'help')
call("SELECT bot_b5_upsert_user(20,'name','First','Last')");call("SELECT bot_b5_upsert_user(20,'name2',NULL,NULL)")
denied=("SELECT bot_b5_create_promo('bad code',5,1,now()+interval '1 day')","SELECT bot_b5_create_promo('X',101,1,now()+interval '1 day')","SELECT bot_b5_reset_provider('')","SELECT bot_b5_admin_reply(1,'')","SELECT bot_b5_claim_referrer(1,1)","SELECT bot_b5_upsert_user(0,NULL,NULL,NULL)","SELECT * FROM bot_users","UPDATE provider_health SET is_healthy=true","SELECT nextval('promo_codes_id_seq')")
for sql in denied:
 try: call(sql)
 except psycopg.Error:continue
 raise AssertionError('unexpectedly allowed: '+sql)
try:call("SELECT * FROM bot_b5_admin_reply(1,'FAULT')")
except psycopg.Error:pass
else:raise AssertionError('support fault allowed')
with psycopg.connect(dsn) as c:
 assert c.execute('SELECT count(*) FROM referrals WHERE referred_id=30').fetchone()==(1,)
 assert c.execute('SELECT code FROM promo_codes WHERE id=%s',(promo,)).fetchone()==('TEST_1',)
 assert c.execute("SELECT failed_count,is_healthy,status,blocker FROM provider_health WHERE provider='Vertu'").fetchone()==(0,True,'READY','')
 assert c.execute("SELECT count(*) FROM support_messages WHERE ticket_id=1 AND sender='admin'").fetchone()==(1,)
 assert c.execute("SELECT status FROM support_tickets WHERE id=1").fetchone()==('answered',)
 assert c.execute("SELECT username,first_name,last_name FROM bot_users WHERE user_id=20").fetchone()==('name2',None,None)
 assert c.execute("SELECT has_table_privilege('obsidian_exchange_bot','referrals','SELECT'),has_table_privilege('obsidian_exchange_bot','promo_codes','INSERT'),has_sequence_privilege('obsidian_exchange_bot','promo_codes_id_seq','USAGE')").fetchone()==(False,False,False)
 for sig in ('bot_b5_create_promo(text,numeric,integer,timestamp with time zone)','bot_b5_reset_provider(text)','bot_b5_admin_reply(bigint,text)','bot_b5_claim_referrer(bigint,bigint)','bot_b5_upsert_user(bigint,text,text,text)'):
  assert c.execute("SELECT has_function_privilege('public',to_regprocedure(%s),'EXECUTE'),has_function_privilege('obsidian_exchange_bot',to_regprocedure(%s),'EXECUTE')",(sig,sig)).fetchone()==(False,True)
print('E0.3 bot B5.2 residual writer serialization, fault rollback and ambient denial: OK')
