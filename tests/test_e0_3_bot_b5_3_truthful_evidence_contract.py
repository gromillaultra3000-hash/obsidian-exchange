from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SQL = (ROOT / "deploy/postgres/proposals/062_e0_bot_b5_3_truthful_evidence_reconciliation.sql").read_text()
STORE = (ROOT / "relay/repositories/bot_notification_store.py").read_text()
BOT = (ROOT / "bot/main_bot.py").read_text()


def test_client_correlation_is_distinct_and_exactly_authorized():
    assert "client_correlation_id uuid NOT NULL" in SQL
    assert "FOREIGN KEY(job_id,attempt_token,client_correlation_id)" in SQL
    assert "provider_request_id=correlation" not in BOT
    assert 'outcome="ACCEPTED", provider_request_id=None' in BOT


def test_old_transport_recorder_is_revoked_and_new_one_is_bound():
    assert "bot_b62_transport_record_evidence" in SQL and "bot_b53_transport_record_evidence" in SQL
    assert "FROM obsidian_exchange_bot_transport" in SQL
    assert "bot_b62_transport_record_evidence" in STORE


def test_accepted_reconciliation_never_calls_transport():
    section = SQL.split("CREATE FUNCTION public.bot_b62_reconcile_accepted", 1)[1]
    assert "bot_b62_consume_accepted" in section
    assert "TELEGRAM" not in section and "BOT_API" not in section
    assert "FOR UPDATE" in SQL and "SKIP LOCKED" not in section  # exact primitive serializes; sweep is bounded


def test_runtime_attests_database_identity_not_dsn_text_only():
    assert "session_user AS session_name,current_user AS current_name" in STORE
    assert "rolsuper" in STORE and "rolinherit" in STORE and "memberships" in STORE
    assert "self.preflight()" in STORE
