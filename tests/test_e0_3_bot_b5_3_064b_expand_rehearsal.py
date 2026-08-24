import json
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "deploy/postgres/rehearsal"
LEGACY = ROOT / "deploy/postgres/023_bot_notification_jobs.sql"


def _sql(name):
    return (PACKAGE / name).read_text()


def test_064b_bundle_is_additive_and_not_a_production_migration():
    expand = _sql("064b_expand_transaction.sql")
    indexes = _sql("064b_expand_indexes.sql")
    rollback = _sql("064b_rollback_transaction.sql")
    assert "REHEARSAL ONLY" in expand
    assert "NOT A PRODUCTION MIGRATION" in expand
    assert "CREATE ROLE" not in expand
    assert "PASSWORD" not in expand
    assert "GRANT " not in expand
    assert "NOT VALID" in expand
    assert "lifecycle_version smallint" in expand
    assert "ADD COLUMN recipient_id bigint" in expand
    assert "DROP CONSTRAINT bot_notification_jobs_state_check" not in expand
    assert "SET recipient_id=(payload->>'user_id')" not in expand
    assert "CREATE INDEX CONCURRENTLY" in indexes
    assert "BEGIN" not in indexes and "COMMIT" not in indexes
    assert "064b_rollback_forbidden_after_v2_submit" in rollback
    assert "DROP CONSTRAINT bot_notification_attempt_terminal_evidence_v2_fk" in rollback
    assert "DROP TABLE public.bot_notification_delivery_evidence" in rollback
    assert "DROP TABLE public.bot_notification_delivery_attempts" in rollback


def test_064b_bundle_is_bound_to_real_legacy_schema_and_plan_contract():
    legacy = LEGACY.read_text()
    plan = json.loads(
        (ROOT / "docs/e0-3-bot-b5-3-production-migration-plan.v1.json").read_text()
    )
    phase = next(item for item in plan["orderedPhases"] if item["id"] == "064B")
    assert "bot_notification_jobs" in legacy
    assert "state IN('pending','sending','sent')" in legacy
    assert phase["requirements"] == [
        "nullable lifecycleVersion and v2 columns",
        "new tables and versioned functions",
        "NOT VALID conditional constraints",
        "concurrent indexes outside transactions",
        "old runtime remains compatible",
    ]
    assert all(token in _sql("064b_expand_transaction.sql") for token in (
        "bot_notification_delivery_attempts",
        "bot_notification_delivery_evidence",
        "bot_b53_v2_delivery_claim",
        "bot_b53_v2_transport_record_evidence",
    ))


def test_064b_rehearsal_is_optional_without_a_test_database():
    if not os.getenv("TEST_POSTGRES_DSN"):
        print("E0.3 B5.3 064B disposable rehearsal: skipped")
