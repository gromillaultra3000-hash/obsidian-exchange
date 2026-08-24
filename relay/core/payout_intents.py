"""SQL-free compatibility facade for legacy order-intent callers.

Authoritative SQLite persistence lives in ``repositories.payout_store``.
New runtime code should use ``PayoutStore`` rather than this connection-level API.
"""
from __future__ import annotations

import sqlite3
from typing import Any


def _queries():
    # Lazy import avoids a core/repository import cycle while old initialization
    # and tests still call this connection-level compatibility API.
    from repositories.payout_store import SQLiteOrderIntentQueries
    return SQLiteOrderIntentQueries


def ensure_schema(conn: sqlite3.Connection) -> None:
    _queries().ensure_schema(conn)


def create(conn: sqlite3.Connection, *, order_id: int, rub_amount: float,
           crypto_amount: float, currency: str, network: str | None,
           destination: str, source: str,
           requested_by: str | int | None = None) -> dict[str, Any]:
    return _queries().create(
        conn, order_id=order_id, rub_amount=rub_amount,
        crypto_amount=crypto_amount, currency=currency, network=network,
        destination=destination, source=source, requested_by=requested_by)


def claim(conn: sqlite3.Connection, order_id: int) -> dict[str, Any] | None:
    return _queries().claim(conn, order_id)


def claim_next(conn: sqlite3.Connection) -> dict[str, Any] | None:
    return _queries().claim_next(conn)


def succeed(conn: sqlite3.Connection, order_id: int, txid: str) -> bool:
    return _queries().succeed(conn, order_id, txid)


def review(conn: sqlite3.Connection, order_id: int, error_code: str) -> bool:
    return _queries().review(conn, order_id, error_code)


def get(conn: sqlite3.Connection, order_id: int) -> dict[str, Any] | None:
    return _queries().get(conn, order_id)


def admin_confirm_txid(conn: sqlite3.Connection, order_id: int, txid: str, *,
                       actor: str | int, evidence: str) -> bool:
    return _queries().admin_confirm_txid(
        conn, order_id, txid, actor=actor, evidence=evidence)


def admin_requeue_absent(conn: sqlite3.Connection, order_id: int, *,
                         actor: str | int, evidence: str) -> bool:
    return _queries().admin_requeue_absent(
        conn, order_id, actor=actor, evidence=evidence)
