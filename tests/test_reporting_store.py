import os
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "relay"))

from repositories.reporting_store import SQLiteReportingStore


with tempfile.TemporaryDirectory() as td:
    path = str(Path(td) / "reporting.db")
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE orders(order_id INTEGER PRIMARY KEY,user_id INTEGER,username TEXT,currency TEXT,status TEXT,rub_amount REAL,
          paid_btc_tx TEXT,created_at TEXT);
        CREATE TABLE payment_sessions(id INTEGER PRIMARY KEY,order_id INTEGER,provider TEXT,created_at TEXT);
        CREATE TABLE provider_health(provider TEXT PRIMARY KEY,is_healthy INTEGER,failed_count INTEGER,
          avg_response_time REAL,status TEXT,blocker TEXT);
        CREATE TABLE reserves(currency TEXT PRIMARY KEY,amount REAL,updated_at TEXT);
        CREATE TABLE limit_orders(id INTEGER PRIMARY KEY,status TEXT);
        CREATE TABLE dca_schedules(id INTEGER PRIMARY KEY,status TEXT);
    """)
    conn.execute("INSERT INTO orders VALUES(1,10,'u10','BTC','sent',1000,'tx1',datetime('now'))")
    conn.execute("INSERT INTO orders VALUES(2,20,'u20','LTC','paid',2000,NULL,datetime('now'))")
    conn.execute("INSERT INTO orders VALUES(3,30,'u30','USDT','pending',3000,NULL,datetime('now'))")
    conn.executemany("INSERT INTO payment_sessions VALUES(?,?,'P',datetime('now'))", [(1,1), (2,2), (3,3)])
    conn.execute("INSERT INTO provider_health VALUES('P',1,0,0.5,'READY','')")
    conn.executemany("INSERT INTO reserves VALUES(?,?,datetime('now'))", [("BTC", 2), ("RUB", 0)])
    conn.commit()
    conn.close()

    store = SQLiteReportingStore(path)
    assert store.provider_conversion_rows(30) == [{"provider": "P", "shown": 3, "paid": 2}]
    assert len(store.completed_evidence_rows(30)) == 2
    assert store.public_stats() == {"exchanges_today": 1, "exchanges_total": 1,
                                    "volume_24h": 1000.0, "volume_total": 1000.0}
    assert store.reserves(positive_only=True) == [("BTC", 2.0)]
    assert [r[:2] for r in store.reserves_detailed()] == [("BTC", 2.0), ("RUB", 0.0)]
    assert store.bot_today_summary() == {"today_count": 3, "today_volume": 6000.0,
        "today_sent": 1, "today_sent_volume": 1000.0, "pending": 1, "paid": 1,
        "new_users": 3, "active_limits": 0, "active_dca": 0}
    assert store.admin_stats() == {"total": 3, "pending": 1, "sent": 1, "volume": 1000.0}
    assert store.site_stats() == {"total": 3, "completed": 2, "attempted": 2}
    assert store.today_status_counts() == {
        "total": 3, "pending": 1, "completed": 2, "expired": 0}
    assert store.stuck_pending_orders(older_than_minutes=0)["count"] == 1
    assert store.recent_conversion() == {"total": 3, "paid": 2}
    assert store.daily_order_stats() == {"total": 3, "paid": 2,
                                         "volume": 3000.0, "users": 3}
    today = __import__("datetime").date.today().isoformat()
    assert store.period_order_report(today, today) == {
        "sent_count": 1, "sent_volume": 1000.0, "total_count": 3,
        "currencies": [("BTC", 1, 1000.0)], "new_users": 3}
    cumulative = store.cumulative_stats({"Сегодня": today}, today,
                                        ["BTC", "LTC", "USDT"],
                                        ["pending", "paid", "sent"])
    assert cumulative["periods"]["Сегодня"] == (1, 1000.0)
    assert cumulative["currencies"]["BTC"] == (1, 1000.0)
    assert cumulative["statuses"] == {"pending": 1, "paid": 1, "sent": 1}
    analytics = store.admin_analytics()
    assert analytics["totals"] == {"total_orders": 3, "total_volume": 6000.0,
        "paid_orders": 2, "paid_volume": 3000.0}
    assert analytics["recent"][0]["provider"] == "P"
    assert analytics["providers"][0]["status"] == "READY"

os.environ["DATABASE_URL"] = "postgresql://example.invalid/db"
try:
    from repositories.reporting_store import from_environment
    try:
        from_environment(sqlite_path="ignored")
        raise AssertionError("PostgreSQL reporting must be feature-gated")
    except RuntimeError as exc:
        assert str(exc) == "postgres_reporting_store_not_enabled"
finally:
    os.environ.pop("DATABASE_URL", None)

print("SQLite reporting repository checks: OK")
