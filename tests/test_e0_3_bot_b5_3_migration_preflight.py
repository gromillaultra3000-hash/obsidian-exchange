import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def module():
    spec = importlib.util.spec_from_file_location(
        "b64", ROOT / "deploy/postgres/check_b64_notification_migration.py")
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def test_plan_has_ordered_safety_and_asymmetric_rollback():
    plan = json.loads((ROOT / "docs/e0-3-bot-b5-3-production-migration-plan.v1.json").read_text())
    assert [item["id"] for item in plan["orderedPhases"]] == [
        "064A", "064B", "064C", "064D", "064E", "064F", "064G", "064H"]
    assert plan["rollback"]["destructiveDownMigration"] is False
    assert "repair forward" in plan["rollback"]["afterFirstV2Submit"]
    assert plan["productionAuthorization"] is False


def test_checker_is_read_only_aggregate_and_secret_free():
    source = (ROOT / "deploy/postgres/check_b64_notification_migration.py").read_text()
    assert "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY" in source
    assert "payload->>'user_id'" in source
    for forbidden in ("SELECT id,", "payload::text", "str(exc)", "recipient_id", "--dsn"):
        assert forbidden not in source


def test_cutover_requires_zero_pending_and_sending():
    source = (ROOT / "deploy/postgres/check_b64_notification_migration.py").read_text()
    assert 'blockers.append("LEGACY_PENDING_DRAINED")' in source
    assert 'blockers.append("LEGACY_SENDING_RECONCILED")' in source
    assert 'blockers.append("LEGACY_MONTERA_ADMIN_RECIPIENT_PROVEN")' in source
    assert '"status": "IN_PROGRESS"' in source
    assert "unverifiedGates" in source
