from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SQL = (ROOT / "deploy/postgres/proposals/058_e0_bot_b5_3_hardened_delivery_lifecycle.sql").read_text()


def test_hardened_delivery_uses_uuid_tokens_and_immutable_attempts():
    assert "pg_catalog.gen_random_uuid()" in SQL
    assert "md5(" not in SQL and "random()" not in SQL
    assert "CREATE TABLE public.bot_notification_delivery_attempts" in SQL
    assert "CREATE TABLE public.bot_notification_delivery_evidence" in SQL
    assert "UNIQUE(attempt_token)" in SQL
    assert "ON DELETE RESTRICT" in SQL


def test_lifecycle_is_token_and_evidence_bound():
    for signature in (
        "bot_b53_delivery_mark_sent(a_job_id bigint,a_token uuid,a_evidence_id uuid)",
        "bot_b53_delivery_retry_pre_submit(a_job_id bigint,a_token uuid,a_evidence_id uuid)",
        "bot_b53_delivery_mark_manual(a_job_id bigint,a_token uuid,a_evidence_id uuid)",
    ):
        assert signature in SQL
    assert "e.attempt_token=a_token" in SQL
    assert "e.consumed_at IS NULL" in SQL
    assert "outcome='NOT_STARTED'" in SQL
    assert "e.outcome='UNCERTAIN'" in SQL
    assert "terminal_evidence_id=e.evidence_id" in SQL


def test_transport_delivery_and_legacy_execute_are_separated():
    assert "TO obsidian_exchange_bot_delivery;" in SQL
    assert "TO obsidian_exchange_bot_transport;" in SQL
    assert "FROM PUBLIC,obsidian_exchange_bot;" in SQL
    assert "FROM obsidian_exchange_bot;" in SQL
    assert "PASSWORD" not in SQL
    assert "CREATE ROLE" not in SQL


def test_existing_sending_and_unresolved_recipient_snapshots_fail_closed():
    assert "legacy_jobs_require_expand_backfill_or_manual_reconciliation" in SQL
    assert "legacy_recipient_snapshot_required" in SQL
    assert "state IN('pending','sending','sent','manual')" in SQL
