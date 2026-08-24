import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "relay"))
from repositories.order_creation_store import SQLiteOrderCreationStore

with tempfile.TemporaryDirectory() as td:
    path = str(Path(td) / "orders.db")
    with sqlite3.connect(path) as conn:
        conn.executescript("""
        CREATE TABLE orders(
          order_id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,username TEXT,
          currency TEXT,rub_amount REAL,crypto_address TEXT,status TEXT,
          web_user_id INTEGER,network TEXT,agreed_rate REAL,
          agreed_crypto_amount REAL,agreed_at TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE payment_sessions(order_id INTEGER,session_token TEXT,status TEXT);
        """)
    store = SQLiteOrderCreationStore(path)
    oid = store.create(user_id=7, username="tester", currency="USDT",
                       rub_amount=10000, destination="0xdest", network="ERC20",
                       agreed_rate=100, agreed_crypto_amount=100)
    dup = store.recent_duplicate(user_id=7, currency="USDT", rub_amount=10000,
                                 destination="0xdest", network="ERC20",
                                 default_network="TRC20")
    assert dup == {"order_id": oid, "session_token": None}
    with sqlite3.connect(path) as conn:
        row = conn.execute("SELECT status,agreed_rate,agreed_crypto_amount FROM orders").fetchone()
        assert row == ("pending", 100.0, 100.0)
        conn.execute("INSERT INTO payment_sessions VALUES(?,?,?)", (oid, "session-1", "pending"))
    assert store.recent_duplicate(user_id=7, currency="USDT", rub_amount=10000,
                                  destination="0xdest", network="ERC20",
                                  default_network="TRC20")["session_token"] == "session-1"
    assert store.recent_duplicate(user_id=8, currency="USDT", rub_amount=10000,
                                  destination="0xdest", network="ERC20",
                                  default_network="TRC20") is None
print("SQLite order creation repository checks: OK")
