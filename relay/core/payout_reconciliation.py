"""Compatibility facade for payout reconciliation storage.

New code should use :mod:`repositories.reconciliation_store`.  These helpers
remain for callers that already own a SQLite transaction.
"""
from __future__ import annotations

import sqlite3
from typing import Any


def ensure_schema(conn: sqlite3.Connection) -> None:
    from repositories.reconciliation_store import ensure_sqlite_schema
    ensure_sqlite_schema(conn)


def reconcile_succeeded(
    conn: sqlite3.Connection,
    order_id: int,
    *,
    btc_rate: float | None,
    commission_percent: float,
    referral_percent: float,
) -> dict[str, Any]:
    from repositories.reconciliation_store import reconcile_sqlite_order
    ensure_schema(conn)
    return reconcile_sqlite_order(
        conn, order_id, btc_rate=btc_rate,
        commission_percent=commission_percent,
        referral_percent=referral_percent,
    )


def claim_notification(conn: sqlite3.Connection) -> dict[str, Any] | None:
    from repositories.reconciliation_store import claim_sqlite_notification
    ensure_schema(conn)
    return claim_sqlite_notification(conn)


def mark_notification_sent(conn: sqlite3.Connection, outbox_id: int) -> bool:
    from repositories.reconciliation_store import mark_sqlite_notification_sent
    return mark_sqlite_notification_sent(conn, outbox_id)


def retry_notification(conn: sqlite3.Connection, outbox_id: int) -> bool:
    from repositories.reconciliation_store import retry_sqlite_notification
    return retry_sqlite_notification(conn, outbox_id)
