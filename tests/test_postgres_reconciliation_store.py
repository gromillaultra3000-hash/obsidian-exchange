import os, sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"relay"))
dsn=os.getenv("TEST_POSTGRES_DSN")
if not dsn:
    print("postgres reconciliation store: skipped (TEST_POSTGRES_DSN unset)")
    raise SystemExit(0)
import psycopg
from repositories.reconciliation_store import PostgresReconciliationStore

with psycopg.connect(dsn) as conn:
    conn.execute("CREATE TABLE IF NOT EXISTS orders(order_id BIGINT PRIMARY KEY,user_id BIGINT,"
                 "rub_amount NUMERIC(20,2),status TEXT,paid_btc_tx TEXT,updated_at TIMESTAMPTZ)")
    conn.execute("CREATE TABLE IF NOT EXISTS referrals(referrer_id BIGINT,referred_id BIGINT PRIMARY KEY,"
                 "bonus_paid INTEGER DEFAULT 0,total_bonus_btc NUMERIC(30,12) DEFAULT 0)")
    conn.execute("CREATE TABLE IF NOT EXISTS user_vip_volume(user_id BIGINT PRIMARY KEY,"
                 "total_rub NUMERIC(20,2),updated_at TIMESTAMPTZ)")
    conn.execute("TRUNCATE notification_outbox,payout_reconciliations,"
                 "referral_payout_intents,payout_intents,user_vip_volume,referrals,orders "
                 "RESTART IDENTITY CASCADE")
    conn.execute("INSERT INTO orders(order_id,user_id,rub_amount,status,paid_btc_tx,updated_at,"
                 "crypto_address) VALUES(601,22,10000,'paid',NULL,now(),'dest')")
    conn.execute("INSERT INTO referrals(referrer_id,referred_id,bonus_paid,total_bonus_btc) "
                 "VALUES(11,22,false,0)")
    conn.execute("INSERT INTO payout_intents(order_id,idempotency_key,source,rub_amount,"
                 "crypto_amount,currency,destination,state,txid,finished_at) VALUES"
                 "(601,'payout_601','test',10000,.001,'BTC','dest','succeeded','tx-order',now())")
    conn.execute("INSERT INTO referrals(referrer_id,referred_id,bonus_paid,total_bonus_btc) "
                 "VALUES(7,77,false,.002)")
    conn.execute("INSERT INTO referral_payout_intents(user_id,idempotency_key,crypto_amount,"
                 "destination,state,txid) VALUES(7,'referral_7_1',.002,'refdest','succeeded','tx-ref')")

store=PostgresReconciliationStore(dsn)
assert store.pending_orders()==[{"order_id":601,"rub_amount":10000.0}]
assert store.reconcile_order(601,btc_rate=10_000_000,
                             commission_percent=10,referral_percent=10)["action"]=="reconciled"
assert store.reconcile_order(601,btc_rate=10_000_000,
                             commission_percent=10,referral_percent=10)["action"]=="already_reconciled"
assert store.reconcile_referral()["txid"]=="tx-ref"
first=store.claim_notification(); assert first and store.retry_notification(first["id"])
again=store.claim_notification(); assert again["attempts"]==2
assert store.mark_notification_sent(again["id"])
last=store.claim_notification(); assert last and store.mark_notification_sent(last["id"])
assert store.claim_notification() is None
with psycopg.connect(dsn) as conn:
    assert conn.execute("SELECT status,paid_btc_tx FROM orders WHERE order_id=601").fetchone()==("sent","tx-order")
    assert float(conn.execute("SELECT total_bonus_btc FROM referrals WHERE referrer_id=7").fetchone()[0])==0
    assert conn.execute("SELECT count(*) FROM notification_outbox WHERE state='sent'").fetchone()[0]==2
print("postgres reconciliation repository checks: OK")
