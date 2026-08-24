import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "relay"))

import psycopg
from repositories.order_creation_store import PostgresOrderCreationStore

dsn = os.environ["TEST_POSTGRES_DSN"]
orders_sql = (ROOT / "deploy/postgres/019_orders.sql").read_text()
sessions_sql = (ROOT / "deploy/postgres/007_payment_sessions.sql").read_text()

with psycopg.connect(dsn) as conn, conn.cursor() as cur:
    cur.execute("DROP TABLE IF EXISTS payment_sessions,orders CASCADE")
    cur.execute(orders_sql)
    cur.execute(sessions_sql)
    cur.execute("SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name='orders' ORDER BY ordinal_position")
    columns = [row[0] for row in cur.fetchall()]

assert columns == [
    "order_id", "user_id", "username", "currency", "rub_amount", "crypto_address",
    "status", "created_at", "paid_btc_tx", "updated_at", "web_user_id",
    "rub_volume_counted", "verification_requested", "montera_invoice_id",
    "receipt_deadline", "receipt_sent_at", "network", "agreed_rate",
    "agreed_crypto_amount", "agreed_at",
]

store = PostgresOrderCreationStore(dsn)
oid = store.create(user_id=42, username="u", currency="BTC", rub_amount=15000,
                   destination="bc1qtest", network="BTC", agreed_rate=9000000,
                   agreed_crypto_amount=0.001666666667, web_user_id=7)
row = store.recent_duplicate(user_id=42, currency="BTC", rub_amount=15000,
                             destination="bc1qtest", network="BTC",
                             default_network="BTC", seconds=90)
assert row == {"order_id": oid, "session_token": None}

with psycopg.connect(dsn) as conn, conn.cursor() as cur:
    cur.execute("SELECT rub_volume_counted,created_at,agreed_at FROM orders WHERE order_id=%s", (oid,))
    saved = cur.fetchone()
    assert saved[0] is False and saved[1] is not None and saved[2] is not None

print("PostgreSQL canonical orders schema checks: OK")
