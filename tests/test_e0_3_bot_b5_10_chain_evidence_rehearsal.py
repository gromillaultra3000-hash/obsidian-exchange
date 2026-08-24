import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
dsn=os.getenv('TEST_POSTGRES_DSN')
if not dsn:print('E0.3 bot B5.10 chain evidence: skipped');raise SystemExit(0)
import psycopg
from psycopg.conninfo import conninfo_to_dict,make_conninfo
ROOT=Path(__file__).resolve().parents[1]
with psycopg.connect(dsn) as c:
 c.execute("CREATE TABLE blocked_users(user_id bigint PRIMARY KEY,reason text NOT NULL,blocked_at timestamptz NOT NULL DEFAULT now());CREATE TABLE orders(order_id bigint PRIMARY KEY,user_id bigint NOT NULL,created_at timestamptz NOT NULL DEFAULT now(),currency text NOT NULL DEFAULT 'BTC',rub_amount numeric NOT NULL DEFAULT 1,status text NOT NULL,crypto_address text,paid_btc_tx text,receipt_sent_at timestamptz,updated_at timestamptz,network text);CREATE TABLE sent_notifications(order_id bigint,event text,PRIMARY KEY(order_id,event));CREATE TABLE reserves(currency text PRIMARY KEY,amount numeric,updated_at timestamptz NOT NULL DEFAULT now())")
 c.execute((ROOT/'deploy/postgres/001_payout_core.sql').read_text());c.execute("INSERT INTO payout_intents(order_id,idempotency_key,state,source,rub_amount,crypto_amount,currency,network,destination) VALUES(1,'p1','processing','x',100,0.1,'BTC','BTC','addr'),(2,'p2','review','x',100,0.2,'BTC','BTC','addr2');INSERT INTO referral_payout_intents(user_id,idempotency_key,state,crypto_amount,currency,network,destination) VALUES(7,'r1','processing',0.3,'BTC','BTC','raddr'),(8,'r2','review',0.4,'BTC','BTC','raddr2')")
 c.execute((ROOT/'deploy/postgres/proposals/035_e0_bot_b1_role_envelope.sql').read_text());c.execute((ROOT/'deploy/postgres/proposals/055_e0_bot_b5_10_chain_evidence_transitions.sql').read_text())
 c.execute("INSERT INTO payout_chain_evidence(evidence_id,debt_kind,debt_id,result,txid,network,destination,crypto_amount,finality,observed_at) VALUES('eo','ORDER',1,'CONFIRMED','tx1','BTC','addr',0.1,6,now()),('er','REFERRAL',1,'CONFIRMED','tx2','BTC','raddr',0.3,6,now()),('no','ORDER',2,'NOT_STARTED',NULL,NULL,NULL,NULL,NULL,now()),('nr','REFERRAL',2,'NOT_STARTED',NULL,NULL,NULL,NULL,NULL,now())")
parts=conninfo_to_dict(dsn);parts.update(user='obsidian_exchange_bot',password='synthetic-rehearsal-only');bot=make_conninfo(**parts)
def call(sql):
 with psycopg.connect(bot) as c:return c.execute(sql).fetchone()[0]
with ThreadPoolExecutor(max_workers=8) as p:r=list(p.map(lambda _:call("SELECT bot_b5_confirm_order_evidence(1,'eo')"),range(8)))
assert sum(r)==1
assert call("SELECT bot_b5_confirm_referral_evidence(1,'er')") is True
assert call("SELECT bot_b5_requeue_order_not_started(2,'no')") is True
assert call("SELECT bot_b5_requeue_referral_not_started(2,'nr')") is True
with psycopg.connect(bot) as c:
 try:c.execute("INSERT INTO payout_chain_evidence(evidence_id,debt_kind,debt_id,result,txid,network,destination,crypto_amount,finality,observed_at) VALUES('fake','ORDER',9,'CONFIRMED','x','BTC','x',1,1,now())")
 except psycopg.Error:pass
 else:raise AssertionError('bot fabricated evidence')
with psycopg.connect(dsn) as c:
 assert c.execute("SELECT state,txid FROM payout_intents ORDER BY order_id").fetchall()==[('succeeded','tx1'),('pending',None)]
 assert c.execute("SELECT state,txid FROM referral_payout_intents ORDER BY id").fetchall()==[('succeeded','tx2'),('pending',None)]
 assert c.execute('SELECT count(*) FROM payout_chain_evidence WHERE consumed_at IS NOT NULL').fetchone()==(4,)
 assert c.execute('SELECT count(*) FROM payout_intent_audit').fetchone()==(2,)
print('E0.3 bot B5.10 principal-owned evidence, global TXID identity, consume-once transitions: OK')
