import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "relay"))

from repositories.user_profile_store import PostgresUserProfileStore, from_environment


class _Result:
    def __init__(self, row=None):
        self._row = row

    def fetchone(self):
        return self._row


class _Connection:
    def __init__(self, results=()):
        self.calls = []
        self.results = iter(results)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, args):
        self.calls.append((sql, args))
        return _Result(next(self.results, None))


def test_b5_user_profile_adapter_calls_only_bounded_functions():
    connection = _Connection(results=(None, (True,)))
    store = PostgresUserProfileStore("postgresql://unused", use_b5_acl_functions=True)
    store._c = lambda: connection

    store.upsert_user(user_id=7, username="user", first_name="A", last_name="B")
    assert store.claim_referrer(referred_id=7, referrer_id=3) is True

    assert connection.calls == [
        (
            "SELECT public.bot_b5_upsert_user(%s,%s,%s,%s)",
            (7, "user", "A", "B"),
        ),
        ("SELECT public.bot_b5_claim_referrer(%s,%s)", (7, 3)),
    ]
    assert all("INSERT INTO" not in sql and "UPDATE " not in sql for sql, _ in connection.calls)


def test_self_referral_is_denied_before_database_call():
    connection = _Connection()
    store = PostgresUserProfileStore("postgresql://unused", use_b5_acl_functions=True)
    store._c = lambda: connection
    assert store.claim_referrer(referred_id=7, referrer_id=7) is False
    assert connection.calls == []


def test_b5_adapter_gate_defaults_off_and_requires_postgres_store_gate(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://unused")
    monkeypatch.setenv("USER_PROFILE_POSTGRES_ENABLED", "1")
    monkeypatch.delenv("BOT_B5_ACL_ADAPTER_ENABLED", raising=False)
    assert from_environment(sqlite_path="unused").use_b5_acl_functions is False

    monkeypatch.setenv("BOT_B5_ACL_ADAPTER_ENABLED", "true")
    assert from_environment(sqlite_path="unused").use_b5_acl_functions is True


def test_legacy_path_remains_available_for_pre_migration_deploy():
    source = (ROOT / "relay/repositories/user_profile_store.py").read_text()
    assert "BOT_B5_ACL_ADAPTER_ENABLED" in source
    assert "INSERT INTO bot_users" in source
    assert "INSERT INTO referrals" in source
