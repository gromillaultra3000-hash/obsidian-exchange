import json, os, sqlite3, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "relay"))
from core import payout_intents, referral_payout_intents
from repositories.reconciliation_store import SQLiteReconciliationStore, ensure_sqlite_schema

with tempfile.TemporaryDirectory() as td:
    path = str(Path(td) / "reconcile.db")
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE orders(order_id INTEGER PRIMARY KEY,user_id INTEGER,"
                 "rub_amount REAL,status TEXT,paid_btc_tx TEXT,updated_at TEXT)")
    conn.execute("CREATE TABLE referrals(referrer_id INTEGER,referred_id INTEGER PRIMARY KEY,"
                 "bonus_paid INTEGER DEFAULT 0,total_bonus_btc REAL DEFAULT 0)")
    conn.execute("CREATE TABLE user_vip_volume(user_id INTEGER PRIMARY KEY,total_rub REAL,updated_at TEXT)")
    conn.executescript((ROOT / "deploy/sqlite/001_payout_core.sql").read_text())
    conn.executescript((ROOT / "deploy/sqlite/019_reconciliation.sql").read_text())
    conn.execute("INSERT INTO orders VALUES(1,22,10000,'paid',NULL,NULL)")
    conn.execute("INSERT INTO referrals VALUES(11,22,0,0)")
    payout_intents.create(conn, order_id=1, rub_amount=10000, crypto_amount=.001,
                          currency="BTC", network=None, destination="dest", source="test")
    payout_intents.claim(conn, 1); payout_intents.succeed(conn, 1, "tx-order")
    conn.commit(); conn.close()

    store = SQLiteReconciliationStore(path)
    assert store.pending_orders() == [{"order_id": 1, "rub_amount": 10000.0}]
    # A terminal outbox write failure must roll back order/referral/VIP/ledger.
    conn = sqlite3.connect(path)
    ensure_sqlite_schema(conn)
    conn.execute("INSERT INTO notification_outbox(topic,aggregate_id,recipient_id,payload) "
                 "VALUES('payout_sent','1',22,'{}')")
    conn.commit(); conn.close()
    try:
        store.reconcile_order(1, btc_rate=10_000_000,
                              commission_percent=10, referral_percent=10)
        raise AssertionError("duplicate outbox must abort reconciliation")
    except sqlite3.IntegrityError:
        pass
    conn = sqlite3.connect(path)
    assert conn.execute("SELECT status FROM orders WHERE order_id=1").fetchone()[0] == "paid"
    assert conn.execute("SELECT COUNT(*) FROM payout_reconciliations").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM user_vip_volume").fetchone()[0] == 0
    conn.execute("DELETE FROM notification_outbox WHERE topic='payout_sent' AND aggregate_id='1'")
    conn.commit(); conn.close()
    result = store.reconcile_order(1, btc_rate=10_000_000,
                                   commission_percent=10, referral_percent=10)
    assert result["action"] == "reconciled" and store.pending_orders() == []
    item = store.claim_notification()
    assert json.loads(item["payload"])["order_id"] == 1
    assert store.retry_notification(item["id"])
    item = store.claim_notification(); assert item["attempts"] == 2
    assert store.mark_notification_sent(item["id"])

    conn = sqlite3.connect(path)
    conn.execute("INSERT INTO referrals VALUES(7,77,0,.002)")
    ref = referral_payout_intents.create(conn, user_id=7, destination="refdest",
                                         minimum_btc=.001)
    referral_payout_intents.claim_next(conn)
    referral_payout_intents.succeed(conn, ref["id"], "tx-ref")
    conn.commit(); conn.close()
    assert store.reconcile_referral()["txid"] == "tx-ref"
    assert store.reconcile_referral() is None

print("SQLite reconciliation repository checks: OK")
