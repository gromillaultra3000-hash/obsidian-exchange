import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "relay"))

from repositories.bot_notification_store import (
    PostgresB5BotNotificationStore,
    PostgresBotNotificationStore,
    from_environment,
)


class _Result:
    def __init__(self, row):
        self.row = row

    def fetchone(self):
        return self.row


class _Connection:
    def __init__(self, rows):
        self.rows = iter(rows)
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, sql, args):
        self.calls.append((sql, args))
        return _Result(next(self.rows))


def test_all_eight_b53_methods_call_only_bounded_functions():
    now = datetime(2026, 8, 16, tzinfo=timezone.utc)
    rows = [
        {"result": 1}, {"result": 2}, {"result": 3}, {"result": 4},
        {"result": 5},
        {"id": 8, "kind": "recall", "dedupe_key": "7", "payload": '{"user_id":7}', "attempts": 1},
        {"result": True}, {"result": False},
    ]
    connection = _Connection(rows)
    store = PostgresB5BotNotificationStore("postgresql://unused")
    store._c = lambda: connection

    assert store.queue_due_recalls(now=now, limit=10) == 1
    assert store.queue_due_montera(now=now, limit=11) == 2
    assert store.queue_due_abandoned(now=now, limit=12) == 3
    assert store.queue_due_payout_delays(warn_minutes=15, now=now, limit=13) == 4
    assert store.queue_due_winbacks(discount=5, valid_hours=72, now=now, limit=14) == 5
    assert store.claim_notification() == {
        "id": 8, "kind": "recall", "dedupe_key": "7",
        "payload": {"user_id": 7}, "attempts": 1,
    }
    assert store.mark_notification_sent(8) is True
    assert store.retry_notification(9) is False

    expected = [
        "bot_b5_queue_due_recalls", "bot_b5_queue_due_montera",
        "bot_b5_queue_due_abandoned", "bot_b5_queue_due_payout_delays",
        "bot_b5_queue_due_winbacks", "bot_b5_notification_claim",
        "bot_b5_notification_mark_sent", "bot_b5_notification_retry",
    ]
    assert [name for name, (sql, _args) in zip(expected, connection.calls) if name in sql] == expected
    assert all(
        token not in sql
        for sql, _args in connection.calls
        for token in ("INSERT INTO", "UPDATE ", "DELETE FROM", "SELECT * FROM orders")
    )


def test_acl_mode_disables_noncanonical_direct_enqueue_methods():
    store = PostgresB5BotNotificationStore("postgresql://unused")
    for method in (
        store.queue_recall, store.queue_montera, store.queue_abandoned,
        store.queue_payout_delay, store.queue_winback,
    ):
        try:
            method()
        except RuntimeError as exc:
            assert str(exc) == "bot_notification_direct_enqueue_disabled_in_b5_acl_mode"
        else:
            raise AssertionError("direct enqueue unexpectedly enabled")


def test_factory_gate_is_explicit_and_default_off(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://unused")
    monkeypatch.setenv("BOT_NOTIFICATION_POSTGRES_ENABLED", "1")
    monkeypatch.delenv("BOT_NOTIFICATION_B5_ACL_ADAPTER_ENABLED", raising=False)
    assert type(from_environment(sqlite_path="unused")) is PostgresBotNotificationStore

    monkeypatch.setenv("BOT_NOTIFICATION_B5_ACL_ADAPTER_ENABLED", "yes")
    assert type(from_environment(sqlite_path="unused")) is PostgresB5BotNotificationStore


def test_invalid_kind_is_denied_without_database_call():
    connection = _Connection([])
    store = PostgresB5BotNotificationStore("postgresql://unused")
    store._c = lambda: connection
    try:
        store.claim_notification(kind="unknown")
    except ValueError as exc:
        assert str(exc) == "invalid_bot_notification_kind"
    else:
        raise AssertionError("unknown kind accepted")
    assert connection.calls == []
