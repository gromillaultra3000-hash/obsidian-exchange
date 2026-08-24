import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "relay"))
from core import payout_intents as pi
from core import payout_reconciliation as pr


def db():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE orders(order_id INTEGER PRIMARY KEY,user_id INTEGER,rub_amount REAL,status TEXT,paid_btc_tx TEXT,updated_at TEXT)")
    conn.execute("CREATE TABLE referrals(referrer_id INTEGER,referred_id INTEGER PRIMARY KEY,bonus_paid INTEGER DEFAULT 0,total_bonus_btc REAL DEFAULT 0)")
    conn.execute("CREATE TABLE user_vip_volume(user_id INTEGER PRIMARY KEY,total_rub REAL,updated_at TEXT)")
    pi.ensure_schema(conn)
    pr.ensure_schema(conn)
    return conn


def succeeded(conn, order_id=1):
    conn.execute("INSERT INTO orders VALUES (?,?,?,?,?,NULL)", (order_id, 22, 10000, "paid", None))
    pi.create(conn, order_id=order_id, rub_amount=10000, crypto_amount=.001,
              currency="BTC", network=None, destination="bc1qdest", source="test")
    assert pi.claim(conn, order_id)
    assert pi.succeed(conn, order_id, "a" * 64)


def test_reconciles_all_effects_exactly_once():
    conn = db()
    succeeded(conn)
    conn.execute("INSERT INTO referrals VALUES (11,22,0,0)")
    first = pr.reconcile_succeeded(conn, 1, btc_rate=10_000_000,
                                   commission_percent=10, referral_percent=10)
    second = pr.reconcile_succeeded(conn, 1, btc_rate=10_000_000,
                                    commission_percent=10, referral_percent=10)
    assert first["action"] == "reconciled"
    assert second["action"] == "already_reconciled"
    assert conn.execute("SELECT status,paid_btc_tx FROM orders").fetchone() == ("sent", "a" * 64)
    assert conn.execute("SELECT total_rub FROM user_vip_volume").fetchone()[0] == 10000
    assert conn.execute("SELECT total_bonus_btc FROM referrals").fetchone()[0] == .00001
    out = conn.execute("SELECT recipient_id,payload FROM notification_outbox").fetchone()
    assert out[0] == 22 and json.loads(out[1])["order_id"] == 1


def test_missing_rate_rolls_back_without_partial_effects():
    conn = db()
    succeeded(conn)
    conn.execute("INSERT INTO referrals VALUES (11,22,0,0)")
    try:
        with conn:
            pr.reconcile_succeeded(conn, 1, btc_rate=None,
                                   commission_percent=10, referral_percent=10)
    except ValueError:
        pass
    else:
        raise AssertionError("missing rate must fail closed")
    assert conn.execute("SELECT status FROM orders").fetchone()[0] == "paid"
    assert conn.execute("SELECT COUNT(*) FROM payout_reconciliations").fetchone()[0] == 0


def test_outbox_claim_retry_and_complete():
    conn = db()
    succeeded(conn)
    pr.reconcile_succeeded(conn, 1, btc_rate=None, commission_percent=10,
                           referral_percent=10)
    item = pr.claim_notification(conn)
    assert item and item["attempts"] == 1
    assert pr.retry_notification(conn, item["id"])
    item = pr.claim_notification(conn)
    assert item["attempts"] == 2
    assert pr.mark_notification_sent(conn, item["id"])
    assert pr.claim_notification(conn) is None


if __name__ == "__main__":
    test_reconciles_all_effects_exactly_once()
    test_missing_rate_rolls_back_without_partial_effects()
    test_outbox_claim_retry_and_complete()
    print("payout reconciliation tests: OK")
