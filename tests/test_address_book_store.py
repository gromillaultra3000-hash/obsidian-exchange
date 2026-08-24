import sqlite3, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "relay"))
from repositories.address_book_store import SQLiteAddressBookStore

with tempfile.TemporaryDirectory() as td:
    path = str(Path(td) / "book.db")
    with sqlite3.connect(path) as c:
        c.execute("CREATE TABLE orders(order_id INTEGER PRIMARY KEY,user_id INTEGER,currency TEXT,network TEXT,crypto_address TEXT,status TEXT,created_at TEXT,updated_at TEXT,agreed_crypto_amount REAL,paid_btc_tx TEXT)")
        c.execute("CREATE TABLE client_address_notes(user_id INTEGER NOT NULL,currency TEXT NOT NULL,network TEXT NOT NULL DEFAULT '',address TEXT NOT NULL,label TEXT NOT NULL DEFAULT '',hidden INTEGER NOT NULL DEFAULT 0,updated_at TEXT NOT NULL,PRIMARY KEY(user_id,currency,network,address))")
        c.execute("INSERT INTO orders VALUES(1,7,'BTC','MAINNET','bc1x','sent','2026-08-09','2026-08-09',0.1,'tx')")
    store = SQLiteAddressBookStore(path)
    rows, notes = store.entries(7, ("sent", "completed"))
    assert rows[0]["crypto_address"] == "bc1x" and notes == []
    store.upsert_note(7, "BTC", "MAINNET", "bc1x", "cold", None, "2026-08-09T00:00:00+00:00")
    store.upsert_note(7, "BTC", "MAINNET", "bc1x", None, 1, "2026-08-09T00:00:01+00:00")
    _, notes = store.entries(7, ("sent",))
    assert notes == [{"currency": "BTC", "network": "MAINNET", "address": "bc1x", "label": "cold", "hidden": 1}]
    assert store.deliveries(7, ("sent",), 10)[0]["order_id"] == 1
print("SQLite address-book repository checks: OK")
