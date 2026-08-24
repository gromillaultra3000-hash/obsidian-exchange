"""Crash-boundary tests: no external signer or Telegram/network calls."""
import os, sqlite3, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "relay"))
from core import payout_intents as pi
from core import payout_reconciliation as pr
from core import referral_payout_intents as rpi


def order_schema(conn):
    conn.execute("CREATE TABLE orders(order_id INTEGER PRIMARY KEY,user_id INTEGER,"
                 "rub_amount REAL,status TEXT,paid_btc_tx TEXT,updated_at TEXT)")
    conn.execute("CREATE TABLE referrals(referrer_id INTEGER,referred_id INTEGER,"
                 "bonus_paid INTEGER DEFAULT 0,total_bonus_btc REAL DEFAULT 0)")
    conn.execute("CREATE TABLE user_vip_volume(user_id INTEGER PRIMARY KEY,total_rub REAL,updated_at TEXT)")


with tempfile.TemporaryDirectory() as td:
    path = os.path.join(td, "faults.db")
    conn = sqlite3.connect(path)
    order_schema(conn)
    pi.create(conn, order_id=1, rub_amount=1000, crypto_amount=.001,
              currency="BTC", network=None, destination="dest", source="test")
    conn.commit()
    # Crash after durable claim: a new worker must not claim/sign again.
    assert pi.claim_next(conn)["state"] == "processing"
    conn.commit()
    conn.close()
    conn = sqlite3.connect(path)
    assert pi.claim_next(conn) is None
    assert pi.get(conn, 1)["state"] == "processing"
    conn.close()

conn = sqlite3.connect(":memory:")
order_schema(conn)
conn.execute("INSERT INTO orders VALUES(2,22,1000,'paid',NULL,CURRENT_TIMESTAMP)")
conn.execute("INSERT INTO referrals VALUES(11,22,0,0)")
intent = pi.create(conn, order_id=2, rub_amount=1000, crypto_amount=.001,
                   currency="BTC", network=None, destination="dest", source="test")
pi.claim(conn, 2)
pi.succeed(conn, 2, "tx-order")
conn.commit()
# Crash inside reconciliation rolls all ledger effects back, then retry applies once.
conn.execute("BEGIN IMMEDIATE")
assert pr.reconcile_succeeded(conn, 2, btc_rate=10_000_000,
                              commission_percent=10, referral_percent=10)["action"] == "reconciled"
conn.rollback()
assert conn.execute("SELECT status FROM orders WHERE order_id=2").fetchone()[0] == "paid"
conn.execute("BEGIN IMMEDIATE")
assert pr.reconcile_succeeded(conn, 2, btc_rate=10_000_000,
                              commission_percent=10, referral_percent=10)["action"] == "reconciled"
conn.commit()
assert pr.reconcile_succeeded(conn, 2, btc_rate=10_000_000,
                              commission_percent=10, referral_percent=10)["action"] == "already_reconciled"
# Crash after outbox claim leaves explicit sending, never blind duplicate retry.
item = pr.claim_notification(conn)
conn.commit()
assert item and pr.claim_notification(conn) is None
assert conn.execute("SELECT state FROM notification_outbox WHERE id=?", (item["id"],)).fetchone()[0] == "sending"

ref = sqlite3.connect(":memory:")
ref.execute("CREATE TABLE referrals(referrer_id INTEGER,referred_id INTEGER,"
            "total_bonus_btc REAL,bonus_paid INTEGER DEFAULT 0)")
ref.execute("INSERT INTO referrals VALUES(7,8,.002,0)")
ri = rpi.create(ref, user_id=7, destination="dest", minimum_btc=.001)
assert rpi.claim_next(ref)
assert rpi.succeed(ref, ri["id"], "tx-ref")
ref.commit()
ref.execute("BEGIN IMMEDIATE")
assert rpi.reconcile_next(ref)
ref.rollback()
assert ref.execute("SELECT total_bonus_btc FROM referrals").fetchone()[0] == .002
ref.execute("BEGIN IMMEDIATE")
assert rpi.reconcile_next(ref)
ref.commit()
assert rpi.reconcile_next(ref) is None
assert abs(ref.execute("SELECT total_bonus_btc FROM referrals").fetchone()[0]) < 1e-12

print("payout fault-injection checks: OK")
