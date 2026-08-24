"""Persistence boundary for dashboard identities and sessions."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Protocol

from core import db_runtime


class DuplicateIdentityError(RuntimeError):
    """A unique email or Telegram identity is already linked."""


class WebAuthStore(Protocol):
    def get_user_by_email(self, email: str) -> dict[str, Any] | None: ...
    def get_user_by_id(self, user_id: int) -> dict[str, Any] | None: ...
    def get_user_by_telegram_id(self, telegram_id: int) -> dict[str, Any] | None: ...
    def create_user(self, email: str, password_hash: str) -> int: ...
    def create_session(self, token: str, user_id: int, csrf_token: str,
                       expires_at: datetime) -> None: ...
    def destroy_session(self, token: str) -> None: ...
    def get_session_user(self, token: str) -> dict[str, Any] | None: ...
    def set_totp(self, user_id: int, secret: str | None) -> bool: ...
    def set_password_hash(self, user_id: int, password_hash: str) -> bool: ...
    def link_telegram(self, user_id: int, telegram_id: int,
                      telegram_username: str | None) -> bool: ...
    def cleanup_expired_sessions(self) -> int: ...


_EMAIL_FIELDS = ("id", "email", "password_hash", "telegram_id",
                 "telegram_username", "totp_secret", "totp_enabled")
_ID_FIELDS = ("id", "email", "telegram_id", "telegram_username",
              "totp_secret", "totp_enabled")


def _dict(fields, row):
    if not row:
        return None
    item = dict(zip(fields, row))
    item["totp_enabled"] = bool(item["totp_enabled"])
    return item


class SQLiteWebAuthStore:
    def __init__(self, path: str, *, timeout: float = 5):
        self.path, self.timeout = path, timeout

    def _connect(self):
        return db_runtime.sqlite_connect(self.path, timeout=self.timeout)

    def get_user_by_email(self, email: str):
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id,email,password_hash,telegram_id,telegram_username,"
                "totp_secret,totp_enabled FROM web_users WHERE email=?", (email,)
            ).fetchone()
        return _dict(_EMAIL_FIELDS, row)

    def get_user_by_id(self, user_id: int):
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id,email,telegram_id,telegram_username,totp_secret,"
                "totp_enabled FROM web_users WHERE id=?", (int(user_id),)
            ).fetchone()
        return _dict(_ID_FIELDS, row)

    def get_user_by_telegram_id(self, telegram_id: int):
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id,email,telegram_id,telegram_username,totp_secret,"
                "totp_enabled FROM web_users WHERE telegram_id=?", (int(telegram_id),)
            ).fetchone()
        return _dict(_ID_FIELDS, row)

    def create_user(self, email: str, password_hash: str) -> int:
        import sqlite3
        try:
            with self._connect() as conn:
                cur = conn.execute("INSERT INTO web_users(email,password_hash) VALUES(?,?)",
                                   (email, password_hash))
                conn.commit()
                return int(cur.lastrowid)
        except sqlite3.IntegrityError as exc:
            raise DuplicateIdentityError("web_identity_conflict") from exc

    def create_session(self, token: str, user_id: int, csrf_token: str,
                       expires_at: datetime) -> None:
        value = expires_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        with self._connect() as conn:
            conn.execute("INSERT INTO web_sessions(token,web_user_id,csrf_token,expires_at) "
                         "VALUES(?,?,?,?)", (token, int(user_id), csrf_token, value))
            conn.commit()

    def destroy_session(self, token: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM web_sessions WHERE token=?", (token,))
            conn.commit()

    def get_session_user(self, token: str):
        with self._connect() as conn:
            row = conn.execute(
                "SELECT u.id,u.email,u.telegram_id,u.telegram_username,s.csrf_token,"
                "u.totp_enabled FROM web_sessions s JOIN web_users u "
                "ON u.id=s.web_user_id WHERE s.token=? AND s.expires_at>datetime('now')",
                (token,)).fetchone()
        return _dict(("id", "email", "telegram_id", "telegram_username",
                      "csrf_token", "totp_enabled"), row)

    def _user_update(self, sql: str, params: tuple) -> bool:
        with self._connect() as conn:
            cur = conn.execute(sql, params)
            conn.commit()
            return cur.rowcount == 1

    def set_totp(self, user_id: int, secret: str | None) -> bool:
        return self._user_update(
            "UPDATE web_users SET totp_secret=?,totp_enabled=? WHERE id=?",
            (secret, int(secret is not None), int(user_id)))

    def set_password_hash(self, user_id: int, password_hash: str) -> bool:
        return self._user_update("UPDATE web_users SET password_hash=? WHERE id=?",
                                 (password_hash, int(user_id)))

    def link_telegram(self, user_id: int, telegram_id: int,
                      telegram_username: str | None) -> bool:
        import sqlite3
        try:
            return self._user_update(
                "UPDATE web_users SET telegram_id=?,telegram_username=? WHERE id=?",
                (int(telegram_id), telegram_username, int(user_id)))
        except sqlite3.IntegrityError as exc:
            raise DuplicateIdentityError("telegram_identity_conflict") from exc

    def cleanup_expired_sessions(self) -> int:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM web_sessions WHERE expires_at<datetime('now')")
            conn.commit()
            return cur.rowcount


class PostgresWebAuthStore:
    def __init__(self, dsn: str):
        self.dsn = dsn

    def _connect(self):
        import psycopg
        from psycopg.rows import dict_row
        return psycopg.connect(self.dsn, row_factory=dict_row)

    def _user(self, where: str, value):
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT id,email,password_hash,telegram_id,telegram_username,"
                        "totp_secret,totp_enabled FROM web_users WHERE " + where, (value,))
            row = cur.fetchone()
            return dict(row) if row else None

    def get_user_by_email(self, email: str):
        return self._user("email=%s", email)

    def get_user_by_id(self, user_id: int):
        item = self._user("id=%s", int(user_id))
        if item:
            item.pop("password_hash", None)
        return item

    def get_user_by_telegram_id(self, telegram_id: int):
        item = self._user("telegram_id=%s", int(telegram_id))
        if item:
            item.pop("password_hash", None)
        return item

    def create_user(self, email: str, password_hash: str) -> int:
        import psycopg
        try:
            with self._connect() as conn, conn.cursor() as cur:
                cur.execute("INSERT INTO web_users(email,password_hash) VALUES(%s,%s) RETURNING id",
                            (email, password_hash))
                return int(cur.fetchone()["id"])
        except psycopg.errors.UniqueViolation as exc:
            raise DuplicateIdentityError("web_identity_conflict") from exc

    def create_session(self, token: str, user_id: int, csrf_token: str,
                       expires_at: datetime) -> None:
        with self._connect() as conn:
            conn.execute("INSERT INTO web_sessions(token,web_user_id,csrf_token,expires_at) "
                         "VALUES(%s,%s,%s,%s)",
                         (token, int(user_id), csrf_token, expires_at))

    def destroy_session(self, token: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM web_sessions WHERE token=%s", (token,))

    def get_session_user(self, token: str):
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT u.id,u.email,u.telegram_id,u.telegram_username,s.csrf_token,"
                        "u.totp_enabled FROM web_sessions s JOIN web_users u "
                        "ON u.id=s.web_user_id WHERE s.token=%s AND s.expires_at>now()", (token,))
            row = cur.fetchone()
            return dict(row) if row else None

    def _update(self, sql: str, params: tuple) -> bool:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.rowcount == 1

    def set_totp(self, user_id: int, secret: str | None) -> bool:
        return self._update("UPDATE web_users SET totp_secret=%s,totp_enabled=%s WHERE id=%s",
                            (secret, secret is not None, int(user_id)))

    def set_password_hash(self, user_id: int, password_hash: str) -> bool:
        return self._update("UPDATE web_users SET password_hash=%s WHERE id=%s",
                            (password_hash, int(user_id)))

    def link_telegram(self, user_id: int, telegram_id: int,
                      telegram_username: str | None) -> bool:
        import psycopg
        try:
            return self._update("UPDATE web_users SET telegram_id=%s,telegram_username=%s WHERE id=%s",
                                (int(telegram_id), telegram_username, int(user_id)))
        except psycopg.errors.UniqueViolation as exc:
            raise DuplicateIdentityError("telegram_identity_conflict") from exc

    def cleanup_expired_sessions(self) -> int:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM web_sessions WHERE expires_at<now()")
            return cur.rowcount


def from_environment(*, sqlite_path: str) -> WebAuthStore:
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        return SQLiteWebAuthStore(sqlite_path)
    if (db_runtime.backend(url) != "postgresql" or
            os.getenv("WEB_AUTH_POSTGRES_ENABLED", "").strip().lower()
            not in {"1", "true", "yes"}):
        raise RuntimeError("postgres_web_auth_store_not_enabled")
    return PostgresWebAuthStore(url)
