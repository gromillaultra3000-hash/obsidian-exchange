"""Privacy-safe acquisition KPI aggregation. No customer-level output."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any


SCHEMA = "obsidian-acquisition-kpi-report.v1"
FINAL_STATUS = "sent"
FORBIDDEN_KEYS = {
    "user_id", "telegram_id", "username", "first_name", "last_name", "phone",
    "email", "address", "crypto_address", "receive_address", "txid", "tx_hash",
    "session_token", "client_ip", "user_agent", "provider_payload", "receipt_path",
}


def _ratio(numerator: int | float, denominator: int | float) -> float | None:
    return round(float(numerator) / float(denominator), 6) if denominator else None


def _money(value: Any) -> float:
    return round(float(value or 0), 2)


def _rows(connection: sqlite3.Connection, sql: str, parameters=()) -> list[dict[str, Any]]:
    cursor = connection.execute(sql, parameters)
    columns = [item[0] for item in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def _one(connection: sqlite3.Connection, sql: str, parameters=()) -> dict[str, Any]:
    rows = _rows(connection, sql, parameters)
    if len(rows) != 1:
        raise RuntimeError("acquisition_kpi_expected_one_row")
    return rows[0]


def _assert_privacy(value: Any) -> None:
    if isinstance(value, dict):
        forbidden = set(value) & FORBIDDEN_KEYS
        if forbidden:
            raise RuntimeError(f"acquisition_kpi_forbidden_fields:{','.join(sorted(forbidden))}")
        for nested in value.values():
            _assert_privacy(nested)
    elif isinstance(value, list):
        for nested in value:
            _assert_privacy(nested)


def _report_digest(report: dict[str, Any]) -> str:
    unsigned = {key: value for key, value in report.items() if key != "report_sha256"}
    encoded = json.dumps(unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_acquisition_kpi_report(
    connection: sqlite3.Connection,
    *,
    as_of: str,
    minimum_cohort_users: int = 10,
) -> dict[str, Any]:
    if not isinstance(as_of, str) or not as_of:
        raise ValueError("as_of_required")
    if not isinstance(minimum_cohort_users, int) or isinstance(minimum_cohort_users, bool) or minimum_cohort_users < 10:
        raise ValueError("minimum_cohort_users_must_be_at_least_10")

    window = _one(connection, "SELECT MIN(created_at) first_order_at,MAX(created_at) last_order_at FROM orders")
    funnel = _one(
        connection,
        "SELECT COUNT(*) total_orders,"
        "SUM(CASE WHEN status='sent' THEN 1 ELSE 0 END) fulfilled_orders,"
        "SUM(CASE WHEN status='paid' THEN 1 ELSE 0 END) paid_not_fulfilled_orders,"
        "SUM(CASE WHEN status='expired' THEN 1 ELSE 0 END) expired_orders,"
        "SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END) pending_orders,"
        "COALESCE(SUM(CASE WHEN status='sent' THEN rub_amount ELSE 0 END),0) fulfilled_gmv_rub,"
        "COALESCE(SUM(CASE WHEN status IN('paid','sent') THEN rub_amount ELSE 0 END),0) payment_confirmed_volume_rub "
        "FROM orders",
    )
    users = _one(
        connection,
        "WITH per_user AS ("
        "SELECT user_id,COUNT(*) orders,"
        "SUM(CASE WHEN status='sent' THEN 1 ELSE 0 END) fulfilled "
        "FROM orders WHERE user_id>0 GROUP BY user_id) "
        "SELECT COUNT(*) transacting_users,"
        "SUM(CASE WHEN fulfilled>0 THEN 1 ELSE 0 END) fulfilled_users,"
        "SUM(CASE WHEN fulfilled>=2 THEN 1 ELSE 0 END) repeat_fulfilled_users "
        "FROM per_user",
    )

    monthly_raw = _rows(
        connection,
        "SELECT strftime('%Y-%m',created_at) month,COUNT(*) orders,"
        "COUNT(DISTINCT CASE WHEN user_id>0 THEN user_id END) users,"
        "SUM(CASE WHEN status='sent' THEN 1 ELSE 0 END) fulfilled_orders,"
        "COALESCE(SUM(CASE WHEN status='sent' THEN rub_amount ELSE 0 END),0) fulfilled_gmv_rub "
        "FROM orders GROUP BY month ORDER BY month",
    )
    monthly = []
    suppressed_months = 0
    for row in monthly_raw:
        if int(row["users"] or 0) < minimum_cohort_users:
            suppressed_months += 1
            continue
        monthly.append({
            "month": row["month"], "orders": int(row["orders"]), "users": int(row["users"]),
            "fulfilled_orders": int(row["fulfilled_orders"] or 0),
            "fulfilled_gmv_rub": _money(row["fulfilled_gmv_rub"]),
            "order_fulfillment_rate": _ratio(row["fulfilled_orders"] or 0, row["orders"]),
        })

    cohorts_raw = _rows(
        connection,
        "WITH firsts AS ("
        "SELECT user_id,strftime('%Y-%m',MIN(created_at)) cohort_month "
        "FROM orders WHERE user_id>0 GROUP BY user_id),"
        "per_user AS ("
        "SELECT o.user_id,f.cohort_month,COUNT(*) orders,"
        "SUM(CASE WHEN o.status='sent' THEN 1 ELSE 0 END) fulfilled_orders,"
        "COALESCE(SUM(CASE WHEN o.status='sent' THEN o.rub_amount ELSE 0 END),0) fulfilled_gmv_rub "
        "FROM orders o JOIN firsts f ON f.user_id=o.user_id GROUP BY o.user_id,f.cohort_month) "
        "SELECT cohort_month,COUNT(*) cohort_users,SUM(orders) orders,"
        "SUM(fulfilled_orders) fulfilled_orders,"
        "SUM(CASE WHEN fulfilled_orders>0 THEN 1 ELSE 0 END) fulfilled_users,"
        "SUM(CASE WHEN fulfilled_orders>=2 THEN 1 ELSE 0 END) repeat_fulfilled_users,"
        "SUM(fulfilled_gmv_rub) fulfilled_gmv_rub "
        "FROM per_user GROUP BY cohort_month ORDER BY cohort_month",
    )
    cohorts = []
    suppressed_cohorts = 0
    for row in cohorts_raw:
        cohort_users = int(row["cohort_users"])
        if cohort_users < minimum_cohort_users:
            suppressed_cohorts += 1
            continue
        fulfilled_users = int(row["fulfilled_users"] or 0)
        repeat_users = int(row["repeat_fulfilled_users"] or 0)
        cohorts.append({
            "cohort_month": row["cohort_month"], "cohort_users": cohort_users,
            "orders": int(row["orders"]), "fulfilled_orders": int(row["fulfilled_orders"] or 0),
            "fulfilled_users": fulfilled_users, "repeat_fulfilled_users": repeat_users,
            "fulfilled_user_rate": _ratio(fulfilled_users, cohort_users),
            "repeat_rate_among_fulfilled_users": _ratio(repeat_users, fulfilled_users),
            "fulfilled_gmv_rub": _money(row["fulfilled_gmv_rub"]),
        })

    currency_mix = _rows(
        connection,
        "SELECT currency,COUNT(*) fulfilled_orders,COALESCE(SUM(rub_amount),0) fulfilled_gmv_rub "
        "FROM orders WHERE status='sent' GROUP BY currency HAVING COUNT(*)>=? ORDER BY fulfilled_gmv_rub DESC,currency",
        (minimum_cohort_users,),
    )
    currency_mix = [{
        "currency": row["currency"], "fulfilled_orders": int(row["fulfilled_orders"]),
        "fulfilled_gmv_rub": _money(row["fulfilled_gmv_rub"]),
    } for row in currency_mix]

    provider_mix = _rows(
        connection,
        "WITH latest AS (SELECT order_id,MAX(id) session_id FROM payment_sessions "
        "WHERE order_id IS NOT NULL GROUP BY order_id) "
        "SELECT ps.provider,COUNT(*) recorded_orders "
        "FROM latest l JOIN payment_sessions ps ON ps.id=l.session_id "
        "JOIN orders o ON o.order_id=l.order_id WHERE o.status='sent' "
        "GROUP BY ps.provider HAVING COUNT(*)>=? ORDER BY recorded_orders DESC,ps.provider",
        (minimum_cohort_users,),
    )
    provider_mix = [{"provider": row["provider"], "recorded_fulfilled_orders": int(row["recorded_orders"])} for row in provider_mix]

    total = int(funnel["total_orders"] or 0)
    fulfilled = int(funnel["fulfilled_orders"] or 0)
    fulfilled_users = int(users["fulfilled_users"] or 0)
    repeat_users = int(users["repeat_fulfilled_users"] or 0)
    report = {
        "schema": SCHEMA,
        "as_of": as_of,
        "data_window": {"first_order_at": window["first_order_at"], "last_order_at": window["last_order_at"]},
        "order_funnel": {
            "total_orders": total, "fulfilled_orders": fulfilled,
            "paid_not_fulfilled_orders": int(funnel["paid_not_fulfilled_orders"] or 0),
            "expired_orders": int(funnel["expired_orders"] or 0),
            "pending_orders": int(funnel["pending_orders"] or 0),
            "order_fulfillment_rate": _ratio(fulfilled, total),
            "fulfilled_gmv_rub": _money(funnel["fulfilled_gmv_rub"]),
            "payment_confirmed_volume_rub": _money(funnel["payment_confirmed_volume_rub"]),
        },
        "user_quality": {
            "transacting_users": int(users["transacting_users"] or 0),
            "fulfilled_users": fulfilled_users,
            "repeat_fulfilled_users": repeat_users,
            "repeat_rate_among_fulfilled_users": _ratio(repeat_users, fulfilled_users),
        },
        "monthly_performance": {"minimum_users": minimum_cohort_users, "rows": monthly, "suppressed_month_count": suppressed_months},
        "acquisition_cohorts": {"minimum_users": minimum_cohort_users, "rows": cohorts, "suppressed_cohort_count": suppressed_cohorts},
        "currency_mix": currency_mix,
        "payment_session_provider_mix": provider_mix,
        "evidence_limitations": {
            "revenue_available": False, "gross_margin_available": False,
            "ebitda_or_sde_available": False, "cac_available": False, "ltv_available": False,
            "fulfilled_volume_is_gmv_not_revenue": True,
            "provider_mix_is_session_record_not_profitability": True,
        },
        "report_sha256": "",
    }
    _assert_privacy(report)
    report["report_sha256"] = _report_digest(report)
    return report
