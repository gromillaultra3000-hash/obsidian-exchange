import os, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "relay"))
from repositories.shadow_payout_store import PostgresShadowPayoutStore

store = PostgresShadowPayoutStore(os.environ["TEST_POSTGRES_DSN"])
with store._c() as c:
    c.execute("DELETE FROM payout_shadow WHERE order_id=990002")
    c.execute("DELETE FROM orders WHERE order_id=990002")
    c.execute("INSERT INTO orders(order_id,user_id,currency,network,crypto_address,status,created_at,updated_at,agreed_crypto_amount,rub_amount) VALUES(990002,990002,'BTC','MAINNET','bc1x','paid',now(),now(),0.1,1000)")
assert any(row["order_id"] == 990002 for row in store.pending_orders(1000))
store.record(990002, "confirmed", "ok", "p", "ok", 1, 1000, "BTC")
assert all(row["order_id"] != 990002 for row in store.pending_orders(1000))
assert store.sync_outcomes() >= 1
assert next(row for row in store.recent(14) if row["order_id"] == 990002)["outcome"] == "ещё не отправлено"
with store._c() as c:
    c.execute("UPDATE orders SET status='sent',paid_btc_tx='manual-1' WHERE order_id=990002")
assert store.sync_outcomes() >= 1
assert next(row for row in store.recent(14) if row["order_id"] == 990002)["outcome"] == "отправлено вручную"
print("PostgreSQL shadow-payout repository checks: OK")
