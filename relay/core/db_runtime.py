"""Explicit database boundary used while SQLite writers migrate to PostgreSQL.

The current runtime is deliberately SQLite-only. A PostgreSQL URL is rejected
instead of accidentally treating it as a filesystem path; PostgreSQL payout
semantics are rehearsed separately in deploy/postgres until callers stop using
SQLite-specific SQL and row APIs.
"""
from __future__ import annotations

import os
import sqlite3
from urllib.parse import urlparse


def backend(value: str | None = None) -> str:
    target = value or os.getenv("DATABASE_URL") or os.getenv("DB_PATH", "/root/exchange.db")
    scheme = urlparse(target).scheme.lower()
    if scheme in ("postgres", "postgresql"):
        return "postgresql"
    if scheme in ("", "file", "sqlite"):
        return "sqlite"
    raise ValueError(f"unsupported_database_scheme:{scheme}")


def sqlite_connect(path: str | None = None, *, timeout: float = 10) -> sqlite3.Connection:
    if os.getenv("DATABASE_URL") and backend(os.getenv("DATABASE_URL")) != "sqlite":
        raise RuntimeError("postgres_runtime_not_enabled")
    target = path or os.getenv("DB_PATH", "/root/exchange.db")
    if backend(target) != "sqlite":
        raise RuntimeError("sqlite_path_required")
    if target.startswith("sqlite:///"):
        target = urlparse(target).path
    conn = sqlite3.connect(target, timeout=timeout)
    conn.execute(f"PRAGMA busy_timeout={int(timeout * 1000)}")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def auxiliary_sqlite_connect(path: str, *, timeout: float = 10) -> sqlite3.Connection:
    """Open a named non-exchange SQLite database (support/cache state).

    Auxiliary stores intentionally ignore ``DATABASE_URL``: migrating the
    exchange ledger must never redirect an unrelated local support database.
    """
    target = str(path or "").strip()
    if not target or backend(target) != "sqlite":
        raise RuntimeError("auxiliary_sqlite_path_required")
    if target.startswith("sqlite:///"):
        target = urlparse(target).path
    conn = sqlite3.connect(target, timeout=timeout)
    conn.execute(f"PRAGMA busy_timeout={int(timeout * 1000)}")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn
