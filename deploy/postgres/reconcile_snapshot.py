#!/usr/bin/env python3
"""Read-only SQLite/PostgreSQL row-count and canonical-hash reconciliation."""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP


SUCCESSFUL_ORDER_STATUSES = ("sent", "completed")
DIAGNOSTIC_ORDER_STATUSES = ("paid", "pending")


def _canonical(value, *, pg_type: str):
    if value is None:
        return None
    if pg_type == "boolean":
        return "1" if bool(value) else "0"
    if pg_type.startswith("numeric:"):
        scale = int(pg_type.split(":", 1)[1])
        number = Decimal(str(value)).quantize(Decimal(1).scaleb(-scale), rounding=ROUND_HALF_UP)
        if number == 0:
            return "0"
        return format(number.normalize(), "f")
    if pg_type in {"smallint", "integer", "bigint", "numeric", "decimal", "real", "double precision"}:
        number = Decimal(str(value))
        if number == 0:
            return "0"
        return format(number.normalize(), "f")
    if pg_type.startswith("timestamp") or pg_type in {"date", "timestamp with time zone", "timestamp without time zone"}:
        if isinstance(value, str):
            raw = value.strip().replace(" ", "T", 1).replace("Z", "+00:00")
            try:
                value = datetime.fromisoformat(raw)
            except ValueError:
                return raw
        if isinstance(value, date) and not isinstance(value, datetime):
            return value.isoformat()
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
    if isinstance(value, bytes):
        return value.hex()
    return str(value)


def _digest(rows, columns, pg_types):
    lines = []
    for row in rows:
        item = [_canonical(row[index], pg_type=pg_types[column])
                for index, column in enumerate(columns)]
        lines.append(json.dumps(item, ensure_ascii=False, separators=(",", ":")))
    digest = hashlib.sha256()
    for line in sorted(lines):
        digest.update(line.encode())
        digest.update(b"\n")
    return digest.hexdigest()


def _decimal_text(value, *, scale: int):
    """Canonical fixed-scale text for a business amount, preserving NULL."""
    if value is None:
        return None
    number = Decimal(str(value)).quantize(
        Decimal(1).scaleb(-scale), rounding=ROUND_HALF_UP
    )
    return format(number, f".{scale}f")


def _count_map(rows) -> dict[int, int]:
    return {int(user_id): int(count) for user_id, count in rows}


def _count_differences(sqlite_counts, postgres_counts) -> list[dict]:
    return [
        {
            "user_id": user_id,
            "sqlite_count": sqlite_counts.get(user_id, 0),
            "postgres_count": postgres_counts.get(user_id, 0),
        }
        for user_id in sorted(set(sqlite_counts) | set(postgres_counts))
        if sqlite_counts.get(user_id, 0) != postgres_counts.get(user_id, 0)
    ]


def _vip_map(rows) -> dict[int, str | None]:
    return {
        int(user_id): _decimal_text(total_rub, scale=2)
        for user_id, total_rub in rows
    }


def _vip_differences(sqlite_rows, postgres_rows) -> list[dict]:
    differences = []
    for user_id in sorted(set(sqlite_rows) | set(postgres_rows)):
        sqlite_present = user_id in sqlite_rows
        postgres_present = user_id in postgres_rows
        sqlite_total = sqlite_rows.get(user_id)
        postgres_total = postgres_rows.get(user_id)
        if (
            sqlite_present == postgres_present
            and sqlite_total == postgres_total
        ):
            continue
        differences.append({
            "user_id": user_id,
            "sqlite_present": sqlite_present,
            "postgres_present": postgres_present,
            "sqlite_total_rub": sqlite_total,
            "postgres_total_rub": postgres_total,
        })
    return differences


def _total(values, *, scale: int) -> str:
    total = sum(
        (Decimal(value) for value in values if value is not None),
        Decimal(0),
    )
    return format(total, f".{scale}f")


