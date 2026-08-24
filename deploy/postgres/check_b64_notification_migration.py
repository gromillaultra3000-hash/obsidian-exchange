#!/usr/bin/env python3
"""Read-only, secret-free preflight for the B5.3 compatibility migration."""
import json
import os
import sys


LEGACY_SHAPE = [
    ("id", "int8", "NO"), ("kind", "text", "NO"),
    ("dedupe_key", "text", "NO"), ("payload", "jsonb", "NO"),
    ("state", "text", "NO"), ("attempts", "int4", "NO"),
    ("created_at", "timestamptz", "NO"), ("claimed_at", "timestamptz", "YES"),
    ("sent_at", "timestamptz", "YES"), ("updated_at", "timestamptz", "NO"),
]

COUNT_NAMES = [
    "total", "pending", "sending", "sent", "invalidState", "invalidKind",
    "staleSending", "monteraAdmin", "activeMonteraAdmin",
    "invalidActiveRecipientShape", "invalidLifecycle",
]
ALLOWED_BLOCKERS = {
    "LEGACY_STATE_VALID", "LEGACY_KIND_VALID",
    "LEGACY_ACTIVE_RECIPIENT_SHAPE_VALID", "LEGACY_LIFECYCLE_VALID",
    "LEGACY_PENDING_DRAINED", "LEGACY_SENDING_RECONCILED",
    "LEGACY_MONTERA_ADMIN_RECIPIENT_PROVEN",
}
UNVERIFIED_GATES = [
    "CATALOG_ACL_OBJECT_HASH", "BACKUP_RESTORE_EQUALITY",
    "AUTHENTICATED_OWNER_REVIEW", "AMBIGUOUS_OPERATOR_DISPOSITION",
]


def valid_snapshot_scan(value: object) -> bool:
    """Accept only the exact aggregate scan emitted after target/shape attestation."""
    if not isinstance(value, dict) or set(value) != {
        "schemaVersion", "status", "criterionStatus", "blockers", "counts",
        "privacy", "migrationApplied", "cutoverAuthorized", "unverifiedGates",
    }:
        return False
    blockers = value.get("blockers")
    counts = value.get("counts")
    if (value.get("schemaVersion") != "b64-notification-dirty-data-scan.v1"
            or value.get("status") != "IN_PROGRESS"
            or value.get("criterionStatus") not in {"PASS", "BLOCKED"}
            or value.get("privacy") != "NO_IDENTIFIERS_OR_PAYLOAD"
            or value.get("migrationApplied") is not False
            or value.get("cutoverAuthorized") is not False
            or value.get("unverifiedGates") != UNVERIFIED_GATES
            or not isinstance(blockers, list)
            or len(blockers) != len(set(blockers))
            or any(item not in ALLOWED_BLOCKERS for item in blockers)
            or not isinstance(counts, dict)
            or list(counts) != COUNT_NAMES
            or any(type(counts.get(name)) is not int or counts[name] < 0
                   for name in COUNT_NAMES)):
        return False
    if ((value["criterionStatus"] == "PASS") != (blockers == [])
            or counts["total"] != (counts["pending"] + counts["sending"]
                                   + counts["sent"] + counts["invalidState"])
            or counts["staleSending"] > counts["sending"]
            or counts["monteraAdmin"] > counts["total"]
            or counts["activeMonteraAdmin"] > counts["monteraAdmin"]
            or counts["activeMonteraAdmin"]
            > counts["pending"] + counts["sending"] + counts["invalidState"]
            or counts["invalidKind"] + counts["monteraAdmin"] > counts["total"]
            or counts["monteraAdmin"] - counts["activeMonteraAdmin"] > counts["sent"]
            or any(counts[name] > counts["total"] for name in (
                "invalidState", "invalidKind", "invalidLifecycle",
            ))
            or counts["invalidActiveRecipientShape"]
            > counts["pending"] + counts["sending"]):
        return False
    expected = []
    for name, blocker in (
        ("invalidState", "LEGACY_STATE_VALID"),
        ("invalidKind", "LEGACY_KIND_VALID"),
        ("invalidActiveRecipientShape", "LEGACY_ACTIVE_RECIPIENT_SHAPE_VALID"),
        ("invalidLifecycle", "LEGACY_LIFECYCLE_VALID"),
        ("pending", "LEGACY_PENDING_DRAINED"),
        ("sending", "LEGACY_SENDING_RECONCILED"),
        ("activeMonteraAdmin", "LEGACY_MONTERA_ADMIN_RECIPIENT_PROVEN"),
    ):
        if counts[name]:
            expected.append(blocker)
    return blockers == expected


