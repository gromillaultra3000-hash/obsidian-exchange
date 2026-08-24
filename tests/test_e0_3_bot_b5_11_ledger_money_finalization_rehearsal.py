import os
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path

dsn=os.getenv('TEST_POSTGRES_DSN')
if not dsn: print('E0.3 bot B5.11 ledger money finalization: skipped');raise SystemExit(0)
import psycopg
from psycopg.conninfo import conninfo_to_dict,make_conninfo
ROOT=Path(__file__).resolve().parents[1]
with psycopg.connect(dsn) as c:
 c.execute("CREATE TABLE blocked_users(user_id bigint PRIMARY KEY,reason text NOT NULL,blocked_at timestamptz NOT NULL DEFAULT now());CREATE TABLE orders(order_id bigint PRIMARY KEY,user_id bigint NOT NULL,created_at timestamptz NOT NULL DEFAULT now(),currency text NOT NULL DEFAULT 'BTC',rub_amount numeric(20,2) NOT NULL,status text NOT NULL,crypto_address text,paid_btc_tx text,receipt_sent_at timestamptz,updated_at timestamptz NOT NULL DEFAULT now(),network text);CREATE TABLE sent_notifications(order_id bigint,event text,PRIMARY KEY(order_id,event));CREATE TABLE reserves(currency text PRIMARY KEY,amount numeric,updated_at timestamptz NOT NULL DEFAULT now());CREATE TABLE referrals(referrer_id bigint NOT NULL,referred_id bigint PRIMARY KEY,total_bonus_btc numeric(30,12) NOT NULL DEFAULT 0,bonus_paid boolean NOT NULL DEFAULT false);CREATE TABLE user_vip_volume(user_id bigint PRIMARY KEY,total_rub numeric(20,2) NOT NULL,updated_at timestamptz NOT NULL DEFAULT now());CREATE TABLE sell_orders(id bigint PRIMARY KEY,user_id bigint NOT NULL,currency text NOT NULL DEFAULT 'BTC',rub_amount numeric(20,2) NOT NULL,status text NOT NULL,sbp_phone text NOT NULL DEFAULT '',payout_bank text,payout_details text,payout_name text,payout_provider text,payout_ref text,payout_status text,updated_at timestamptz NOT NULL DEFAULT now());")
 c.execute((ROOT/'deploy/postgres/001_payout_core.sql').read_text())
 c.execute((ROOT/'deploy/postgres/009_swap_sessions.sql').read_text())
 c.execute((ROOT/'deploy/postgres/022_sell_settlement.sql').read_text())
 c.execute("INSERT INTO orders(order_id,user_id,rub_amount,status) VALUES(1,10,100000,'paid');INSERT INTO referrals VALUES(20,10,0,false),(30,31,0.4,false),(30,32,0.6,false),(50,51,0,false);INSERT INTO payout_intents(order_id,idempotency_key,state,source,rub_amount,crypto_amount,currency,network,destination,txid) VALUES(1,'p1','succeeded','x',100000,0.1,'BTC','BTC','a','tx-order');INSERT INTO sell_orders(id,user_id,rub_amount,status,sbp_phone,payout_bank,payout_details,payout_name,payout_provider) VALUES(1,40,5000,'paying','+7000','bank','acct','name','vertu');INSERT INTO swap_sessions(session_token,user_id,coin_from,coin_to,amount_from,address_to,status) VALUES('swap-1',51,'BTC','LTC',0.01,'x','finished')")
 c.execute((ROOT/'deploy/postgres/proposals/035_e0_bot_b1_role_envelope.sql').read_text())
 c.execute((ROOT/'deploy/postgres/proposals/055_e0_bot_b5_10_chain_evidence_transitions.sql').read_text())
 c.execute((ROOT/'deploy/postgres/proposals/056_e0_bot_b5_11_ledger_money_finalization.sql').read_text())
 c.execute((ROOT/'deploy/postgres/proposals/057_e0_bot_b5_11_source_reservations_and_manual_evidence.sql').read_text())
 c.execute("INSERT INTO payout_chain_evidence(evidence_id,debt_kind,debt_id,result,txid,network,destination,crypto_amount,finality,observed_at,consumed_at) VALUES('eo','ORDER',1,'CONFIRMED','tx-order','BTC','a',0.1,6,now(),now());INSERT INTO order_value_terms VALUES(1,'terms-1',10,5,5000000,now());INSERT INTO sell_payment_evidence(evidence_id,sell_id,user_id,provider,payout_ref,destination_digest,currency,rub_amount,result,observed_at) VALUES('sell-e',1,40,'vertu','pay-ref',md5(jsonb_build_array('+7000','bank','acct','name')::text),'RUB',5000,'CONFIRMED',now());INSERT INTO engagement_credit_ledger(source_kind,source_id,credit_kind,beneficiary_id,referred_id,amount,terms_snapshot) VALUES('LEGACY','l1','REFERRAL_BTC',30,31,0.4,'{}'),('LEGACY','l2','REFERRAL_BTC',30,32,0.6,'{}');INSERT INTO swap_value_evidence(evidence_id,session_token,user_id,coin_from,amount_from,rub_value,btc_rub_rate,commission_percent,referral_percent,result,observed_at) VALUES('swap-e','swap-1',51,'BTC',0.01,50000,5000000,10,5,'CONFIRMED',now())")
