import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
KAIROS_ROOT = ROOT / "kairos"
if str(KAIROS_ROOT) not in sys.path:
    sys.path.insert(0, str(KAIROS_ROOT))

from app.shadow_alerts import evaluate_alerts, public_policy

START = datetime(2026, 8, 11, 3, 0, tzinfo=timezone.utc)


def metrics(submissions=0, divergence=0, **signals):
    by_signal = {
        "ADVISORY_UNAVAILABLE": 0, "CONNECTOR_DEGRADED": 0,
        "MARKET_DATA_STALE": 0, "PERMISSION_DRIFT": 0,
        "PROVIDER_RATE_LIMIT": 0,
    }
    by_signal.update(signals)
    return {
        "schemaVersion": "shadow-metrics.v1", "submissionCount": submissions,
        "hardAdvisoryDisagreementCount": divergence, "bySignal": by_signal,
    }


def window(*, slow=0, value=None, start=START):
    return {
        "schemaVersion": "shadow-alert-window.v1",
        "windowStart": start.isoformat(),
        "windowEnd": (start + timedelta(minutes=5)).isoformat(),
        "metrics": value or metrics(), "slowAdvisoryCount": slow,
    }


def alarms(result):
    return {item["alarmId"]: item for item in result["alarms"]}


def test_policy_matches_frozen_fixture_and_clear_projection_is_non_executing():
    fixture = json.loads((ROOT / "contracts/e2-shadow/alert-policy.v1.json").read_text())
    assert public_policy() == fixture
    result = evaluate_alerts(window())
    assert result["overallLevel"] == "CLEAR"
    assert result["actionAllowed"] is False
    assert all(item["status"] == "CLEAR" for item in result["alarms"])


@pytest.mark.parametrize(("alarm_id", "warn", "critical"), [
    ("ADVISORY_LATENCY", window(slow=3, value=metrics(submissions=3)),
     window(slow=10, value=metrics(submissions=10))),
    ("MARKET_DATA_STALE", window(value=metrics(submissions=3, MARKET_DATA_STALE=3)),
     window(value=metrics(submissions=10, MARKET_DATA_STALE=10))),
    ("PROVIDER_RATE_LIMIT", window(value=metrics(submissions=5, PROVIDER_RATE_LIMIT=5)),
     window(value=metrics(submissions=20, PROVIDER_RATE_LIMIT=20))),
])
def test_count_thresholds_are_exact(alarm_id, warn, critical):
    assert alarms(evaluate_alerts(warn))[alarm_id]["level"] == "WARN"
    assert alarms(evaluate_alerts(critical))[alarm_id]["level"] == "CRITICAL"


def test_permission_drift_is_immediately_critical():
    result = evaluate_alerts(window(value=metrics(submissions=1, PERMISSION_DRIFT=1)))
    assert alarms(result)["PERMISSION_DRIFT"]["level"] == "CRITICAL"
    assert result["actionAllowed"] is False


@pytest.mark.parametrize(("submissions", "count", "expected"), [
    (20, 2, "CLEAR"), (20, 3, "CLEAR"), (15, 3, "WARN"),
    (20, 9, "WARN"), (20, 10, "CRITICAL"),
])
def test_divergence_requires_both_count_and_rate(submissions, count, expected):
    result = evaluate_alerts(window(value=metrics(
        submissions=submissions, divergence=count)))
    assert alarms(result)["HARD_ADVISORY_DIVERGENCE"]["level"] == expected


def test_recovery_requires_two_consecutive_healthy_windows_and_reactivation_resets():
    active = evaluate_alerts(window(value=metrics(submissions=1, PERMISSION_DRIFT=1)))
    first_clear = evaluate_alerts(
        window(start=START + timedelta(minutes=5)), active["nextState"])
    recovering = alarms(first_clear)["PERMISSION_DRIFT"]
    assert recovering == {"alarmId": "PERMISSION_DRIFT", "level": "WARN",
                          "status": "RECOVERING", "healthyWindows": 1}
    reactivated = evaluate_alerts(
        window(start=START + timedelta(minutes=10),
               value=metrics(submissions=1, PERMISSION_DRIFT=1)),
        first_clear["nextState"])
    assert alarms(reactivated)["PERMISSION_DRIFT"]["healthyWindows"] == 0
    clear_again = evaluate_alerts(
        window(start=START + timedelta(minutes=15)), reactivated["nextState"])
    final = evaluate_alerts(
        window(start=START + timedelta(minutes=20)), clear_again["nextState"])
    assert alarms(final)["PERMISSION_DRIFT"]["status"] == "CLEAR"


@pytest.mark.parametrize("mutation", [
    {"windowStart": "2026-08-11T03:01:00+00:00"},
    {"windowStart": "2026-08-11T03:00:00"},
    {"slowAdvisoryCount": -1},
    {"extra": True},
])
def test_malformed_or_unaligned_windows_fail_closed(mutation):
    value = window()
    value.update(mutation)
    with pytest.raises(ValueError):
        evaluate_alerts(value)


def test_alarm_projection_contains_no_evidence_or_identity_fields():
    public = json.dumps(evaluate_alerts(window()), sort_keys=True).lower()
    assert all(term not in public for term in (
        "facts", "evidence", "recordid", "principal", "owner", "account"))


def test_recovery_rejects_gap_or_replayed_window():
    active = evaluate_alerts(window(value=metrics(submissions=1, PERMISSION_DRIFT=1)))
    with pytest.raises(ValueError, match="consecutive"):
        evaluate_alerts(window(start=START), active["nextState"])
    with pytest.raises(ValueError, match="consecutive"):
        evaluate_alerts(window(start=START + timedelta(minutes=10)), active["nextState"])
