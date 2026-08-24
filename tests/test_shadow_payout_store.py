import sqlite3, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "relay"))
from repositories.shadow_payout_store import SQLiteShadowPayoutStore

with tempfile.TemporaryDirectory() as td:
    path = str(Path(td) / "shadow.db")
    with sqlite3.connect(path) as c:
        c.execute("CREATE TABLE orders(order_id INTEGER PRIMARY KEY,rub_amount REAL,currency TEXT,crypto_address TEXT,status TEXT,paid_btc_tx TEXT,created_at TEXT)")
        c.execute("CREATE TABLE payout_shadow(order_id INTEGER PRIMARY KEY,decided_at TEXT DEFAULT CURRENT_TIMESTAMP,verdict TEXT,detail TEXT,provider TEXT,circuit_action TEXT,would_auto_pay INTEGER,rub_amount REAL,currency TEXT,outcome TEXT,outcome_at TEXT)")
        c.execute("INSERT INTO orders VALUES(1,1000,'BTC','bc1x','paid',NULL,CURRENT_TIMESTAMP)")
    store = SQLiteShadowPayoutStore(path)
    assert store.pending_orders(10)[0]["order_id"] == 1
    store.record(1, "confirmed", "ok", "p", "ok", 1, 1000, "BTC")
    assert store.pending_orders(10) == []
    assert store.sync_outcomes() == 1
    assert store.recent(14)[0]["outcome"] == "ещё не отправлено"
    with sqlite3.connect(path) as c:
        c.execute("UPDATE orders SET status='sent',paid_btc_tx='manual-1' WHERE order_id=1")
    assert store.sync_outcomes() == 1
    assert store.recent(14)[0]["outcome"] == "отправлено вручную"
print("SQLite shadow-payout repository checks: OK")
