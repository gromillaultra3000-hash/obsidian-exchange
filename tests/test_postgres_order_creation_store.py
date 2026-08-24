import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "relay"))
dsn = os.getenv("TEST_POSTGRES_DSN")
if not dsn:
    print("postgres order creation store: skipped (TEST_POSTGRES_DSN unset)")
    raise SystemExit(0)

from repositories.order_creation_store import PostgresOrderCreationStore

store = PostgresOrderCreationStore(dsn)
oid = store.create(user_id=7, username="tester", currency="USDT", rub_amount=10000,
                   destination="0xdest", network="ERC20", agreed_rate=100,
                   agreed_crypto_amount=100)
assert store.recent_duplicate(user_id=7, currency="USDT", rub_amount=10000,
                              destination="0xdest", network="ERC20",
                              default_network="TRC20")["order_id"] == oid
print("PostgreSQL order creation repository checks: OK")
