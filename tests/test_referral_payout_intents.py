import os, sqlite3, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "relay"))
from core import referral_payout_intents as rpi

with open(os.path.join(ROOT, "relay", "core", "referral_payout_intents.py"),
          encoding="utf-8") as source_file:
    CORE_SOURCE = source_file.read()
with open(os.path.join(ROOT, "relay", "repositories", "payout_store.py"),
          encoding="utf-8") as source_file:
    STORE_SOURCE = source_file.read()
assert ".execute(" not in CORE_SOURCE and ".executescript(" not in CORE_SOURCE
assert "from core import referral_payout_intents" not in STORE_SOURCE
assert "from core import db_runtime, referral_payout_intents" not in STORE_SOURCE


with tempfile.TemporaryDirectory() as td:
    db = os.path.join(td, "referral.db")
    with sqlite3.connect(db) as conn:
        conn.executescript(open(os.path.join(ROOT, "deploy", "sqlite", "001_payout_core.sql"), encoding="utf-8").read())
        conn.executescript(open(os.path.join(ROOT, "deploy", "sqlite", "019_reconciliation.sql"), encoding="utf-8").read())
        conn.execute("CREATE TABLE referrals(referrer_id INTEGER,referred_id INTEGER,"
                     "total_bonus_btc REAL,bonus_paid INTEGER DEFAULT 0)")
        conn.executemany("INSERT INTO referrals VALUES(?,?,?,0)",
                         [(7, 10, .00003), (7, 11, .00002)])
        first = rpi.create(conn, user_id=7, destination="btc-address", minimum_btc=.00001)
        again = rpi.create(conn, user_id=7, destination="changed", minimum_btc=.00001)
        assert first["id"] == again["id"] and first["destination"] == "btc-address"
        conn.commit()
    with sqlite3.connect(db) as conn:
        claimed = rpi.claim_next(conn)
        assert claimed["intent_type"] == "referral" and claimed["order_id"] is None
        assert rpi.succeed(conn, claimed["id"], "tx-ref")
        conn.commit()
    with sqlite3.connect(db) as conn:
        row = rpi.reconcile_next(conn)
        assert row["txid"] == "tx-ref"
        assert abs(conn.execute("SELECT SUM(total_bonus_btc) FROM referrals").fetchone()[0]) < 1e-12
        assert rpi.reconcile_next(conn) is None
        outbox = conn.execute("SELECT topic,recipient_id FROM notification_outbox").fetchone()
        assert outbox == ("referral_payout_sent", 7)
        conn.commit()

print("referral payout intent checks: OK")

conn = sqlite3.connect(":memory:")
conn.executescript(open(os.path.join(ROOT, "deploy", "sqlite", "001_payout_core.sql"), encoding="utf-8").read())
conn.execute("CREATE TABLE referrals(referrer_id INTEGER,referred_id INTEGER,"
             "total_bonus_btc REAL,bonus_paid INTEGER DEFAULT 0)")
conn.execute("INSERT INTO referrals VALUES(9,10,.001,0)")
intent = rpi.create(conn, user_id=9, destination="dest", minimum_btc=.0001)
assert rpi.claim_next(conn)
assert rpi.review(conn, intent["id"], "TimeoutError")
assert rpi.admin_requeue_absent(conn, intent["id"], actor=1, evidence="ledger absent")
assert rpi.get(conn, intent["id"])["state"] == "pending"
assert rpi.claim_next(conn)
assert rpi.review(conn, intent["id"], "TimeoutError")
assert rpi.admin_confirm_txid(conn, intent["id"], "tx-proof", actor=1,
                              evidence="final trusted exact transfer")
assert rpi.get(conn, intent["id"])["state"] == "succeeded"
assert conn.execute("SELECT COUNT(*) FROM referral_payout_intent_audit").fetchone()[0] == 2
print("referral admin review checks: OK")