def reconcile_cutover_invariants(sqlite_path: str, postgres_dsn: str) -> dict:
    """Compare cutover-critical user progress and non-blocking diagnostics.

    The only critical checks are the per-user count of orders in the immutable
    successful statuses and the exact per-user VIP amount at its NUMERIC(20,2)
    storage scale. Referral data and open-order status counts are deliberately
    reported as diagnostics and cannot make this semantic gate fail.
    """
    import psycopg

    source = sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True)
    try:
        with psycopg.connect(postgres_dsn) as target, target.cursor() as cur:
            source_success = _count_map(source.execute(
                "SELECT user_id,COUNT(*) FROM orders "
                "WHERE status IN (?,?) GROUP BY user_id ORDER BY user_id",
                SUCCESSFUL_ORDER_STATUSES,
            ).fetchall())
            cur.execute(
                "SELECT user_id,COUNT(*) FROM orders "
                "WHERE status IN (%s,%s) GROUP BY user_id ORDER BY user_id",
                SUCCESSFUL_ORDER_STATUSES,
            )
            target_success = _count_map(cur.fetchall())
            success_differences = _count_differences(
                source_success, target_success
            )

            source_vip = _vip_map(source.execute(
                "SELECT user_id,total_rub FROM user_vip_volume ORDER BY user_id"
            ).fetchall())
            cur.execute(
                "SELECT user_id,total_rub FROM user_vip_volume ORDER BY user_id"
            )
            target_vip = _vip_map(cur.fetchall())
            vip_differences = _vip_differences(source_vip, target_vip)

            source_referral = source.execute(
                "SELECT COUNT(*),COALESCE(SUM(bonus_amount),0) "
                "FROM referral_bonuses"
            ).fetchone()
            cur.execute(
                "SELECT COUNT(*),COALESCE(SUM(bonus_amount),0) "
                "FROM referral_bonuses"
            )
            target_referral = cur.fetchone()

            source_order_status = dict.fromkeys(DIAGNOSTIC_ORDER_STATUSES, 0)
            source_order_status.update({
                str(status): int(count)
                for status, count in source.execute(
                    "SELECT status,COUNT(*) FROM orders "
                    "WHERE status IN (?,?) GROUP BY status",
                    DIAGNOSTIC_ORDER_STATUSES,
                ).fetchall()
            })
            cur.execute(
                "SELECT status,COUNT(*) FROM orders "
                "WHERE status IN (%s,%s) GROUP BY status",
                DIAGNOSTIC_ORDER_STATUSES,
            )
            target_order_status = dict.fromkeys(DIAGNOSTIC_ORDER_STATUSES, 0)
            target_order_status.update({
                str(status): int(count) for status, count in cur.fetchall()
            })
    finally:
        source.close()

    critical = {
        "successful_orders_by_user": {
            "status": "match" if not success_differences else "mismatch",
            "included_statuses": list(SUCCESSFUL_ORDER_STATUSES),
            "sqlite_user_count": len(source_success),
            "postgres_user_count": len(target_success),
            "sqlite_order_count": sum(source_success.values()),
            "postgres_order_count": sum(target_success.values()),
            "differences": success_differences,
        },
        "user_vip_volume": {
            "status": "match" if not vip_differences else "mismatch",
            "amount_scale": 2,
            "sqlite_user_count": len(source_vip),
            "postgres_user_count": len(target_vip),
            "sqlite_total_rub": _total(source_vip.values(), scale=2),
            "postgres_total_rub": _total(target_vip.values(), scale=2),
            "differences": vip_differences,
        },
    }
    referral_sqlite_total = _decimal_text(source_referral[1], scale=12)
    referral_postgres_total = _decimal_text(target_referral[1], scale=12)
    informational = {
        "referral_bonuses": {
            "blocking": False,
            "expected": "zero_rows_and_zero_total",
            "status": (
                "zero"
                if (
                    int(source_referral[0]) == 0
                    and referral_sqlite_total == "0.000000000000"
                    and int(target_referral[0]) == 0
                    and referral_postgres_total == "0.000000000000"
                )
                else "attention"
            ),
            "sqlite_row_count": int(source_referral[0]),
            "postgres_row_count": int(target_referral[0]),
            "sqlite_total": referral_sqlite_total,
            "postgres_total": referral_postgres_total,
            "sqlite_zero": (
                int(source_referral[0]) == 0
                and referral_sqlite_total == "0.000000000000"
            ),
            "postgres_zero": (
                int(target_referral[0]) == 0
                and referral_postgres_total == "0.000000000000"
            ),
        },
        "order_status_counts": {
            "blocking": False,
            "status": (
                "match"
                if source_order_status == target_order_status
                else "different"
            ),
            "included_statuses": list(DIAGNOSTIC_ORDER_STATUSES),
            "sqlite": source_order_status,
            "postgres": target_order_status,
        },
    }
    return {
        "status": (
            "match"
            if all(item["status"] == "match" for item in critical.values())
            else "critical_mismatch"
        ),
        "critical": critical,
        "informational": informational,
    }


