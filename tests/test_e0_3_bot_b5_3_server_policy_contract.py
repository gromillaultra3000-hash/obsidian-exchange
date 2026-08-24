from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SQL = (ROOT / "deploy/postgres/proposals/059_e0_bot_b5_3_server_policy_producers.sql").read_text()


def test_producers_accept_only_limit_and_capture_server_time():
    for name in ("abandoned", "montera", "payout_delays", "recalls", "winbacks"):
        assert f"bot_b59_queue_due_{name}(a_limit integer)" in SQL
    assert "a_now" not in SQL
    assert "v_now timestamptz:=clock_timestamp()" in SQL


def test_policy_is_versioned_hash_bound_and_immutable():
    assert "CREATE TABLE public.bot_notification_policy_versions" in SQL
    assert "policy_sha256 text UNIQUE NOT NULL" in SQL
    assert "approval_evidence_sha256 text NOT NULL" in SQL
    assert "notification_policy_immutable" in SQL
    assert "CHECK(effective_from>=approved_at)" in SQL
    assert "winback_discount<=20" in SQL
    assert "winback_valid_hours BETWEEN 1 AND 720" in SQL


def test_every_job_binds_recipient_policy_time_and_attempt_limit():
    inserts = [chunk for chunk in SQL.split("INSERT INTO public.bot_notification_jobs")[1:]]
    assert len(inserts) == 6
    for chunk in inserts:
        columns = chunk.split(")", 1)[0]
        for name in ("recipient_id", "policy_id", "policy_version", "eligibility_at", "max_attempts"):
            assert name in columns
    assert "r.order_id::text||':'||v_admin::text" in SQL


def test_background_login_is_execute_only_and_old_producers_are_revoked():
    assert "TO obsidian_exchange_bot_background;" in SQL
    assert "FROM PUBLIC,obsidian_exchange_bot;" in SQL
    assert "FROM obsidian_exchange_bot;" in SQL
    assert "PASSWORD" not in SQL and "CREATE ROLE" not in SQL
    assert "GRANT INSERT(kind,dedupe_key,payload,recipient_id,policy_id,policy_version,eligibility_at,max_attempts)" in SQL
