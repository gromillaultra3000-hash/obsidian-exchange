import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "relay"))

from repositories.legacy_runtime_store import SQLiteLegacyRuntimeStore


with tempfile.TemporaryDirectory() as td:
    path = str(Path(td) / "exchange.db")
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE payout_queue(
            id INTEGER PRIMARY KEY, status TEXT, created_at TEXT
        );
        CREATE TABLE risk_events(
            id INTEGER PRIMARY KEY, event_type TEXT, created_at TEXT
        );
    """)
    old = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
    fresh = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    conn.executemany(
        "INSERT INTO payout_queue(status,created_at) VALUES(?,?)",
        [("new", old), ("new", fresh), ("sent", old)],
    )
    conn.executemany(
        "INSERT INTO risk_events(event_type,created_at) VALUES(?,?)",
        [("old", old), ("fresh", fresh)],
    )
    conn.commit()
    conn.close()

    store = SQLiteLegacyRuntimeStore(path)
    assert store.stuck_payout_count(older_than_minutes=20) == 1
    since = datetime.now(timezone.utc) - timedelta(minutes=10)
    assert store.recent_risk_event_count(since=since) == 1

with tempfile.TemporaryDirectory() as td:
    assert SQLiteLegacyRuntimeStore(str(Path(td) / "empty.db")).stuck_payout_count() == 0

print("SQLite legacy runtime repository checks: OK")
