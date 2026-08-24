"""Atomic creation and short-window deduplication for ordinary buy orders."""
from __future__ import annotations

import os
from typing import Any, Protocol

from core import db_runtime


class OrderCreationStore(Protocol):
    def create(self, *, user_id: int, username: str, currency: str,
               rub_amount: float, destination: str, network: str | None,
               agreed_rate: float, agreed_crypto_amount: float,
               web_user_id: int | None = None) -> int: ...
    def recent_duplicate(self, *, user_id: int, currency: str, rub_amount: float,
                         destination: str, network: str, default_network: str,
                         seconds: int = 90) -> dict[str, Any] | None: ...


class SQLiteOrderCreationStore:
    def __init__(self, path: str, *, timeout: float = 5):
        self.path, self.timeout = path, timeout

    def _connect(self):
        return db_runtime.sqlite_connect(self.path, timeout=self.timeout)

    def create(self, **order) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO orders(user_id,username,currency,rub_amount,crypto_address,status,"
                "web_user_id,network,agreed_rate,agreed_crypto_amount,agreed_at) "
                "VALUES(?,?,?,?,?,'pending',?,?,?,?,CURRENT_TIMESTAMP)",
                (int(order["user_id"]), order["username"], order["currency"],
                 float(order["rub_amount"]), order["destination"], order.get("web_user_id"),
                 order.get("network"), float(order["agreed_rate"]),
                 float(order["agreed_crypto_amount"])))
            conn.commit()
            return int(cur.lastrowid)

    def recent_duplicate(self, **query):
        seconds = min(300, max(1, int(query.get("seconds", 90))))
        with self._connect() as conn:
            row = conn.execute(
                "SELECT o.order_id,ps.session_token FROM orders o LEFT JOIN payment_sessions ps "
                "ON ps.order_id=o.order_id AND ps.status NOT IN('failed','expired') "
                "WHERE o.user_id=? AND o.currency=? AND o.rub_amount=? AND o.crypto_address=? "
                "AND COALESCE(o.network,?)=? AND o.status='pending' "
                "AND o.created_at>datetime('now',?) ORDER BY o.created_at DESC LIMIT 1",
                (int(query["user_id"]), query["currency"], float(query["rub_amount"]),
                 query["destination"], query["default_network"], query["network"],
                 f"-{seconds} seconds")).fetchone()
        return {"order_id": int(row[0]), "session_token": row[1]} if row else None


class PostgresOrderCreationStore:
    def __init__(self, dsn: str):
        self.dsn = dsn

    def _connect(self):
        import psycopg
        from psycopg.rows import dict_row
        return psycopg.connect(self.dsn, row_factory=dict_row)

    def create(self, **order) -> int:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO orders(user_id,username,currency,rub_amount,crypto_address,status,"
                "web_user_id,network,agreed_rate,agreed_crypto_amount,agreed_at) "
                "VALUES(%s,%s,%s,%s,%s,'pending',%s,%s,%s,%s,now()) RETURNING order_id",
                (int(order["user_id"]), order["username"], order["currency"],
                 order["rub_amount"], order["destination"], order.get("web_user_id"),
                 order.get("network"), order["agreed_rate"], order["agreed_crypto_amount"]))
            return int(cur.fetchone()["order_id"])

    def recent_duplicate(self, **query):
        seconds = min(300, max(1, int(query.get("seconds", 90))))
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT o.order_id,ps.session_token FROM orders o LEFT JOIN payment_sessions ps "
                "ON ps.order_id=o.order_id AND ps.status NOT IN('failed','expired') "
                "WHERE o.user_id=%s AND o.currency=%s AND o.rub_amount=%s AND o.crypto_address=%s "
                "AND COALESCE(o.network,%s)=%s AND o.status='pending' "
                "AND o.created_at>now()-(%s * interval '1 second') "
                "ORDER BY o.created_at DESC LIMIT 1",
                (int(query["user_id"]), query["currency"], query["rub_amount"],
                 query["destination"], query["default_network"], query["network"], seconds))
            row = cur.fetchone()
            return dict(row) if row else None


def from_environment(*, sqlite_path: str) -> OrderCreationStore:
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        return SQLiteOrderCreationStore(sqlite_path)
    if (db_runtime.backend(url) != "postgresql" or
            os.getenv("ORDER_POSTGRES_ENABLED", "").strip().lower()
            not in {"1", "true", "yes"}):
        raise RuntimeError("postgres_order_store_not_enabled")
    return PostgresOrderCreationStore(url)
