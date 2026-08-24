import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "relay"))
from repositories.order_read_store import SQLiteOrderReadStore


with tempfile.TemporaryDirectory() as td:
    path = str(Path(td) / "orders.db")
    with sqlite3.connect(path) as c:
        c.executescript((ROOT / "deploy/postgres/019_orders.sql").read_text()
                        .replace("BIGSERIAL PRIMARY KEY", "INTEGER PRIMARY KEY")
                        .replace("BIGINT", "INTEGER").replace("TIMESTAMPTZ", "TEXT")
                        .replace("NUMERIC(20,2)", "REAL").replace("NUMERIC(30,12)", "REAL")
                        .replace("BOOLEAN", "INTEGER").replace("DEFAULT now()", "DEFAULT CURRENT_TIMESTAMP"))
        c.execute("CREATE TABLE payment_sessions(id INTEGER PRIMARY KEY,order_id INTEGER,"
                  "session_token TEXT,status TEXT,created_at TEXT)")
        c.execute("CREATE TABLE order_receipts(order_id INTEGER PRIMARY KEY)")
        c.executemany(
            "INSERT INTO orders(order_id,user_id,username,currency,rub_amount,crypto_address,status,"
            "created_at,network,agreed_rate,agreed_crypto_amount) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            [(1, 7, "u", "BTC", 1000, "a", "sent", "2026-01-01T00:00:00+00:00", "BTC", 10, .1),
             (2, 7, "u", "BTC", 2000, "b", "sent", "2026-01-02T00:00:00+00:00", "BTC", 20, .2),
             (3, 7, "u", "LTC", 3000, "c", "pending", "2026-01-03T00:00:00+00:00", "LTC", None, None)])
        c.executemany("INSERT INTO payment_sessions VALUES(?,?,?,?,?)",
                      [(1, 2, "expired", "expired", "2026-01-02T00:01:00+00:00"),
                       (2, 2, "active", "invoice_created", "2026-01-02T00:02:00+00:00")])
        c.execute("INSERT INTO order_receipts VALUES(2)")
    s = SQLiteOrderReadStore(path)
    assert s.agreed_quote(2) == (20.0, .2)
    try:
        s.agreed_quote(999)
        raise AssertionError("missing order must fail closed")
    except LookupError:
        pass
    assert s.snapshot(2)["crypto_address"] == "b" and s.snapshot(999) is None
    assert s.authorized_snapshot(2, user_id=7)["crypto_address"] == "b"
    assert s.authorized_snapshot(2, user_id=8) is None
    assert s.authorized_snapshot(2, session_token="active")["crypto_address"] == "b"
    assert s.authorized_snapshot(2, session_token="foreign") is None
    try:
        s.authorized_snapshot(2)
        raise AssertionError("authority-free order snapshot must fail closed")
    except ValueError:
        pass
    assert [r["order_id"] for r in s.customer_orders(7, limit=2)] == [3, 2]
    assert s.customer_orders(7, limit=2)[1]["session_token"] == "active"
    assert [r["order_id"] for r in s.web_customer_orders(99, 7, limit=2)] == [3, 2]
    assert s.receipt_order_ids([1, 2, 999]) == {2}
    assert [r["order_id"] for r in s.customer_orders(7, limit=2, offset=1)] == [2, 1]
    assert [r["order_id"] for r in s.customer_history(7)] == [3, 2, 1]
    assert s.latest_customer_order_id(7) == 3 and s.latest_customer_order_id(999) is None
    assert s.find_customer(7)["volume"] == 3000.0
    assert s.find_customer("u")["sent_cnt"] == 2 and s.find_customer("missing") is None
    assert [r["order_id"] for r in s.admin_recent(limit=2)] == [3, 2]
    assert [r["order_id"] for r in s.export_recent(limit=2)] == [2, 3]
    assert s.customer_aggregates(7) == {"total": 3, "completed": 2, "volume": 3000.0,
                                        "first_at": "2026-01-01T00:00:00+00:00",
                                        "favorite_currency": "BTC"}
    assert s.provider_success_count(7) == 2
    limits = s.creation_limit_state(
        7, daily_since="2025-12-31 00:00:00", cooldown_since="2026-01-02 12:00:00")
    assert limits["daily_count"] == 3 and limits["cooldown_active"]
    dashboard = s.operator_dashboard(limit=10)
    assert [row["order_id"] for row in dashboard["pending"]] == [3]
    assert dashboard["paid_count"] == 0 and s.worker_paid_orders() == []
    assert s.active_customer_ids(days=30) == []
    assert s.pending_usdt_match(sender_address="missing", minimum_rub=1,
                                maximum_rub=9999) is None
    assert s.stuck_pending_ids(older_than="2026-02-01 00:00:00") == [3]
    with sqlite3.connect(path) as c:
        c.execute("INSERT INTO orders(order_id,user_id,username,currency,rub_amount,"
                  "crypto_address,status,created_at) VALUES(4,7,'u','BTC',4000,'d','paid',"
                  "CURRENT_TIMESTAMP)")
        c.execute("INSERT INTO orders(order_id,user_id,username,currency,rub_amount,"
                  "crypto_address,status,created_at) VALUES(5,8,'v','USDT',50,'sender','pending',"
                  "CURRENT_TIMESTAMP)")
    assert s.provider_success_count(7) == 3
    assert [row["order_id"] for row in s.worker_paid_orders()] == [4]
    assert set(s.active_customer_ids(days=30)) == {7, 8}
    assert s.pending_usdt_match(sender_address="sender", minimum_rub=45,
                                maximum_rub=55)["order_id"] == 5
print("SQLite order-read repository checks: OK")
