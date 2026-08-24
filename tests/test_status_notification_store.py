import os
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "relay"))

from repositories.status_notification_store import SQLiteStatusNotificationStore


with tempfile.TemporaryDirectory() as td:
    path = str(Path(td) / "notifications.db")
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE orders(order_id INTEGER PRIMARY KEY,user_id INTEGER,rub_amount REAL,
          crypto_address TEXT,currency TEXT,status TEXT,paid_btc_tx TEXT,network TEXT,
          created_at TEXT DEFAULT CURRENT_TIMESTAMP,updated_at TEXT);
        CREATE TABLE gift_vouchers(id INTEGER PRIMARY KEY,sender_id INTEGER NOT NULL,
          currency TEXT NOT NULL,rub_amount REAL NOT NULL,code TEXT UNIQUE NOT NULL,
          status TEXT NOT NULL,order_id INTEGER);
        CREATE TABLE sent_notifications(order_id INTEGER NOT NULL,event TEXT NOT NULL,
          created_at TEXT DEFAULT CURRENT_TIMESTAMP,PRIMARY KEY(order_id,event));
        INSERT INTO orders(order_id,user_id,rub_amount,crypto_address,currency,status,paid_btc_tx)
          VALUES(1,10,1000,'a','BTC','paid',NULL);
        INSERT INTO orders(order_id,user_id,rub_amount,crypto_address,currency,status,paid_btc_tx)
          VALUES(2,20,2000,'b','LTC','sent','tx2');
        INSERT INTO gift_vouchers VALUES(1,10,'BTC',1000,'GIFT','pending',1);
    """)
    conn.commit()
    conn.close()

    store = SQLiteStatusNotificationStore(path)
    assert [row["order_id"] for row in store.pending("paid")] == [1]
    assert [row["order_id"] for row in store.payout_candidates()] == [1]
    assert store.complete(1, "payout_held") and not store.complete(1, "payout_held")
    assert store.complete(1, "payout_triggered")
    assert store.payout_candidates() == []
    assert store.complete(1, "paid") and not store.complete(1, "paid")
    assert store.pending("paid") == []
    assert [row["order_id"] for row in store.pending("sent")] == [2]
    with sqlite3.connect(path) as check:
        assert check.execute("SELECT status FROM gift_vouchers WHERE id=1").fetchone()[0] == "paid"

os.environ["DATABASE_URL"] = "postgresql://example.invalid/db"
try:
    from repositories.status_notification_store import from_environment
    try:
        from_environment(sqlite_path="ignored")
        raise AssertionError("PostgreSQL status notifier must be feature-gated")
    except RuntimeError as exc:
        assert str(exc) == "postgres_status_notification_store_not_enabled"
finally:
    os.environ.pop("DATABASE_URL", None)

print("SQLite status notification repository checks: OK")
