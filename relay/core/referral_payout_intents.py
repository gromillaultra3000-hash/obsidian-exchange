"""SQL-free compatibility facade for durable referral payout intents.

New runtime code uses :mod:`repositories.payout_store` directly.  These
functions preserve the legacy connection-oriented API for focused contracts
and callers that have not yet moved to the aggregate store.
"""
from __future__ import annotations

import sqlite3
from typing import Any


def _queries():
    from repositories.payout_store import SQLiteReferralIntentQueries
    return SQLiteReferralIntentQueries


def ensure_schema(conn: sqlite3.Connection) -> None:
    _queries().ensure_schema(conn)


def create(conn: sqlite3.Connection, *, user_id: int, destination: str,
           minimum_btc: float) -> dict[str, Any]:
    return _queries().create(
        conn, user_id=user_id, destination=destination, minimum_btc=minimum_btc)


def claim_next(conn: sqlite3.Connection) -> dict[str, Any] | None:
    return _queries().claim_next(conn)


def get(conn: sqlite3.Connection, ident: int) -> dict[str, Any] | None:
    return _queries().get(conn, ident)


def succeed(conn: sqlite3.Connection, ident: int, txid: str) -> bool:
    return _queries().succeed(conn, ident, txid)


def review(conn: sqlite3.Connection, ident: int, error_code: str) -> bool:
    return _queries().review(conn, ident, error_code)


def admin_confirm_txid(conn: sqlite3.Connection, ident: int, txid: str, *,
                       actor: str | int, evidence: str) -> bool:
    return _queries().admin_confirm_txid(
        conn, ident, txid, actor=actor, evidence=evidence)


def admin_requeue_absent(conn: sqlite3.Connection, ident: int, *,
                         actor: str | int, evidence: str) -> bool:
    return _queries().admin_requeue_absent(
        conn, ident, actor=actor, evidence=evidence)


def reconcile_next(conn: sqlite3.Connection) -> dict[str, Any] | None:
    """Compatibility facade; storage is owned by reconciliation_store."""
    from repositories.reconciliation_store import (
        ensure_sqlite_schema,
        reconcile_sqlite_referral,
    )
    ensure_sqlite_schema(conn)
    return reconcile_sqlite_referral(conn)
