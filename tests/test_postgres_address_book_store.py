import os, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "relay"))
from repositories.address_book_store import PostgresAddressBookStore

store = PostgresAddressBookStore(os.environ["TEST_POSTGRES_DSN"])
with store._c() as c:
    c.execute("DELETE FROM client_address_notes WHERE user_id=990001")
    c.execute("DELETE FROM orders WHERE order_id=990001")
    c.execute("INSERT INTO orders(order_id,user_id,currency,network,crypto_address,status,created_at,updated_at,agreed_crypto_amount,paid_btc_tx,rub_amount) VALUES(990001,990001,'BTC','MAINNET','bc1x','sent',now(),now(),0.1,'tx',1000)")
rows, notes = store.entries(990001, ("sent", "completed"))
assert rows[0]["crypto_address"] == "bc1x" and notes == []
store.upsert_note(990001, "BTC", "MAINNET", "bc1x", "cold", None, "2026-08-09T00:00:00+00:00")
store.upsert_note(990001, "BTC", "MAINNET", "bc1x", None, 1, "2026-08-09T00:00:01+00:00")
_, notes = store.entries(990001, ("sent",))
assert notes[0]["label"] == "cold" and notes[0]["hidden"] is True
assert store.deliveries(990001, ("sent",), 10)[0]["order_id"] == 990001
print("PostgreSQL address-book repository checks: OK")
