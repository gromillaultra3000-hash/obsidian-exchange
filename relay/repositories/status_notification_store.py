"""Persistence boundary for the legacy paid/sent status notifier."""
from __future__ import annotations

import os

from core import db_runtime

_NOTIFICATION_EVENTS = {"paid", "sent"}
_PAYOUT_EVENTS = {"payout_held", "payout_triggered"}


class SQLiteStatusNotificationStore:
    def __init__(self, path: str, *, timeout: float = 10):
        self.path, self.timeout = path, timeout

    def _connect(self):
        return db_runtime.sqlite_connect(self.path, timeout=self.timeout)

    def pending(self, event: str, *, limit: int = 10):
        if event not in _NOTIFICATION_EVENTS:
            raise ValueError("invalid_notification_event")
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT o.order_id,o.user_id,o.rub_amount,o.currency,o.paid_btc_tx "
                "FROM orders o WHERE o.status=? AND NOT EXISTS(SELECT 1 FROM sent_notifications sn "
                "WHERE sn.order_id=o.order_id AND sn.event=?) ORDER BY o.order_id LIMIT ?",
                (event, event, int(limit)),
            ).fetchall()
        return [{"order_id": row[0], "user_id": row[1], "rub_amount": row[2],
                 "currency": row[3], "paid_btc_tx": row[4]} for row in rows]

    def payout_candidates(self, *, hours: int = 24, limit: int = 5):
        hours, limit = max(1, min(int(hours), 168)), max(1, min(int(limit), 100))
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT o.order_id,o.user_id,o.rub_amount,o.crypto_address,o.currency,o.network "
                "FROM orders o WHERE o.status='paid' "
                "AND datetime(COALESCE(o.updated_at,o.created_at))>=datetime('now',?) "
                "AND NOT EXISTS(SELECT 1 FROM sent_notifications sn WHERE "
                "sn.order_id=o.order_id AND sn.event='payout_triggered') "
                "ORDER BY o.created_at ASC LIMIT ?", (f"-{hours} hours", limit),).fetchall()
        keys = ("order_id", "user_id", "rub_amount", "crypto_address", "currency", "network")
        return [dict(zip(keys, row)) for row in rows]

    def complete(self, order_id: int, event: str) -> bool:
        if event not in _NOTIFICATION_EVENTS | _PAYOUT_EVENTS:
            raise ValueError("invalid_notification_event")
        with self._connect() as conn:
            changed = conn.execute(
                "INSERT OR IGNORE INTO sent_notifications(order_id,event) VALUES(?,?)",
                (order_id, event),
            ).rowcount == 1
            if event == "paid":
                conn.execute("UPDATE gift_vouchers SET status='paid' "
                             "WHERE order_id=? AND status='pending'", (order_id,))
            conn.commit()
        return changed


class PostgresStatusNotificationStore:
    def __init__(self, dsn: str):
        self.dsn = dsn

    def _connect(self):
        import psycopg
        from psycopg.rows import dict_row
        return psycopg.connect(self.dsn, row_factory=dict_row)

    def pending(self, event: str, *, limit: int = 10):
        if event not in _NOTIFICATION_EVENTS:
            raise ValueError("invalid_notification_event")
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT o.order_id,o.user_id,o.rub_amount,o.currency,o.paid_btc_tx "
                "FROM orders o WHERE o.status=%s AND NOT EXISTS(SELECT 1 FROM sent_notifications sn "
                "WHERE sn.order_id=o.order_id AND sn.event=%s) ORDER BY o.order_id LIMIT %s",
                (event, event, int(limit)),
            )
            return [dict(row) for row in cur.fetchall()]

    def payout_candidates(self, *, hours: int = 24, limit: int = 5):
        hours, limit = max(1, min(int(hours), 168)), max(1, min(int(limit), 100))
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT o.order_id,o.user_id,o.rub_amount,o.crypto_address,o.currency,o.network "
                "FROM orders o WHERE o.status='paid' "
                "AND COALESCE(o.updated_at,o.created_at)>=now()-(%s*interval '1 hour') "
                "AND NOT EXISTS(SELECT 1 FROM sent_notifications sn WHERE "
                "sn.order_id=o.order_id AND sn.event='payout_triggered') "
                "ORDER BY o.created_at ASC LIMIT %s", (hours, limit))
            return [dict(row) for row in cur.fetchall()]

    def complete(self, order_id: int, event: str) -> bool:
        if event not in _NOTIFICATION_EVENTS | _PAYOUT_EVENTS:
            raise ValueError("invalid_notification_event")
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO sent_notifications(order_id,event) VALUES(%s,%s) "
                "ON CONFLICT(order_id,event) DO NOTHING", (order_id, event)
            )
            changed = cur.rowcount == 1
            if event == "paid":
                cur.execute("UPDATE gift_vouchers SET status='paid' "
                            "WHERE order_id=%s AND status='pending'", (order_id,))
        return changed


def from_environment(*, sqlite_path: str):
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        return SQLiteStatusNotificationStore(sqlite_path)
    enabled = os.getenv("STATUS_NOTIFICATION_POSTGRES_ENABLED", "").lower()
    if db_runtime.backend(url) != "postgresql" or enabled not in {"1", "true", "yes"}:
        raise RuntimeError("postgres_status_notification_store_not_enabled")
    return PostgresStatusNotificationStore(url)
