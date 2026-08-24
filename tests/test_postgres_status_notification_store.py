import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "relay"))

dsn = os.environ["TEST_POSTGRES_DSN"]
import psycopg
from repositories.status_notification_store import PostgresStatusNotificationStore

with psycopg.connect(dsn) as conn, conn.cursor() as cur:
    cur.execute("TRUNCATE sent_notifications,gift_vouchers,orders RESTART IDENTITY CASCADE")
    cur.execute("INSERT INTO orders(order_id,user_id,rub_amount,currency,crypto_address,status) "
                "VALUES(1,10,1000,'BTC','bc1','paid'),(2,20,2000,'LTC','ltc1','sent')")
    cur.execute("INSERT INTO gift_vouchers(sender_id,currency,rub_amount,code,status,order_id) "
                "VALUES(10,'BTC',1000,'GIFT','pending',1)")

store = PostgresStatusNotificationStore(dsn)
assert [row["order_id"] for row in store.pending("paid")] == [1]
assert [row["order_id"] for row in store.payout_candidates()] == [1]
assert store.complete(1, "payout_held") and not store.complete(1, "payout_held")
assert store.complete(1, "payout_triggered")
assert store.payout_candidates() == []
assert store.complete(1, "paid") and not store.complete(1, "paid")
assert store.pending("paid") == []
assert [row["order_id"] for row in store.pending("sent")] == [2]
with psycopg.connect(dsn) as conn:
    assert conn.execute("SELECT status FROM gift_vouchers WHERE order_id=1").fetchone()[0] == "paid"

print("PostgreSQL status notification repository checks: OK")