def reconcile(sqlite_path: str, postgres_dsn: str, tables: list[str]):
    import psycopg

    results = []
    source = sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True)
    try:
        with psycopg.connect(postgres_dsn) as target, target.cursor() as cur:
            for table in tables:
                if not table.replace("_", "").isalnum():
                    raise ValueError(f"invalid_table:{table}")
                source_columns = [row[1] for row in source.execute(f'PRAGMA table_info("{table}")')]
                cur.execute(
                    "SELECT column_name,data_type,COALESCE(numeric_scale,-1) FROM information_schema.columns "
                    "WHERE table_schema='public' AND table_name=%s ORDER BY ordinal_position", (table,))
                target_meta = cur.fetchall()
                target_columns = [row[0] for row in target_meta]
                if not target_columns:
                    results.append({"table": table, "status": "missing",
                                    "sqlite": bool(source_columns), "postgres": False})
                    continue
                if not source_columns:
                    cur.execute(f'SELECT COUNT(*) FROM "{table}"')
                    count = cur.fetchone()[0]
                    results.append({"table": table, "status": "match" if count == 0 else "data_mismatch",
                                    "sqlite_count": 0, "postgres_count": count,
                                    "source_table_absent": True})
                    continue
                columns = [column for column in target_columns if column in source_columns]
                if not columns:
                    results.append({"table": table, "status": "schema_mismatch",
                                    "sqlite_columns": source_columns, "postgres_columns": target_columns})
                    continue
                pg_types = {name: (f"numeric:{scale}" if kind == "numeric" and scale >= 0 else kind)
                            for name, kind, scale in target_meta}
                projection = ",".join(f'"{column}"' for column in columns)
                source_rows = source.execute(f'SELECT {projection} FROM "{table}"').fetchall()
                cur.execute(f'SELECT {projection} FROM "{table}"')
                target_rows = cur.fetchall()
                source_hash = _digest(source_rows, columns, pg_types)
                target_hash = _digest(target_rows, columns, pg_types)
                results.append({"table": table,
                                "status": "match" if (len(source_rows), source_hash) ==
                                (len(target_rows), target_hash) else "data_mismatch",
                                "sqlite_count": len(source_rows), "postgres_count": len(target_rows),
                                "sqlite_sha256": source_hash, "postgres_sha256": target_hash,
                                "compared_columns": columns,
                                "ignored_sqlite_columns": [c for c in source_columns if c not in columns],
                                "ignored_postgres_columns": [c for c in target_columns if c not in columns]})
    finally:
        source.close()
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sqlite", required=True)
    parser.add_argument("--postgres", required=True)
    parser.add_argument("--tables", help="comma-separated allowlist; defaults to migration table set")
    parser.add_argument(
        "--critical-invariants",
        action="store_true",
        help=(
            "also require exact per-user successful-order counts and VIP "
            "progression; include non-blocking referral/open-order diagnostics"
        ),
    )
    args = parser.parse_args()
    if args.tables:
        tables = [item.strip() for item in args.tables.split(",") if item.strip()]
    else:
        from load_sqlite_snapshot import TABLE_ORDER
        tables = TABLE_ORDER
    results = reconcile(args.sqlite, args.postgres, tables)
    tables_match = all(item["status"] == "match" for item in results)
    if not args.critical_invariants:
        print(json.dumps(results, ensure_ascii=False, indent=2))
        raise SystemExit(0 if tables_match else 1)

    invariants = reconcile_cutover_invariants(args.sqlite, args.postgres)
    report = {
        "status": (
            "match"
            if tables_match and invariants["status"] == "match"
            else "mismatch"
        ),
        "tables": results,
        "cutover_invariants": invariants,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["status"] == "match" else 1)


if __name__ == "__main__":
    main()
