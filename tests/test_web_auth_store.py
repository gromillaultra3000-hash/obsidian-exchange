import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "relay"))
from repositories.web_auth_store import DuplicateIdentityError, SQLiteWebAuthStore


with tempfile.TemporaryDirectory() as td:
    path = str(Path(td) / "auth.db")
    with sqlite3.connect(path) as conn:
        conn.executescript("""
        CREATE TABLE web_users(
          id INTEGER PRIMARY KEY AUTOINCREMENT,email TEXT NOT NULL UNIQUE,
          password_hash TEXT NOT NULL,telegram_id INTEGER UNIQUE,
          telegram_username TEXT,created_at TEXT DEFAULT (datetime('now')),
          totp_secret TEXT,totp_enabled INTEGER DEFAULT 0);
        CREATE TABLE web_sessions(
          token TEXT PRIMARY KEY,web_user_id INTEGER NOT NULL,csrf_token TEXT NOT NULL,
          created_at TEXT DEFAULT (datetime('now')),expires_at TEXT NOT NULL);
        """)
    store = SQLiteWebAuthStore(path)
    uid = store.create_user("user@example.test", "hash-1")
    assert store.get_user_by_email("user@example.test")["password_hash"] == "hash-1"
    assert store.get_user_by_id(uid)["totp_enabled"] is False
    try:
        store.create_user("user@example.test", "hash-2")
        raise AssertionError("duplicate email accepted")
    except DuplicateIdentityError:
        pass
    assert store.set_password_hash(uid, "hash-2")
    assert store.set_totp(uid, "TOTPSECRET")
    assert store.link_telegram(uid, 123456, "tester")
    assert store.get_user_by_id(uid)["totp_enabled"] is True

    future = datetime.now(timezone.utc) + timedelta(hours=1)
    store.create_session("live", uid, "csrf", future)
    assert store.get_session_user("live")["csrf_token"] == "csrf"
    store.destroy_session("live")
    assert store.get_session_user("live") is None

    past = datetime.now(timezone.utc) - timedelta(hours=1)
    store.create_session("expired", uid, "csrf-old", past)
    assert store.get_session_user("expired") is None
    assert store.cleanup_expired_sessions() == 1
    assert store.set_totp(uid, None)
    assert store.get_user_by_id(uid)["totp_enabled"] is False

print("SQLite web auth repository checks: OK")
