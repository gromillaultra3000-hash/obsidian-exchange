import os, sys, threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "relay"))

dsn = os.getenv("TEST_POSTGRES_DSN")
if not dsn:
    print("postgres payout store: skipped (TEST_POSTGRES_DSN unset)")
    raise SystemExit(0)

import psycopg
from repositories.payout_store import PostgresPayoutStore

with psycopg.connect(dsn) as conn:
    conn.execute("TRUNCATE payout_reconciliations,payout_intent_audit,payout_intents,"
                 "referral_payout_intent_audit,referral_payout_intents RESTART IDENTITY")
    conn.execute("INSERT INTO payout_intents(order_id,idempotency_key,source,rub_amount,"
                 "crypto_amount,currency,destination) VALUES"
                 "(501,'payout_501','test',1000,.001,'BTC','dest')")
    conn.execute("INSERT INTO referral_payout_intents(user_id,idempotency_key,"
                 "crypto_amount,destination) VALUES(7,'referral_7_1',.002,'refdest')")
    conn.execute("DELETE FROM referrals WHERE referrer_id IN (8,9)")
    conn.execute("INSERT INTO referrals(referrer_id,referred_id,total_bonus_btc) VALUES"
                 "(8,81,.001),(8,82,.002),(9,91,.00001)")

store = PostgresPayoutStore(dsn)
order = store.claim_next()
assert order["intent_type"] == "order" and order["order_id"] == 501
assert store.succeed(order, "tx-order")
referral = store.claim_next()
assert referral["intent_type"] == "referral" and referral["user_id"] == 7
assert referral["order_id"] is None and referral["idempotency_key"] == "referral_7_1"
assert store.review(referral, "TimeoutError")
assert store.claim_next() is None

with psycopg.connect(dsn) as conn:
    conn.execute("INSERT INTO orders(order_id,user_id,rub_amount,crypto_address,status) "
                 "VALUES(502,22,2000,'dest-502','paid'),(503,23,3000,'dest-503','paid') "
                 "ON CONFLICT(order_id) DO NOTHING")

created = store.create_order(order_id=502, rub_amount=2000, crypto_amount=.002,
                             currency="btc", network=None, destination="dest-502",
                             source="test", requested_by="contract")
assert created["idempotency_key"] == "payout_502"
assert store.order_exists(502) and not store.order_exists(999999)
assert store.order(502)["crypto_amount"] == .002
assert store.create_order(order_id=502, rub_amount=2000, crypto_amount=.002,
                          currency="BTC", network=None, destination="dest-502",
                          source="test")["id"] == created["id"]
try:
    store.create_order(order_id=502, rub_amount=2000, crypto_amount=.002,
                       currency="BTC", network=None, destination="changed", source="test")
    raise AssertionError("immutable mismatch was accepted")
except ValueError as exc:
    assert str(exc) == "payout_intent_payload_mismatch"

# PostgreSQL ON CONFLICT + row lock resolves concurrent creation to one debt.
barrier = threading.Barrier(2)
created_ids, create_errors = [], []
def create_same():
    try:
        barrier.wait()
        item = PostgresPayoutStore(dsn).create_order(
            order_id=503, rub_amount=3000, crypto_amount=.003, currency="BTC",
            network=None, destination="dest-503", source="test")
        created_ids.append(item["id"])
    except Exception as exc:
        create_errors.append(exc)
threads = [threading.Thread(target=create_same) for _ in range(2)]
for thread in threads: thread.start()
for thread in threads: thread.join()
assert not create_errors and len(created_ids) == 2 and len(set(created_ids)) == 1, (
    create_errors, created_ids)

intent = store.claim_next()
assert intent["order_id"] == 502 and store.review(intent, "TimeoutError")
items = store.review_items()
assert len(items) == 1 and items[0]["order_id"] == 502
barrier = threading.Barrier(2)
confirmed = []
def confirm_same():
    barrier.wait()
    confirmed.append(PostgresPayoutStore(dsn).confirm_order_txid(
        502, "tx-502", actor=99, evidence="chain final"))
