import importlib.util
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path


dsn = os.getenv("TEST_POSTGRES_DSN")
if not dsn:
    print("E0.3 B5.3 migration preflight PostgreSQL: skipped")
    raise SystemExit(0)

import psycopg

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "b64", ROOT / "deploy/postgres/check_b64_notification_migration.py")
b64 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b64)

with psycopg.connect(dsn) as db:
    db.execute((ROOT / "deploy/postgres/023_bot_notification_jobs.sql").read_text())
    now = datetime.now(timezone.utc)
    for number in range(80):
        state = "sent" if number < 69 else "sending"
        kind = "montera_admin" if number == 0 else "recall"
        db.execute(
            "INSERT INTO bot_notification_jobs(kind,dedupe_key,payload,state,attempts,claimed_at,sent_at,updated_at) "
            "VALUES(%s,%s,%s::jsonb,%s,1,%s,%s,%s)",
            (kind, str(number), '{"user_id":123}', state,
             now - timedelta(days=2) if state == "sending" else now - timedelta(days=3),
             now - timedelta(days=2) if state == "sent" else None, now),
        )

with psycopg.connect(dsn) as db:
    os.environ["B64_EXPECTED_DATABASE"] = db.info.dbname
    blocked = b64.inspect(db)
assert blocked["status"] == "IN_PROGRESS"
assert blocked["criterionStatus"] == "BLOCKED"
assert blocked["blockers"] == ["LEGACY_SENDING_RECONCILED"]
assert blocked["counts"] == {
    "total": 80, "pending": 0, "sending": 11, "sent": 69, "invalidState": 0,
    "invalidKind": 0, "staleSending": 11, "monteraAdmin": 1,
    "activeMonteraAdmin": 0, "invalidActiveRecipientShape": 0,
    "invalidLifecycle": 0,
}
assert blocked["migrationApplied"] is False and blocked["cutoverAuthorized"] is False
assert "AMBIGUOUS_OPERATOR_DISPOSITION" in blocked["unverifiedGates"]
print("E0.3 B5.3 synthetic-shaped dirty-data scan BLOCKED: OK")
