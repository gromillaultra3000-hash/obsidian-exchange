import os, sqlite3, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "relay"))
from services.conversion_intel import provider_conversion
from services.evidence import evidence_summary

with tempfile.TemporaryDirectory() as td:
    path = str(Path(td) / "analytics.db")
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE orders(order_id INTEGER PRIMARY KEY,status TEXT,"
                 "paid_btc_tx TEXT,created_at TEXT)")
    conn.execute("CREATE TABLE payment_sessions(order_id INTEGER,provider TEXT,created_at TEXT)")
    for oid in range(1, 7):
        conn.execute("INSERT INTO orders VALUES(?,?,?,datetime('now'))",
                     (oid, "sent" if oid <= 3 else "expired", "tx" if oid <= 2 else None))
        conn.execute("INSERT INTO payment_sessions VALUES(?, 'ProviderA', datetime('now'))", (oid,))
    conn.commit()
    conn.close()
    conversion = provider_conversion(30, path)
    assert conversion["providers"][0]["shown"] == 6
    assert conversion["providers"][0]["paid"] == 3
    evidence = evidence_summary(30, path)
    assert evidence["total_completed"] == 3
    assert evidence["chain_confirmed"] == 2

print("database analytics boundary checks: OK")