def inspect(conn, *, configure_transaction: bool = True) -> dict:
    if configure_transaction:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        conn.execute("SET LOCAL statement_timeout='15s'")
        conn.execute("SET LOCAL lock_timeout='2s'")
    target = conn.execute(
        "SELECT current_database()=%s,current_setting('server_version_num')::integer/10000,"
        "current_setting('transaction_read_only')",
        (os.environ["B64_EXPECTED_DATABASE"],),
    ).fetchone()
    shape = [tuple(row) for row in conn.execute(
        "SELECT column_name,udt_name,is_nullable FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name='bot_notification_jobs' "
        "ORDER BY ordinal_position"
    ).fetchall()]
    if not target[0] or target[1] != 17 or target[2] != "on" or shape != LEGACY_SHAPE:
        return {
            "schemaVersion": "b64-notification-dirty-data-scan.v1",
            "status": "IN_PROGRESS", "criterionStatus": "BLOCKED",
            "blockers": ["TARGET_PG17_READONLY_AND_LEGACY_SHAPE_EXACT"],
            "counts": {}, "privacy": "NO_IDENTIFIERS_OR_PAYLOAD",
            "migrationApplied": False, "cutoverAuthorized": False,
        }
    row = conn.execute(
        "SELECT count(*) AS total,"
        "count(*) FILTER(WHERE state='pending') AS pending,"
        "count(*) FILTER(WHERE state='sending') AS sending,"
        "count(*) FILTER(WHERE state='sent') AS sent,"
        "count(*) FILTER(WHERE state IS NULL OR state NOT IN('pending','sending','sent')) AS invalid_state,"
        "count(*) FILTER(WHERE kind IS NULL OR kind NOT IN('recall','montera_customer','montera_admin','pay_reminder','payout_delayed','winback_promo')) AS invalid_kind,"
        "count(*) FILTER(WHERE state='sending' AND claimed_at<=clock_timestamp()-interval '24 hours') AS stale_sending,"
        "count(*) FILTER(WHERE kind='montera_admin') AS montera_admin,"
        "count(*) FILTER(WHERE kind='montera_admin' AND state<>'sent') AS active_montera_admin,"
        "count(*) FILTER(WHERE state IN('pending','sending') AND (payload IS NULL OR jsonb_typeof(payload)<>'object' OR NOT(payload ? 'user_id') "
        " OR jsonb_typeof(payload->'user_id') NOT IN('number','string') "
        " OR payload->>'user_id'!~'^[1-9][0-9]{0,18}$' "
        " OR length(payload->>'user_id')=19 AND payload->>'user_id'>'9223372036854775807')) AS invalid_active_recipient_shape,"
        "count(*) FILTER(WHERE attempts IS NULL OR attempts<0 "
        " OR state='pending' AND (claimed_at IS NOT NULL OR sent_at IS NOT NULL) "
        " OR state='sending' AND (attempts<1 OR claimed_at IS NULL OR sent_at IS NOT NULL) "
        " OR state='sent' AND (attempts<1 OR claimed_at IS NULL OR sent_at IS NULL)) AS invalid_lifecycle "
        "FROM public.bot_notification_jobs"
    ).fetchone()
    counts = {name: int(value) for name, value in zip(COUNT_NAMES, row)}
    blockers = []
    if counts["invalidState"]:
        blockers.append("LEGACY_STATE_VALID")
    if counts["invalidKind"]:
        blockers.append("LEGACY_KIND_VALID")
    if counts["invalidActiveRecipientShape"]:
        blockers.append("LEGACY_ACTIVE_RECIPIENT_SHAPE_VALID")
    if counts["invalidLifecycle"]:
        blockers.append("LEGACY_LIFECYCLE_VALID")
    if counts["pending"]:
        blockers.append("LEGACY_PENDING_DRAINED")
    if counts["sending"]:
        blockers.append("LEGACY_SENDING_RECONCILED")
    if counts["activeMonteraAdmin"]:
        blockers.append("LEGACY_MONTERA_ADMIN_RECIPIENT_PROVEN")
    return {
        "schemaVersion": "b64-notification-dirty-data-scan.v1",
        "status": "IN_PROGRESS",
        "criterionStatus": "PASS" if not blockers else "BLOCKED",
        "blockers": blockers,
        "counts": counts,
        "privacy": "NO_IDENTIFIERS_OR_PAYLOAD",
        "migrationApplied": False,
        "cutoverAuthorized": False,
        "unverifiedGates": UNVERIFIED_GATES,
    }


def main() -> int:
    dsn = os.getenv("B64_READONLY_DATABASE_URL", "").strip()
    if not dsn or not os.getenv("B64_EXPECTED_DATABASE", "").strip():
        print(json.dumps({"status": "ERROR", "errorType": "ConfigurationError"}))
        return 2
    try:
        import psycopg
        with psycopg.connect(dsn, connect_timeout=5) as conn:
            result = inspect(conn)
    except Exception as exc:
        print(json.dumps({"status": "ERROR", "errorType": type(exc).__name__}, separators=(",", ":")))
        return 2
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if result.get("criterionStatus") == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
