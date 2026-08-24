import sqlite3
import sys
import tempfile
import threading
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "relay"))

from repositories.payout_store import SQLitePayoutStore


core_source = (ROOT / "relay/core/payout_intents.py").read_text("utf-8")
core_tree = ast.parse(core_source)
assert not any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
               and node.func.attr in {"execute", "executemany", "executescript", "cursor"}
               for node in ast.walk(core_tree))
store_source = (ROOT / "relay/repositories/payout_store.py").read_text("utf-8")
store_tree = ast.parse(store_source)
assert not any(
    (isinstance(node, ast.ImportFrom) and node.module == "core"
     and any(alias.name == "payout_intents" for alias in node.names))
    or (isinstance(node, ast.Import)
        and any(alias.name == "core.payout_intents" for alias in node.names))
    for node in ast.walk(store_tree)
)


def payload(order_id=71):
    return dict(order_id=order_id, rub_amount=5000, crypto_amount=.00123456,
                currency="btc", network=None, destination="bc1qexample",
                source="test", requested_by="contract")


with tempfile.TemporaryDirectory() as td:
    path = str(Path(td) / "payout.db")
    with sqlite3.connect(path) as conn:
        conn.executescript((ROOT / "deploy/sqlite/001_payout_core.sql").read_text())
        conn.execute("CREATE TABLE orders(order_id INTEGER PRIMARY KEY,status TEXT)")
        conn.execute("INSERT INTO orders VALUES(71,'paid')")
        conn.execute("CREATE TABLE referrals(referrer_id INTEGER,referred_id INTEGER,"
                     "total_bonus_btc REAL,bonus_paid INTEGER DEFAULT 0,"
                     "PRIMARY KEY(referrer_id,referred_id))")
        conn.executemany("INSERT INTO referrals VALUES(?,?,?,0)",
                         [(8, 81, .001), (8, 82, .002), (9, 91, .00001)])
    store = SQLitePayoutStore(path)

    first = store.create_order(**payload())
    again = store.create_order(**payload())
    assert first["id"] == again["id"]
    assert first["idempotency_key"] == "payout_71"
    assert store.order_exists(71) and not store.order_exists(72)
    assert store.order(71)["destination"] == "bc1qexample"
    try:
        store.create_order(**{**payload(), "destination": "changed"})
        raise AssertionError("immutable mismatch was accepted")
    except ValueError as exc:
        assert str(exc) == "payout_intent_payload_mismatch"

    # Concurrent identical creation resolves to one immutable debt.
    barrier = threading.Barrier(2)
    results, errors = [], []

    def create_same():
        try:
            barrier.wait()
            results.append(SQLitePayoutStore(path).create_order(**payload(72))["id"])
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=create_same) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors and len(results) == 2 and len(set(results)) == 1

    claimed = store.claim_next()
    assert claimed["order_id"] == 71
    assert store.review(claimed, "TimeoutError")
    assert store.review_items() == [{
        "order_id": 71, "state": "review", "currency": "BTC", "network": None,
        "crypto_amount": .00123456, "destination": "bc1qexample", "txid": None,
        "error_code": "TimeoutError", "claimed_at": store.order(71)["claimed_at"],
        "updated_at": store.order(71)["updated_at"], "order_status": "paid",
    }]

    # Two administrators racing the same CAS produce one transition and audit.
    barrier = threading.Barrier(2)
    outcomes = []

    def confirm():
        barrier.wait()
        outcomes.append(SQLitePayoutStore(path).confirm_order_txid(
            71, "tx-71", actor=99, evidence="chain final"))

    threads = [threading.Thread(target=confirm) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(outcomes) == [False, True]
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM payout_intent_audit").fetchone()[0] == 1

    # Audit failure rolls the state transition back atomically.
    second = store.claim_next()
    assert second["order_id"] == 72 and store.review(second, "TimeoutError")
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TRIGGER reject_payout_audit BEFORE INSERT ON payout_intent_audit "
                     "BEGIN SELECT RAISE(ABORT,'audit rejected'); END")
    try:
        store.requeue_order_absent(72, actor=99, evidence="ledger absent")
        raise AssertionError("audit failure was ignored")
    except sqlite3.IntegrityError:
        pass
    assert store.order(72)["state"] == "review"

    # A referral request reserves one immutable aggregate under concurrency.
    barrier = threading.Barrier(2)
    referral_ids, referral_errors = [], []

    def request_same_referral():
        try:
            barrier.wait()
            referral_ids.append(SQLitePayoutStore(path).request_referral(
                user_id=8, destination="ref-destination", minimum_btc=.0001)["id"])
        except Exception as exc:
            referral_errors.append(exc)

    threads = [threading.Thread(target=request_same_referral) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not referral_errors and len(referral_ids) == 2
    assert len(set(referral_ids)) == 1
    referral_id = referral_ids[0]
    assert store.referral(referral_id)["crypto_amount"] == .003
    assert store.request_referral(user_id=8, destination="ignored-on-retry",
                                  minimum_btc=.0001)["id"] == referral_id
    try:
        store.request_referral(user_id=9, destination="small", minimum_btc=.0001)
        raise AssertionError("below-minimum referral was accepted")
    except ValueError as exc:
        assert str(exc) == "referral_balance_below_minimum"

    # Existing order debt remains ahead of referral debt in worker priority.
    store.create_order(**payload(73))
    assert store.claim_next()["order_id"] == 73
    referral = store.claim_next()
    assert referral["intent_type"] == "referral" and referral["id"] == referral_id
    assert store.review(referral, "TimeoutError")
    assert store.referral_review_items()[0]["id"] == referral_id

    barrier = threading.Barrier(2)
    outcomes = []

    def confirm_referral():
        barrier.wait()
        outcomes.append(SQLitePayoutStore(path).confirm_referral_txid(
            referral_id, "tx-ref", actor=99, evidence="chain final"))

    threads = [threading.Thread(target=confirm_referral) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(outcomes) == [False, True]
    with sqlite3.connect(path) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM referral_payout_intent_audit WHERE intent_id=?",
            (referral_id,),
        ).fetchone()[0] == 1

    # Audit insertion failure rolls a referral requeue back as one transaction.
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE referral_payout_intents SET state='review' WHERE id=?",
                     (referral_id,))
        conn.execute("CREATE TRIGGER reject_referral_audit BEFORE INSERT ON "
                     "referral_payout_intent_audit BEGIN SELECT "
                     "RAISE(ABORT,'audit rejected'); END")
    try:
        store.requeue_referral_absent(
            referral_id, actor=99, evidence="signer ledger absent")
        raise AssertionError("referral audit failure was ignored")
    except sqlite3.IntegrityError:
        pass
    assert store.referral(referral_id)["state"] == "review"

print("SQLite payout aggregate checks: OK")
