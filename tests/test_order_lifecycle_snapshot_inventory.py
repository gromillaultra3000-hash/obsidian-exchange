import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"deploy/postgres"))
from load_sqlite_snapshot import TABLE_ORDER

assert len(TABLE_ORDER)==54
assert TABLE_ORDER.count("order_lifecycle_work")==1
assert TABLE_ORDER.count("sell_settlement_ledger")==1
assert TABLE_ORDER.count("sell_settlement_outbox")==1
assert TABLE_ORDER.count("bot_notification_jobs")==1
assert (ROOT/"deploy/postgres/021_order_lifecycle.sql").is_file()
schema=(ROOT/"deploy/postgres/021_order_lifecycle.sql").read_text()
for invariant in ("UNIQUE(kind,order_id,session_token)","state IN('pending','sending','done')",
                  "provider_cancel","order_expired_notify","session_dead_admin",
                  "session_dead_customer"):
    assert invariant in schema,invariant
print("Order lifecycle snapshot/migration inventory: OK")
