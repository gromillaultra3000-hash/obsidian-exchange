import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "relay"))
dsn = os.getenv("TEST_POSTGRES_DSN")
if not dsn:
    print("postgres web auth store: skipped (TEST_POSTGRES_DSN unset)")
    raise SystemExit(0)

from repositories.web_auth_store import DuplicateIdentityError, PostgresWebAuthStore

store = PostgresWebAuthStore(dsn)
uid = store.create_user("user@example.test", "hash-1")
assert store.get_user_by_email("user@example.test")["password_hash"] == "hash-1"
try:
    store.create_user("user@example.test", "hash-2")
    raise AssertionError("duplicate email accepted")
except DuplicateIdentityError:
    pass
assert store.set_password_hash(uid, "hash-2")
assert store.set_totp(uid, "TOTPSECRET")
assert store.link_telegram(uid, 123456, "tester")
store.create_session("live", uid, "csrf", datetime.now(timezone.utc) + timedelta(hours=1))
assert store.get_session_user("live")["csrf_token"] == "csrf"
store.destroy_session("live")
store.create_session("expired", uid, "old", datetime.now(timezone.utc) - timedelta(hours=1))
assert store.get_session_user("expired") is None
assert store.cleanup_expired_sessions() == 1
assert store.set_totp(uid, None)
assert store.get_user_by_id(uid)["totp_enabled"] is False
print("PostgreSQL web auth repository checks: OK")
