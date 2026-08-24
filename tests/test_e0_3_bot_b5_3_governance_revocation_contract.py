from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SQL = (ROOT / "deploy/postgres/proposals/060_e0_bot_b5_3_policy_governance_recipient_revocation.sql").read_text()


def test_governance_uses_database_principal_and_append_only_events():
    assert SQL.count("session_user") >= 6
    assert "a_actor" not in SQL and "a_approved_by" not in SQL
    for table in ("policy_approvals", "policy_activation_events", "recipient_revocation_events"):
        assert f"bot_notification_{table}" in SQL
    assert SQL.count("b60_append_only") >= 4


def test_activation_is_digest_bound_serialized_and_monotonic():
    assert "policy_approval_digest_mismatch" in SQL
    assert "pg_advisory_xact_lock(530060)" in SQL
    assert "stale_activation_head" in SQL
    assert "policy_version_not_monotonic" in SQL
    assert "activation_event_id" in SQL


def test_revocation_quarantines_without_fabricating_delivery_evidence():
    assert "state='quarantined'" in SQL
    assert "possible_in_flight" in SQL
    assert "prior_state" in SQL
    revocation = SQL.split("CREATE FUNCTION public.bot_b60_set_recipient_revocation", 1)[1].split("CREATE FUNCTION", 1)[0]
    assert "bot_notification_delivery_evidence" not in revocation
    assert "bot_notification_delivery_attempts" not in revocation
    assert "state IN('pending','sending')" in revocation


def test_claim_and_enqueue_fail_closed_for_revoked_recipient():
    assert "bot_b60_reject_revoked_recipient BEFORE INSERT" in SQL
    claim = SQL.split("CREATE OR REPLACE FUNCTION public.bot_b53_delivery_claim", 1)[1]
    assert "NOT EXISTS(SELECT 1 FROM public.bot_notification_recipient_revocations" in claim


def test_runtime_principals_are_execute_only_and_no_login_is_created():
    assert "TO obsidian_exchange_bot_policy_approver" in SQL
    assert "TO obsidian_exchange_bot_reconciler" in SQL
    assert "FROM PUBLIC,obsidian_exchange_bot" in SQL
    assert "CREATE ROLE" not in SQL and "PASSWORD" not in SQL
