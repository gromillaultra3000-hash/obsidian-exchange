"""Persistence boundary for customer address-book notes and order history."""
from __future__ import annotations

import os
import sqlite3

from core import db_runtime


def _timestamp_text(value):
    return value.isoformat() if hasattr(value, "isoformat") else value


class SQLiteAddressBookStore:
    def __init__(self, path, *, timeout=5):
        self.path, self.timeout = path, timeout

    def _c(self):
        connection = db_runtime.sqlite_connect(self.path, timeout=self.timeout)
        connection.row_factory = sqlite3.Row
        return connection

    def entries(self, user_id, statuses, currency=None, limit=200):
        marks = ",".join("?" for _ in statuses)
        sql = ("SELECT UPPER(currency) currency,UPPER(COALESCE(network,'')) network,crypto_address,"
               "MAX(created_at) last_at,COUNT(*) uses FROM orders "
               "WHERE user_id=? AND crypto_address IS NOT NULL AND TRIM(crypto_address)!='' "
               f"AND LOWER(COALESCE(status,'')) IN ({marks})")
        args = [user_id, *statuses]
        if currency:
            sql += " AND UPPER(currency)=?"
            args.append(currency)
        sql += (" GROUP BY UPPER(currency),UPPER(COALESCE(network,'')),crypto_address "
                "ORDER BY last_at DESC LIMIT ?")
        args.append(limit)
        with self._c() as c:
            rows = c.execute(sql, args).fetchall()
            try:
                notes = c.execute(
                    "SELECT currency,network,address,label,hidden "
                    "FROM client_address_notes WHERE user_id=?",
                    (user_id,),).fetchall()
            except sqlite3.OperationalError as exc:
                # Older SQLite snapshots predate address-book notes.  Their
                # delivered-order history remains useful and owner-scoped;
                # treat only this absent optional table as an empty overlay.
                if "no such table: client_address_notes" not in str(exc):
                    raise
                notes = []
            return [dict(r) for r in rows], [dict(r) for r in notes]

    def deliveries(self, user_id, statuses, limit):
        marks = ",".join("?" for _ in statuses)
        with self._c() as c:
            rows = c.execute(
                "SELECT order_id,currency,COALESCE(network,'') network,crypto_address,"
                "agreed_crypto_amount,paid_btc_tx,COALESCE(updated_at,created_at) ts FROM orders "
                f"WHERE user_id=? AND LOWER(COALESCE(status,'')) IN ({marks}) "
                "ORDER BY ts DESC LIMIT ?", (user_id, *statuses, limit)).fetchall()
            return [dict(r) for r in rows]

    def upsert_note(self, user_id, currency, network, address, label, hidden, updated_at):
        with self._c() as c:
            row = c.execute(
                "SELECT label,hidden FROM client_address_notes WHERE user_id=? AND currency=? AND network=? AND address=?",
                (user_id, currency, network, address)).fetchone()
            new_label = row["label"] if row and label is None else (label or "")
            new_hidden = row["hidden"] if row and hidden is None else int(hidden or 0)
            c.execute(
                "INSERT INTO client_address_notes(user_id,currency,network,address,label,hidden,updated_at) "
                "VALUES(?,?,?,?,?,?,?) ON CONFLICT(user_id,currency,network,address) DO UPDATE SET "
                "label=excluded.label,hidden=excluded.hidden,updated_at=excluded.updated_at",
                (user_id, currency, network, address, new_label, new_hidden, updated_at))
            c.commit()


class PostgresAddressBookStore(SQLiteAddressBookStore):
    def __init__(self, dsn):
        self.dsn = dsn

    def _c(self):
        import psycopg
        return psycopg.connect(self.dsn, row_factory=psycopg.rows.dict_row)

    def entries(self, user_id, statuses, currency=None, limit=200):
        sql = ("SELECT UPPER(currency) currency,UPPER(COALESCE(network,'')) network,crypto_address,"
               "MAX(created_at) last_at,COUNT(*) uses FROM orders "
               "WHERE user_id=%s AND crypto_address IS NOT NULL AND BTRIM(crypto_address)!='' "
               "AND LOWER(COALESCE(status,''))=ANY(%s)")
        args = [user_id, list(statuses)]
        if currency:
            sql += " AND UPPER(currency)=%s"
            args.append(currency)
        sql += (" GROUP BY UPPER(currency),UPPER(COALESCE(network,'')),crypto_address "
                "ORDER BY last_at DESC LIMIT %s")
        args.append(limit)
        with self._c() as c:
            rows = c.execute(sql, args).fetchall()
            notes = c.execute(
                "SELECT currency,network,address,label,hidden FROM client_address_notes WHERE user_id=%s",
                (user_id,)).fetchall()
            for row in rows:
                row["last_at"] = _timestamp_text(row.get("last_at"))
            return rows, notes

    def deliveries(self, user_id, statuses, limit):
        with self._c() as c:
            rows = c.execute(
                "SELECT order_id,currency,COALESCE(network,'') network,crypto_address,"
                "agreed_crypto_amount,paid_btc_tx,COALESCE(updated_at,created_at) ts FROM orders "
                "WHERE user_id=%s AND LOWER(COALESCE(status,''))=ANY(%s) "
                "ORDER BY ts DESC LIMIT %s", (user_id, list(statuses), limit)).fetchall()
            for row in rows:
                row["ts"] = _timestamp_text(row.get("ts"))
            return rows

    def upsert_note(self, user_id, currency, network, address, label, hidden, updated_at):
        with self._c() as c:
            row = c.execute(
                "SELECT label,hidden FROM client_address_notes WHERE user_id=%s AND currency=%s AND network=%s AND address=%s FOR UPDATE",
                (user_id, currency, network, address)).fetchone()
            new_label = row["label"] if row and label is None else (label or "")
            new_hidden = row["hidden"] if row and hidden is None else bool(hidden or False)
            c.execute(
                "INSERT INTO client_address_notes(user_id,currency,network,address,label,hidden,updated_at) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(user_id,currency,network,address) DO UPDATE SET "
                "label=excluded.label,hidden=excluded.hidden,updated_at=excluded.updated_at",
                (user_id, currency, network, address, new_label, new_hidden, updated_at))


def from_environment(*, sqlite_path):
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        return SQLiteAddressBookStore(sqlite_path)
    if (db_runtime.backend(url) != "postgresql" or
            os.getenv("ADDRESS_BOOK_POSTGRES_ENABLED", "").lower() not in {"1", "true", "yes"}):
        raise RuntimeError("postgres_address_book_store_not_enabled")
    return PostgresAddressBookStore(url)