parts=conninfo_to_dict(dsn);parts.update(user='obsidian_exchange_bot',password='synthetic-rehearsal-only');bot=make_conninfo(**parts)
def call(sql):
 with psycopg.connect(bot) as c:return c.execute(sql).fetchone()[0]
assert call("SELECT bot_b5_finalize_order_money(1,'wrong-terms')")=='not_ready'
assert call("SELECT bot_b5_finalize_sell_money(1,'missing-evidence')")=='evidence_conflict'
assert call("SELECT bot_b5_finalize_swap_referral('swap-1','missing-evidence')")=='evidence_conflict'
with ThreadPoolExecutor(max_workers=8) as p: order=list(p.map(lambda _:call("SELECT bot_b5_finalize_order_money(1,'terms-1')"),range(8)))
assert order.count('reconciled')==1 and order.count('already_reconciled')==7
with psycopg.connect(dsn) as c:c.execute("UPDATE notification_outbox SET recipient_id=999 WHERE topic='payout_sent' AND aggregate_id='1'")
must_replay_error=False
try:call("SELECT bot_b5_finalize_order_money(1,'terms-1')")
except psycopg.Error:must_replay_error=True
assert must_replay_error
with psycopg.connect(dsn) as c:c.execute("UPDATE notification_outbox SET recipient_id=10 WHERE topic='payout_sent' AND aggregate_id='1'")
ref_intent=call("SELECT (bot_b5_request_referral_payout(30,'r',0.5)->>'id')::bigint")
with psycopg.connect(dsn) as c:
 c.execute("UPDATE referral_payout_intents SET state='succeeded',txid='tx-ref' WHERE id=%s",(ref_intent,))
 c.execute("INSERT INTO payout_chain_evidence(evidence_id,debt_kind,debt_id,result,txid,network,destination,crypto_amount,finality,observed_at,consumed_at) VALUES('er','REFERRAL',%s,'CONFIRMED','tx-ref',NULL,'r',1,6,now(),now())",(ref_intent,))
 c.execute("INSERT INTO engagement_credit_ledger(source_kind,source_id,credit_kind,beneficiary_id,referred_id,amount,terms_snapshot) VALUES('LEGACY','late','REFERRAL_BTC',30,31,0.25,'{}');UPDATE referrals SET total_bonus_btc=total_bonus_btc+0.25 WHERE referrer_id=30 AND referred_id=31")
with ThreadPoolExecutor(max_workers=8) as p: referral=list(p.map(lambda _:call("SELECT bot_b5_finalize_referral_money(1)"),range(8)))
assert referral.count('reconciled')==1 and referral.count('already_reconciled')==7
assert call("SELECT bot_b5_sell_record_processing(1,'vertu')") is True
with ThreadPoolExecutor(max_workers=8) as p: sell=list(p.map(lambda _:call("SELECT bot_b5_finalize_sell_money(1,'sell-e')"),range(8)))
assert sell.count('settled')==1 and sell.count('already_settled')==7
with psycopg.connect(dsn) as c:c.execute("UPDATE bot_sell_finalization_outbox SET rub_amount=1 WHERE sell_id=1")
try:call("SELECT bot_b5_finalize_sell_money(1,'sell-e')")
except psycopg.Error:pass
else:raise AssertionError('sell replay corruption accepted')
with psycopg.connect(dsn) as c:c.execute("UPDATE bot_sell_finalization_outbox SET rub_amount=5000 WHERE sell_id=1")
with psycopg.connect(dsn) as c:
 assert c.execute("SELECT status,paid_btc_tx FROM orders WHERE order_id=1").fetchone()==('sent','tx-order')
 assert c.execute("SELECT total_rub FROM user_vip_volume WHERE user_id=10").fetchone()==(100000,)
 assert c.execute("SELECT count(*) FROM engagement_credit_ledger").fetchone()==(6,)
 assert c.execute("SELECT state FROM referral_payout_intents WHERE id=1").fetchone()==('reconciled',)
 assert c.execute("SELECT sum(total_bonus_btc) FROM referrals WHERE referrer_id=30").fetchone()==(Decimal('0.250000000000'),)
 assert c.execute("SELECT status,payout_ref FROM sell_orders WHERE id=1").fetchone()==('paid','pay-ref')
 assert c.execute("SELECT count(*) FROM notification_outbox").fetchone()==(2,)
 assert c.execute("SELECT count(*) FROM bot_sell_finalization_outbox").fetchone()==(1,)
with psycopg.connect(bot) as c:
 for sql in ("INSERT INTO order_value_terms VALUES(9,'fake',1,1,1,now())","INSERT INTO sell_payment_evidence(evidence_id,sell_id,user_id,provider,payout_ref,destination_digest,currency,rub_amount,result,observed_at) VALUES('fake',9,9,'vertu','x','00000000000000000000000000000000','RUB',1,'CONFIRMED',now())","UPDATE user_vip_volume SET total_rub=999"):
  try:c.execute(sql)
  except psycopg.Error:c.rollback()
  else:raise AssertionError('raw bot access unexpectedly allowed')
with ThreadPoolExecutor(max_workers=8) as p: swap=list(p.map(lambda _:call("SELECT bot_b5_finalize_swap_referral('swap-1','swap-e')"),range(8)))
assert swap.count('credited')==1 and swap.count('already_credited')==7
with psycopg.connect(dsn) as c:c.execute("UPDATE engagement_credit_ledger SET amount=amount+1 WHERE source_kind='SWAP' AND source_id='swap-1'")
try:call("SELECT bot_b5_finalize_swap_referral('swap-1','swap-e')")
except psycopg.Error:pass
else:raise AssertionError('swap replay corruption accepted')
with psycopg.connect(dsn) as c:c.execute("UPDATE engagement_credit_ledger SET amount=amount-1 WHERE source_kind='SWAP' AND source_id='swap-1'")
with psycopg.connect(dsn) as c:
 c.execute("INSERT INTO sell_orders(id,user_id,rub_amount,status,sbp_phone,payout_bank,payout_details,payout_name,payout_provider) VALUES(2,41,10,'paying','+7111','bank2','acct2','name2','manual');INSERT INTO sell_payment_evidence(evidence_id,sell_id,user_id,provider,payout_ref,destination_digest,currency,rub_amount,result,observed_at) VALUES('manual-e',2,41,'manual','m',md5(jsonb_build_array('+7111','bank2','acct2','name2')::text),'RUB',10,'CONFIRMED',now());INSERT INTO orders(order_id,user_id,rub_amount,status) VALUES(2,99,1,'paid');INSERT INTO payout_intents(order_id,idempotency_key,state,source,rub_amount,crypto_amount,currency,destination) VALUES(2,'p2','review','x',1,0.01,'BTC','z');INSERT INTO payout_hold_evidence(evidence_id,order_id,reason,observed_at) VALUES('hold-e',2,'provider outcome unknown',now())")
with ThreadPoolExecutor(max_workers=8) as p: manual=list(p.map(lambda _:call("SELECT bot_b5_finalize_sell_money(2,'manual-e')"),range(8)))
assert manual.count('settled')==1 and manual.count('already_settled')==7
with ThreadPoolExecutor(max_workers=8) as p: held=list(p.map(lambda _:call("SELECT bot_b5_record_payout_hold(2,'hold-e')"),range(8)))
assert sum(held)==1
def must_fail(sql):
 try:call(sql)
 except psycopg.Error:return
 raise AssertionError('injected fault did not abort')