threads = [threading.Thread(target=confirm_same) for _ in range(2)]
for thread in threads: thread.start()
for thread in threads: thread.join()
assert sorted(confirmed) == [False, True]

intent = store.claim_next()
assert intent["order_id"] == 503 and store.review(intent, "TimeoutError")
assert store.requeue_order_absent(503, actor=99, evidence="ledger absent")
assert store.order(503)["state"] == "pending"

# Per-user advisory serialization resolves the first-referral-request race.
barrier = threading.Barrier(2)
referral_ids, referral_errors = [], []
def request_same_referral():
    try:
        barrier.wait()
        item = PostgresPayoutStore(dsn).request_referral(
            user_id=8, destination="ref-destination", minimum_btc=.0001)
        referral_ids.append(item["id"])
    except Exception as exc:
        referral_errors.append(exc)
threads = [threading.Thread(target=request_same_referral) for _ in range(2)]
for thread in threads: thread.start()
for thread in threads: thread.join()
assert not referral_errors and len(referral_ids) == 2 and len(set(referral_ids)) == 1, (
    referral_errors, referral_ids)
referral_id = referral_ids[0]
assert store.referral(referral_id)["crypto_amount"] == .003
assert store.request_referral(user_id=8, destination="ignored-on-retry",
                              minimum_btc=.0001)["id"] == referral_id
try:
    store.request_referral(user_id=9, destination="small", minimum_btc=.0001)
    raise AssertionError("below-minimum referral was accepted")
except ValueError as exc:
    assert str(exc) == "referral_balance_below_minimum"

# Order retry keeps its established priority over the new referral aggregate.
assert store.claim_next()["order_id"] == 503
new_referral = store.claim_next()
assert new_referral["intent_type"] == "referral" and new_referral["id"] == referral_id
assert store.review(new_referral, "TimeoutError")
assert store.referral_review_items()[0]["id"] in (referral["id"], referral_id)

barrier = threading.Barrier(2)
referral_confirmed = []
def confirm_same_referral():
    barrier.wait()
    referral_confirmed.append(PostgresPayoutStore(dsn).confirm_referral_txid(
        referral_id, "tx-ref-8", actor=99, evidence="chain final"))
threads = [threading.Thread(target=confirm_same_referral) for _ in range(2)]
for thread in threads: thread.start()
for thread in threads: thread.join()
assert sorted(referral_confirmed) == [False, True]

# A failed audit write must roll the state transition back.
with psycopg.connect(dsn) as conn:
    conn.execute("UPDATE referral_payout_intents SET state='review' WHERE id=%s",
                 (referral_id,))
    conn.execute("CREATE OR REPLACE FUNCTION reject_referral_audit() RETURNS trigger "
                 "LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'audit rejected'; END $$")
    conn.execute("CREATE TRIGGER reject_referral_audit BEFORE INSERT ON "
                 "referral_payout_intent_audit FOR EACH ROW EXECUTE FUNCTION "
                 "reject_referral_audit()")
try:
    store.requeue_referral_absent(
        referral_id, actor=99, evidence="signer ledger absent")
    raise AssertionError("referral audit failure was ignored")
except psycopg.Error:
    pass
finally:
    with psycopg.connect(dsn) as conn:
        conn.execute("DROP TRIGGER IF EXISTS reject_referral_audit ON "
                     "referral_payout_intent_audit")
        conn.execute("DROP FUNCTION IF EXISTS reject_referral_audit()")
assert store.referral(referral_id)["state"] == "review"

with psycopg.connect(dsn) as conn:
    assert conn.execute("SELECT state,txid FROM payout_intents WHERE order_id=501").fetchone() == (
        "succeeded", "tx-order")
    assert conn.execute("SELECT state,error_code FROM referral_payout_intents WHERE user_id=7").fetchone() == (
        "review", "TimeoutError")
    assert conn.execute("SELECT count(*) FROM payout_intent_audit").fetchone()[0] == 2
    assert conn.execute("SELECT count(*) FROM referral_payout_intent_audit "
                        "WHERE intent_id=%s", (referral_id,)).fetchone()[0] == 1

print("postgres payout repository checks: OK")
