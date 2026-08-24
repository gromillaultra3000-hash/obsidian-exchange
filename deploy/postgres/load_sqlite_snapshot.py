#!/usr/bin/env python3
"""Load a consistent SQLite snapshot into an explicitly named rehearsal DB."""
from __future__ import annotations

import argparse
import sqlite3
from urllib.parse import urlparse


PRODUCTION_SCHEMA_VERSION = 23

# The immutable SQLite cutover/source contract ends at migration 023.  Keep
# this inventory separate from later dormant PostgreSQL-only migrations: the
# production loader must continue to require exactly these 54 source tables.
PRODUCTION_TABLE_ORDER = [
    "orders", "web_users", "web_sessions", "bot_users", "workers", "worker_ids", "operators",
    "blocked_users", "blocked_addresses", "reserves", "system_flags",
    "admin_log", "risk_events", "user_vip_volume", "rate_subscriptions",
    "referral_bonuses", "client_address_notes", "reviews", "payout_queue", "payout_shadow",
    "provider_health", "provider_attempts", "alert_throttle", "alert_watermark",
    "audit_log", "referrals", "referral_addresses", "rate_locks", "promo_codes",
    "promo_uses", "payment_sessions", "payment_transition_audit",
    "payment_notification_outbox", "gift_vouchers", "dca_schedules", "limit_orders",
    "support_tickets", "support_messages", "swap_sessions", "sell_orders",
    "order_receipts", "sent_notifications", "wallet_links", "wallet_send_intents",
    "payout_intents", "payout_intent_audit", "payout_reconciliations",
    "referral_payout_intents", "referral_payout_intent_audit", "notification_outbox",
    "order_lifecycle_work",
    "sell_settlement_ledger", "sell_settlement_outbox",
    "bot_notification_jobs",
]

# Migration 024 is PostgreSQL-only and deliberately absent from the frozen
# SQLite source.  Repository-complete schema checks use this separate profile;
# production loading/reconciliation continues to use TABLE_ORDER below.
DORMANT_MIGRATION_TABLE_ORDER = [
    "e3_paper_evidence",
    "e3_paper_evidence_heads",
]
MIGRATION_COMPLETE_TABLE_ORDER = [
    *PRODUCTION_TABLE_ORDER,
    *DORMANT_MIGRATION_TABLE_ORDER,
]

# Compatibility name for existing source/cutover consumers.  New consumers
# should choose the named production or migration-complete profile explicitly.
TABLE_ORDER = PRODUCTION_TABLE_ORDER


def _safe_target(dsn: str):
    name = urlparse(dsn).path.lstrip("/").lower()
    if not any(marker in name for marker in ("rehearsal", "staging", "contract")):
        raise RuntimeError("refusing_non_rehearsal_database")


def _target_metadata(cur):
    cur.execute(
        "SELECT table_name,column_name,data_type "
        "FROM information_schema.columns WHERE table_schema='public' "
        "ORDER BY table_name,ordinal_position"
    )
    metadata = {}
    for table, column, data_type in cur.fetchall():
        metadata.setdefault(table, []).append((column, data_type))
    return metadata


