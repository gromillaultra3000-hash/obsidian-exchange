import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "relay"))

dsn = os.getenv("TEST_POSTGRES_DSN")
if not dsn:
    print("postgres legacy runtime store: skipped")
    raise SystemExit(0)

from repositories.legacy_runtime_store import PostgresLegacyRuntimeStore


store = PostgresLegacyRuntimeStore(dsn)
with store._connect() as conn, conn.cursor() as cur:
    cur.execute("TRUNCATE payout_queue, risk_events RESTART IDENTITY")
    cur.execute(
        "INSERT INTO payout_queue(order_id,btc_address,btc_amount,status,created_at) "
        "VALUES(1,'bc1qtest',0.1,'new',now()-interval '30 minutes'),"
        "(2,'bc1qtest',0.1,'new',now()-interval '5 minutes'),"
        "(3,'bc1qtest',0.1,'sent',now()-interval '30 minutes')"
    )
    cur.execute(
        "INSERT INTO risk_events(event_type,created_at) "
        "VALUES('old',now()-interval '30 minutes'),('fresh',now()-interval '5 minutes')"
    )

assert store.stuck_payout_count(older_than_minutes=20) == 1
since = datetime.now(timezone.utc) - timedelta(minutes=10)
assert store.recent_risk_event_count(since=since) == 1
print("PostgreSQL legacy runtime repository checks: OK")
