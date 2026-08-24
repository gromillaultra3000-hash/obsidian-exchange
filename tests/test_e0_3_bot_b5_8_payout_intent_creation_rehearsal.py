import os,json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
dsn=os.getenv('TEST_POSTGRES_DSN')
if not dsn:print('E0.3 bot B5.8 payout intents: skipped');raise SystemExit(0)
import psycopg
from psycopg.conninfo import conninfo_to_dict,make_conninfo
ROOT=Path(__file__).resolve().parents[1]
with psycopg.connect(dsn) as c:
 c.execute("CREATE TABLE blocked_users(user_id bigint PRIMARY KEY,reason text NOT NULL,blocked_at timestamptz NOT NULL DEFAULT now());CREATE TABLE orders(order_id bigint PRIMARY KEY,user_id bigint NOT NULL,created_at timestamptz NOT NULL DEFAULT now(),currency text NOT NULL,rub_amount numeric NOT NULL,status text NOT NULL,crypto_address text,paid_btc_tx text,receipt_sent_at timestamptz,updated_at timestamptz,network text,agreed_crypto_amount numeric);CREATE TABLE sent_notifications(order_id bigint,event text,PRIMARY KEY(order_id,event));CREATE TABLE reserves(currency text PRIMARY KEY,amount numeric,updated_at timestamptz NOT NULL DEFAULT now());CREATE TABLE referrals(referrer_id bigint,referred_id bigint UNIQUE,total_bonus_btc numeric NOT NULL,PRIMARY KEY(referrer_id,referred_id))")
 c.execute((ROOT/'deploy/postgres/001_payout_core.sql').read_text())
 c.execute("INSERT INTO orders VALUES(1,7,now(),'btc',1000,'paid','addr',NULL,NULL,now(),'btc',0.01),(2,7,now(),'BTC',1000,'pending','addr',NULL,NULL,now(),'BTC',0.01);INSERT INTO referrals VALUES(9,10,0.02),(9,11,0.03)")
 c.execute((ROOT/'deploy/postgres/proposals/035_e0_bot_b1_role_envelope.sql').read_text());c.execute((ROOT/'deploy/postgres/proposals/053_e0_bot_b5_8_payout_intent_creation.sql').read_text())
parts=conninfo_to_dict(dsn);parts.update(user='obsidian_exchange_bot',password='synthetic-rehearsal-only');bot=make_conninfo(**parts)
def order(_):
 with psycopg.connect(bot) as c:return c.execute('SELECT bot_b5_create_order_payout_intent(1)').fetchone()[0]
def referral(_):
 with psycopg.connect(bot) as c:return c.execute("SELECT bot_b5_request_referral_payout(9,'dest',0.01)").fetchone()[0]
with ThreadPoolExecutor(max_workers=8) as p:orders=list(p.map(order,range(8)))
with ThreadPoolExecutor(max_workers=8) as p:refs=list(p.map(referral,range(8)))
assert len({x['id'] for x in orders})==len({x['id'] for x in refs})==1
assert all(x['crypto_amount']==0.01 and x['destination']=='addr' for x in orders)
assert all(x['crypto_amount']==0.05 and x['destination']=='dest' for x in refs)
with psycopg.connect(bot) as c:
 for sql in ("SELECT bot_b5_create_order_payout_intent(2)","SELECT bot_b5_request_referral_payout(8,'d',1)",'SELECT * FROM payout_intents','INSERT INTO payout_intents(order_id,idempotency_key,source,rub_amount,crypto_amount,currency,destination) VALUES(3,\'x\',\'x\',1,1,\'BTC\',\'a\')'):
  try:c.execute(sql)
  except psycopg.Error:c.rollback()
  else:raise AssertionError('unexpectedly allowed: '+sql)
with psycopg.connect(dsn) as c:
 assert c.execute('SELECT count(*) FROM payout_intents').fetchone()==(1,)
 assert c.execute('SELECT count(*) FROM referral_payout_intents').fetchone()==(1,)
 assert c.execute("SELECT has_table_privilege('obsidian_exchange_bot','payout_intents','INSERT'),has_sequence_privilege('obsidian_exchange_bot','payout_intents_id_seq','USAGE')").fetchone()==(False,False)
print('E0.3 bot B5.8 authoritative debt derivation, concurrent idempotency and ambient denial: OK')
