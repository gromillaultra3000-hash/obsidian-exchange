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

from app.shadow_alert_replay import extract_alert_windows, replay_alert_sequence
from app.shadow_decision_journal import ShadowDecisionJournal
from app.shadow_ingress import ShadowSubmission
from app.shadow_metrics import project_metrics
from relay.core.shadow_observations import plan_observation

START = datetime(2026, 8, 11, 3, 0, tzinfo=timezone.utc)


def append(journal, *, trigger, at, facts, hard="HOLD", advisory="ALLOW", freshness="FRESH"):
    planned = plan_observation(
        trigger_id=trigger, observed_at=at, facts=facts,
        hard_verdict=hard, advisory_verdict=advisory, freshness=freshness)
    submission = ShadowSubmission.model_validate_json(json.dumps(planned["submission"]))
    return journal.append(
        evidence=submission.evidence, decision=submission.decision,
        recorded_at=at + timedelta(seconds=1))


def test_record_windows_fill_gaps_and_replay_critical_recovering_clear(tmp_path):
    journal = ShadowDecisionJournal(tmp_path / "shadow.jsonl")
    append(journal, trigger="PERMISSION_DRIFT", at=START + timedelta(seconds=10),
           facts={"permission_valid": False, "withdrawal_enabled": True})
    records = journal._read_locked()
    windows = extract_alert_windows(
        records, start=START, end=START + timedelta(minutes=15))
    assert len(windows) == 3
    assert [item["metrics"]["submissionCount"] for item in windows] == [1, 0, 0]
    replay = replay_alert_sequence(windows)
    assert [item["overallLevel"] for item in replay["projections"]] == [
        "CRITICAL", "WARN", "CLEAR"]
    assert replay["finalLevel"] == "CLEAR"
    assert replay["actionAllowed"] is False


def test_latency_buckets_are_bounded_and_slow_count_is_per_submission(tmp_path):
    journal = ShadowDecisionJournal(tmp_path / "shadow.jsonl")
    for minute, bucket in enumerate(("S1_3", "OVER_3S", "TIMEOUT")):
        append(journal, trigger="ADVISORY_UNAVAILABLE",
               at=START + timedelta(minutes=minute),
               facts={"failure_class": "TIMEOUT", "latency_bucket": bucket})
    windows = extract_alert_windows(
        journal._read_locked(), start=START, end=START + timedelta(minutes=5))
    assert windows[0]["slowAdvisoryCount"] == 3
    result = replay_alert_sequence(windows)
    assert result["projections"][0]["overallLevel"] == "WARN"


def test_replay_is_byte_deterministic_and_chunk_state_is_equivalent(tmp_path):
    journal = ShadowDecisionJournal(tmp_path / "shadow.jsonl")
    append(journal, trigger="PERMISSION_DRIFT", at=START + timedelta(seconds=1),
           facts={"permission_valid": False, "withdrawal_enabled": False})
    windows = extract_alert_windows(
        journal._read_locked(), start=START, end=START + timedelta(minutes=15))
    whole = replay_alert_sequence(windows)
    assert json.dumps(whole, sort_keys=True) == json.dumps(
        replay_alert_sequence(windows), sort_keys=True)
    first = replay_alert_sequence(windows[:2])
    last = replay_alert_sequence(windows[2:], previous=first["finalState"])
    assert last["projections"] == whole["projections"][2:]
    assert last["finalState"] == whole["finalState"]


def test_unaligned_bounds_omission_and_sequence_gap_fail_closed(tmp_path):
    journal = ShadowDecisionJournal(tmp_path / "shadow.jsonl")
    append(journal, trigger="CONNECTOR_DEGRADED", at=START + timedelta(seconds=10),
           facts={"failure_count": 1, "reachable": False})
    records = journal._read_locked()
    with pytest.raises(ValueError, match="align"):
        extract_alert_windows(records, start=START + timedelta(seconds=1),
                              end=START + timedelta(minutes=5))
    with pytest.raises(ValueError, match="omit"):
        extract_alert_windows(records, start=START + timedelta(minutes=5),
                              end=START + timedelta(minutes=10))
    broken = [dict(records[0], sequence=4), dict(records[0], sequence=6)]
    with pytest.raises(ValueError, match="sequence"):
        extract_alert_windows(broken, start=START, end=START + timedelta(minutes=5))


def test_projection_contains_no_record_evidence_or_fact_material(tmp_path):
    journal = ShadowDecisionJournal(tmp_path / "shadow.jsonl")
    append(journal, trigger="CONNECTOR_DEGRADED", at=START + timedelta(seconds=1),
           facts={"failure_count": 2, "reachable": False})
    replay = replay_alert_sequence(extract_alert_windows(
        journal._read_locked(), start=START, end=START + timedelta(minutes=5)))
    public = json.dumps(replay, sort_keys=True).lower()
    assert all(term not in public for term in (
        "facts", "evidence", "recordid", "principal", "owner", "account"))


def test_empty_window_replay_matches_frozen_compatibility_fixture():
    expected = json.loads((
        ROOT / "contracts/e2-shadow/alert-replay-empty-window.v1.json").read_text())
    empty = {"schemaVersion": "shadow-alert-window.v1",
             "windowStart": START.isoformat(),
             "windowEnd": (START + timedelta(minutes=5)).isoformat(),
             "metrics": project_metrics([]), "slowAdvisoryCount": 0}
    assert replay_alert_sequence([empty]) == expected