with psycopg.connect(dsn) as c:
 c.execute("INSERT INTO orders(order_id,user_id,rub_amount,status) VALUES(3,80,100,'paid');INSERT INTO payout_intents(order_id,idempotency_key,state,source,rub_amount,crypto_amount,currency,destination,txid) VALUES(3,'p3','succeeded','x',100,0.01,'BTC','o3','tx3');INSERT INTO payout_chain_evidence(evidence_id,debt_kind,debt_id,result,txid,destination,crypto_amount,finality,observed_at,consumed_at) VALUES('eo3','ORDER',3,'CONFIRMED','tx3','o3',0.01,1,now(),now());INSERT INTO order_value_terms VALUES(3,'terms-3',1,1,5000000,now());CREATE FUNCTION fail_order_outbox() RETURNS trigger LANGUAGE plpgsql AS $$BEGIN IF NEW.topic='payout_sent' AND NEW.aggregate_id='3' THEN RAISE EXCEPTION 'injected_order_outbox';END IF;RETURN NEW;END$$;CREATE TRIGGER fail_order_outbox BEFORE INSERT ON notification_outbox FOR EACH ROW EXECUTE FUNCTION fail_order_outbox()")
must_fail("SELECT bot_b5_finalize_order_money(3,'terms-3')")
with psycopg.connect(dsn) as c:
 assert c.execute("SELECT status FROM orders WHERE order_id=3").fetchone()==('paid',)
 assert c.execute("SELECT count(*) FROM payout_reconciliations WHERE order_id=3").fetchone()==(0,)
 assert c.execute("SELECT count(*) FROM engagement_credit_ledger WHERE source_kind='ORDER' AND source_id='3'").fetchone()==(0,)
 c.execute("DROP TRIGGER fail_order_outbox ON notification_outbox;DROP FUNCTION fail_order_outbox()")
 c.execute("INSERT INTO referrals VALUES(60,61,0.2,false);INSERT INTO engagement_credit_ledger(source_kind,source_id,credit_kind,beneficiary_id,referred_id,amount,terms_snapshot) VALUES('LEGACY','rf','REFERRAL_BTC',60,61,0.2,'{}')")
ref_fault=call("SELECT (bot_b5_request_referral_payout(60,'rf',0.1)->>'id')::bigint")
with psycopg.connect(dsn) as c:
 c.execute("UPDATE referral_payout_intents SET state='succeeded',txid='tx-rf' WHERE id=%s",(ref_fault,));c.execute("INSERT INTO payout_chain_evidence(evidence_id,debt_kind,debt_id,result,txid,destination,crypto_amount,finality,observed_at,consumed_at) VALUES('erf','REFERRAL',%s,'CONFIRMED','tx-rf','rf',0.2,1,now(),now())",(ref_fault,));c.execute("CREATE FUNCTION fail_ref_outbox() RETURNS trigger LANGUAGE plpgsql AS $$BEGIN IF NEW.topic='referral_payout_sent' THEN RAISE EXCEPTION 'injected_ref_outbox';END IF;RETURN NEW;END$$;CREATE TRIGGER fail_ref_outbox BEFORE INSERT ON notification_outbox FOR EACH ROW EXECUTE FUNCTION fail_ref_outbox()")
must_fail(f"SELECT bot_b5_finalize_referral_money({ref_fault})")
with psycopg.connect(dsn) as c:
 assert c.execute("SELECT state FROM referral_payout_intents WHERE id=%s",(ref_fault,)).fetchone()==('succeeded',)
 assert c.execute("SELECT total_bonus_btc FROM referrals WHERE referrer_id=60").fetchone()==(Decimal('0.200000000000'),)
 assert c.execute("SELECT count(*) FROM referral_payout_debit_ledger WHERE intent_id=%s",(ref_fault,)).fetchone()==(0,)
 assert c.execute("SELECT count(*) FROM referral_credit_reservations WHERE intent_id=%s AND consumed_at IS NOT NULL",(ref_fault,)).fetchone()==(0,)
 c.execute("DROP TRIGGER fail_ref_outbox ON notification_outbox;DROP FUNCTION fail_ref_outbox()")
 c.execute("INSERT INTO referrals VALUES(70,71,0,false);INSERT INTO swap_sessions(session_token,user_id,coin_from,coin_to,amount_from,address_to,status) VALUES('swap-f',71,'BTC','LTC',0.02,'x','finished');INSERT INTO swap_value_evidence(evidence_id,session_token,user_id,coin_from,amount_from,rub_value,btc_rub_rate,commission_percent,referral_percent,result,observed_at) VALUES('swap-fe','swap-f',71,'BTC',0.02,1000,5000000,10,5,'CONFIRMED',now());CREATE FUNCTION fail_swap_credit() RETURNS trigger LANGUAGE plpgsql AS $$BEGIN IF NEW.source_kind='SWAP' AND NEW.source_id='swap-f' THEN RAISE EXCEPTION 'injected_swap_credit';END IF;RETURN NEW;END$$;CREATE TRIGGER fail_swap_credit BEFORE INSERT ON engagement_credit_ledger FOR EACH ROW EXECUTE FUNCTION fail_swap_credit()")
