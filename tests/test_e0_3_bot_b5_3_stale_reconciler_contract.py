import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SQL = (ROOT / "deploy/postgres/proposals/063_e0_bot_b5_3_stale_review_reconciler.sql").read_text()
SERVICE = (ROOT / "deploy/systemd/exchange-bot-notification-reconciler.service").read_text()


def _module():
    spec = importlib.util.spec_from_file_location(
        "notification_reconciler", ROOT / "relay/bot_notification_reconciler.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_stale_path_is_manual_and_never_retry():
    assert "terminal_evidence_id IS NULL" in SQL
    assert "state='manual'" in SQL
    assert "PRE_SUBMIT_ABANDONED" in SQL
    assert "AUTHORIZED_NO_TERMINAL_EVIDENCE" in SQL
    assert "LEFT JOIN public.bot_notification_submit_authorizations" in SQL
    assert "automaticRetryAllowed',false" in SQL
    assert "state='pending'" not in SQL


def test_review_is_append_only_and_exact_attempt_bound():
    assert "UNIQUE(job_id,attempt_token)" in SQL
    assert "FOREIGN KEY(job_id,attempt_no)" in SQL
    assert "bot_b63_stale_review_immutable" in SQL
    assert "FOR UPDATE OF j,a SKIP LOCKED" in SQL


def test_uncertain_evidence_cannot_smuggle_provider_identifiers():
    section = SQL.split("bot_notification_evidence_outcome_v63_check", 1)[1].split(");", 1)[0]
    assert "provider_message_id IS NULL" in section
    assert "provider_request_id IS NULL" in section


def test_worker_is_separate_oneshot_identity_and_secret_free_output():
    source = (ROOT / "relay/bot_notification_reconciler.py").read_text()
    assert "obsidian_exchange_bot_notification_reconciler" in source
    assert "Type=oneshot" in SERVICE and "User=obsidian-bot-reconciler" in SERVICE
    assert "EnvironmentFile=/etc/obsidian-exchange/bot-notification-reconciler.env" in SERVICE
    assert "errorType" in source and "str(exc)" not in source


def test_invalid_bounds_fail_before_connect(monkeypatch):
    module = _module()
    monkeypatch.setenv("BOT_NOTIFICATION_RECONCILER_DATABASE_URL", "postgresql://synthetic")
    monkeypatch.setenv("BOT_NOTIFICATION_STALE_AFTER_SECONDS", "59")
    called = False
    def connect(_):
        nonlocal called
        called = True
    try:
        module.run_once(connect)
    except RuntimeError as exc:
        assert str(exc) == "invalid_bot_notification_stale_after_seconds"
    else:
        raise AssertionError("invalid bounds accepted")
    assert called is False