def _copy_snapshot(source, target, selected, target_meta_by_table):
    """Copy selected SQLite tables into one caller-owned PG transaction."""
    from psycopg import sql
    from psycopg.types.json import Jsonb

    report = []
    with target.cursor() as cur:
        for table in selected:
            source_meta = source.execute(f'PRAGMA table_info("{table}")').fetchall()
            if not source_meta:
                report.append({"table": table, "rows": 0, "status": "source_missing"})
                continue
            source_columns = [row[1] for row in source_meta]
            target_meta = target_meta_by_table[table]
            target_types = dict(target_meta)
            columns = [name for name, _ in target_meta if name in source_columns]
            if not columns:
                source_count = int(source.execute(
                    f'SELECT COUNT(*) FROM "{table}"'
                ).fetchone()[0])
                if source_count:
                    raise RuntimeError(f"no_compatible_columns:{table}")
                report.append({
                    "table": table,
                    "rows": 0,
                    "status": "loaded",
                    "ignored_source_columns": source_columns,
                })
                continue
            rows = source.execute(
                "SELECT " + ",".join(f'"{name}"' for name in columns) +
                f' FROM "{table}"'
            ).fetchall()
            converted = []
            for row in rows:
                values = []
                for name, value in zip(columns, row):
                    kind = target_types[name]
                    if value is not None and kind == "boolean":
                        value = bool(value)
                    elif value is not None and kind in {"numeric", "decimal"}:
                        from decimal import Decimal
                        # psycopg sends Python float using its binary value;
                        # Decimal(str(...)) preserves SQLite's visible value
                        # before PostgreSQL applies the declared scale.
                        value = Decimal(str(value))
                    elif value is not None and kind in {"json", "jsonb"}:
                        import json
                        value = Jsonb(
                            json.loads(value) if isinstance(value, str) else value
                        )
                    values.append(value)
                converted.append(values)
            if converted:
                statement = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
                    sql.Identifier(table),
                    sql.SQL(",").join(map(sql.Identifier, columns)),
                    sql.SQL(",").join(sql.Placeholder() for _ in columns),
                )
                cur.executemany(statement, converted)
            ignored = [name for name in source_columns if name not in target_types]
            report.append({
                "table": table,
                "rows": len(rows),
                "status": "loaded",
                "ignored_source_columns": ignored,
            })
        cur.execute(
            "SELECT table_name,column_name FROM information_schema.columns "
            "WHERE table_schema='public' AND column_default LIKE 'nextval(%'"
        )
        for table, column in cur.fetchall():
            if table not in selected:
                continue
            cur.execute(sql.SQL(
                "SELECT setval(pg_get_serial_sequence(%s,%s),"
                "COALESCE(MAX({}),1),MAX({}) IS NOT NULL) FROM {}"
            ).format(
                sql.Identifier(column), sql.Identifier(column), sql.Identifier(table)
            ), (table, column))
    return report


def load(sqlite_path: str, postgres_dsn: str):
    """Destructive rehearsal/staging loader retained behind its name guard."""
    import psycopg
    from psycopg import sql

    _safe_target(postgres_dsn)
    source = sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True)
    try:
        with psycopg.connect(postgres_dsn) as target, target.cursor() as cur:
            target_meta = _target_metadata(cur)
            selected = [table for table in TABLE_ORDER if table in target_meta]
            cur.execute(sql.SQL("TRUNCATE {} RESTART IDENTITY CASCADE").format(
                sql.SQL(",").join(sql.Identifier(table) for table in selected)
            ))
            return _copy_snapshot(source, target, selected, target_meta)
    finally:
        source.close()


def load_empty_snapshot(sqlite_path: str, postgres_dsn: str, *,
                        expected_database: str,
                        expected_tables: list[str] | None = None,
                        before_commit=None):
    """Atomically load a frozen snapshot into an exact, empty PG schema.

    This path never truncates. It locks every expected table, verifies all of
    them are still empty in the same transaction, then copies and sets serial
    sequences. Any row or schema drift rolls the transaction back.
    """
    import psycopg
    from psycopg import sql

    required = list(expected_tables or TABLE_ORDER)
    if not required or len(required) != len(set(required)):
        raise RuntimeError("invalid_expected_table_inventory")
    source = sqlite3.connect(f"file:{sqlite_path}?mode=ro&immutable=1", uri=True)
    try:
        with psycopg.connect(postgres_dsn) as target, target.cursor() as cur:
            database = cur.execute("SELECT current_database()").fetchone()[0]
            if database != expected_database:
                raise RuntimeError(f"unexpected_target_database:{database}")
            target_meta = _target_metadata(cur)
            actual = set(target_meta)
            expected = set(required)
            if actual != expected:
                raise RuntimeError(
                    "unexpected_target_inventory:missing=" +
                    ",".join(sorted(expected - actual)) + ";unexpected=" +
                    ",".join(sorted(actual - expected))
                )
            cur.execute(sql.SQL("LOCK TABLE {} IN ACCESS EXCLUSIVE MODE").format(
                sql.SQL(",").join(sql.Identifier(table) for table in required)
            ))
            nonempty = []
            for table in required:
                cur.execute(sql.SQL("SELECT count(*) FROM {}").format(
                    sql.Identifier(table)
                ))
                count = int(cur.fetchone()[0])
                if count:
                    nonempty.append((table, count))
            if nonempty:
                raise RuntimeError(
                    "production_target_not_empty:" +
                    ",".join(f"{table}={count}" for table, count in nonempty)
                )
            report = _copy_snapshot(source, target, required, target_meta)
            if before_commit is not None:
                before_commit()
            return report
    finally:
        source.close()


def main():
    import json
    parser = argparse.ArgumentParser()
    parser.add_argument("--sqlite", required=True)
    parser.add_argument("--postgres", required=True)
    args = parser.parse_args()
    print(json.dumps(load(args.sqlite, args.postgres), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
