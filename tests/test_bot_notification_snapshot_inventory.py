import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "deploy/postgres"))

from load_sqlite_snapshot import TABLE_ORDER


assert len(TABLE_ORDER) == 54
assert TABLE_ORDER[-1] == "bot_notification_jobs"
schema = (ROOT / "deploy/postgres/023_bot_notification_jobs.sql").read_text("utf-8")
for invariant in (
    "UNIQUE(kind,dedupe_key)",
    "state IN('pending','sending','sent')",
    "state,attempts,id",
    "montera_customer",
    "montera_admin",
    "pay_reminder",
    "payout_delayed",
    "winback_promo",
):
    assert invariant in schema, invariant

print("Bot notification snapshot/migration inventory: 54 tables OK")