must_fail("SELECT bot_b5_finalize_swap_referral('swap-f','swap-fe')")
with psycopg.connect(dsn) as c:
 assert c.execute("SELECT consumed_at FROM swap_value_evidence WHERE evidence_id='swap-fe'").fetchone()==(None,)
 assert c.execute("SELECT total_bonus_btc FROM referrals WHERE referrer_id=70").fetchone()==(Decimal('0E-12'),)
 c.execute("DROP TRIGGER fail_swap_credit ON engagement_credit_ledger;DROP FUNCTION fail_swap_credit()")
 c.execute("INSERT INTO sell_orders(id,user_id,rub_amount,status,sbp_phone,payout_bank,payout_details,payout_name,payout_provider) VALUES(3,42,20,'paying','+7222','','','','manual');INSERT INTO sell_payment_evidence(evidence_id,sell_id,user_id,provider,payout_ref,destination_digest,currency,rub_amount,result,observed_at) VALUES('sell-fe',3,42,'manual','mf',md5(jsonb_build_array('+7222','','','')::text),'RUB',20,'CONFIRMED',now());CREATE FUNCTION fail_sell_outbox() RETURNS trigger LANGUAGE plpgsql AS $$BEGIN IF NEW.sell_id=3 THEN RAISE EXCEPTION 'injected_sell_outbox';END IF;RETURN NEW;END$$;CREATE TRIGGER fail_sell_outbox BEFORE INSERT ON bot_sell_finalization_outbox FOR EACH ROW EXECUTE FUNCTION fail_sell_outbox()")
must_fail("SELECT bot_b5_finalize_sell_money(3,'sell-fe')")
with psycopg.connect(dsn) as c:
 assert c.execute("SELECT status FROM sell_orders WHERE id=3").fetchone()==('paying',)
 assert c.execute("SELECT consumed_at FROM sell_payment_evidence WHERE evidence_id='sell-fe'").fetchone()==(None,)
 assert c.execute("SELECT count(*) FROM bot_sell_finalization_ledger WHERE sell_id=3").fetchone()==(0,)
 c.execute("DROP TRIGGER fail_sell_outbox ON bot_sell_finalization_outbox;DROP FUNCTION fail_sell_outbox()")
with psycopg.connect(dsn) as c:
 assert c.execute("SELECT count(*) FROM payout_intent_audit WHERE order_id=2 AND action='hold' AND evidence='hold-e'").fetchone()==(1,)
 assert c.execute("SELECT status FROM sell_orders WHERE id=2").fetchone()==('paid',)
 signatures=['bot_b5_finalize_order_money(bigint,text)','bot_b5_request_referral_payout(bigint,text,numeric)','bot_b5_finalize_referral_money(bigint)','bot_b5_finalize_swap_referral(text,text)','bot_b5_sell_record_processing(bigint,text)','bot_b5_finalize_sell_money(bigint,text)','bot_b5_record_payout_hold(bigint,text)']
 for signature in signatures:
  row=c.execute("SELECT p.prosecdef,r.rolname,p.proconfig,has_function_privilege('obsidian_exchange_bot',p.oid,'EXECUTE'),has_function_privilege('public',p.oid,'EXECUTE') FROM pg_proc p JOIN pg_roles r ON r.oid=p.proowner WHERE p.oid=to_regprocedure(%s)",(signature,)).fetchone()
  assert row==(True,'obsidian_exchange_bot_owner',['search_path=pg_catalog'],True,False)
 assert c.execute("SELECT count(*) FROM information_schema.role_table_grants WHERE grantee='obsidian_exchange_bot'").fetchone()==(0,)
 assert c.execute("SELECT count(*) FROM information_schema.role_usage_grants WHERE grantee='obsidian_exchange_bot'").fetchone()==(0,)
 try:c.execute("INSERT INTO order_value_terms VALUES(9,'nan',1,1,'NaN',now())")
 except psycopg.errors.CheckViolation:c.rollback()
 else:raise AssertionError('NaN terms accepted')
print('E0.3 bot B5.11 source-bound order/referral/swap/sell ledgers, reservations and atomic projections: OK')
