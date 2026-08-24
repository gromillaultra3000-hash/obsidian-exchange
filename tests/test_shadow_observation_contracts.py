import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
KAIROS_ROOT = ROOT / "kairos"
for path in (str(KAIROS_ROOT), str(ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

from app.shadow_decision_journal import ShadowDecisionJournal
from app.shadow_ingress import ShadowSubmission
from app.shadow_metrics import project_metrics
from relay.core.shadow_observations import plan_observation, public_catalog

NOW = datetime(2026, 8, 11, 3, 4, 12, 345000, tzinfo=timezone.utc)


def plan(**changes):
    values = dict(
        trigger_id="CONNECTOR_DEGRADED", observed_at=NOW,
        facts={"failure_count": 2, "reachable": False},
        hard_verdict="HOLD", advisory_verdict="MANUAL", freshness="STALE")
    values.update(changes)
    return plan_observation(**values)


def test_catalog_and_empty_metrics_match_frozen_fixtures():
    catalog = json.loads((ROOT / "contracts/e2-shadow/trigger-catalog.v1.json").read_text())
    empty = json.loads((ROOT / "contracts/e2-shadow/metrics-empty.v1.json").read_text())
    assert public_catalog() == catalog
    assert project_metrics([]) == empty


def test_sampling_and_idempotency_are_deterministic_per_bucket():
    first = plan()
    repeated = plan(observed_at=NOW + timedelta(seconds=20))
    next_bucket = plan(observed_at=NOW + timedelta(minutes=5))
    changed = plan(facts={"failure_count": 3, "reachable": False})
    assert first == repeated
    assert first["bucketStart"] == "2026-08-11T03:00:00+00:00"
    assert first["observationId"].startswith("obs_")
    assert next_bucket["observationId"] != first["observationId"]
    assert changed["observationId"] != first["observationId"]
    assert ShadowSubmission.model_validate_json(
        json.dumps(first["submission"])).schemaVersion == "shadow-submission.v1"


@pytest.mark.parametrize("change", [
    {"trigger_id": "UNKNOWN"},
    {"facts": {"failure_count": 2}},
    {"facts": {"failure_count": 2, "reachable": False, "owner_id": 9}},
])
def test_unknown_trigger_or_fact_drift_fails_closed(change):
    with pytest.raises(ValueError):
        plan(**change)


@pytest.mark.parametrize("change", [
    {"facts": {"failure_count": -1, "reachable": False}},
    {"facts": {"failure_count": 1, "reachable": "yes"}},
    {"trigger_id": "MARKET_DATA_STALE",
     "facts": {"age_bucket": "raw_seconds_71", "source_count": 1}},
    {"trigger_id": "ADVISORY_UNAVAILABLE",
     "facts": {"failure_class": "traceback", "latency_bucket": "1007ms"}},
])
def test_fact_values_outside_frozen_buckets_fail_closed(change):
    with pytest.raises(ValueError, match="buckets"):
        plan(**change)


def test_metrics_only_expose_frozen_aggregate_dimensions(tmp_path):
    journal = ShadowDecisionJournal(tmp_path / "shadow.jsonl")
    first = ShadowSubmission.model_validate_json(json.dumps(plan()["submission"]))
    second = ShadowSubmission.model_validate_json(json.dumps(plan(
        trigger_id="MARKET_DATA_STALE", observed_at=NOW,
        facts={"age_bucket": "S60_299", "source_count": 2},
        hard_verdict="ALLOW", advisory_verdict="HOLD",
        freshness="STALE")["submission"]))
    journal.append(evidence=first.evidence, decision=first.decision,
                   recorded_at=NOW + timedelta(seconds=1))
    journal.append(evidence=second.evidence, decision=second.decision,
                   recorded_at=NOW + timedelta(seconds=2))
    records = journal._read_locked()
    metrics = project_metrics(records)
    assert metrics["submissionCount"] == 2
    assert metrics["bySignal"]["CONNECTOR_DEGRADED"] == 1
    assert metrics["bySignal"]["MARKET_DATA_STALE"] == 1
    assert metrics["byCombinedVerdict"] == {
        "ALLOW": 0, "HOLD": 1, "MANUAL": 1, "FREEZE": 0}
    assert metrics["hardAdvisoryDisagreementCount"] == 2
    assert metrics["advisoryTightenedCount"] == 2
    public = json.dumps(metrics, sort_keys=True).lower()
    assert all(term not in public for term in (
        "facts", "evidenceid", "recordid", "principal", "owner", "account"))


def test_metrics_reject_unknown_signal_instead_of_silently_grouping_it():
    record = {"decision": {"hardVerdict": "HOLD", "advisoryVerdict": "HOLD",
                           "combinedVerdict": "HOLD"},
              "evidence": [{"signalType": "NEW_UNVERSIONED_SIGNAL",
                            "freshness": "FRESH"}]}
    with pytest.raises(ValueError, match="evidence"):
        project_metrics([record])


def test_verified_record_read_crosses_generation_boundary(tmp_path):
    from app.shadow_journal_operations import ShadowJournalOperations
    operations = ShadowJournalOperations(tmp_path / "state" / "decisions.jsonl")
    first = ShadowSubmission.model_validate_json(json.dumps(plan()["submission"]))
    operations.active_journal().append(
        evidence=first.evidence, decision=first.decision,
        recorded_at=NOW + timedelta(seconds=1))
    operations.rotate(created_at=NOW + timedelta(seconds=2))
    second = ShadowSubmission.model_validate_json(json.dumps(plan(
        trigger_id="MARKET_DATA_STALE",
        facts={"age_bucket": "S60_299", "source_count": 1},
        hard_verdict="HOLD", advisory_verdict="HOLD")["submission"]))
    operations.active_journal().append(
        evidence=second.evidence, decision=second.decision,
        recorded_at=NOW + timedelta(seconds=3))
    records = operations.read_verified_records()
    assert [item["sequence"] for item in records] == [1, 2]
    assert project_metrics(records)["submissionCount"] == 2
