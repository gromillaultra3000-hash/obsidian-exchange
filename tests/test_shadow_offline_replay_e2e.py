import inspect
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT / "kairos", ROOT / "lumi", ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from app.shadow_decision_journal import (
    GENESIS_HASH, ShadowDecisionJournal, project_record, verify_record_projection,
)
from e2_shadow_offline_replay import replay, replay_many, verify_batch
from relay.core.shadow_observations import plan_observation

NOW = datetime(2026, 8, 11, 5, 0, tzinfo=timezone.utc)


def make_plan():
    return plan_observation(
        trigger_id="CONNECTOR_DEGRADED", observed_at=NOW,
        facts={"failure_count": 3, "reachable": False},
        hard_verdict="HOLD", advisory_verdict="ALLOW", freshness="FRESH")


def run_replay(plan=None):
    return replay(
        plan or make_plan(), requested_at=NOW + timedelta(seconds=1),
        evaluated_at=NOW + timedelta(seconds=2),
        decided_at=NOW + timedelta(seconds=3),
        recorded_at=NOW + timedelta(seconds=4))


TRIGGER_CASES = [
    ("PERMISSION_DRIFT", {"permission_valid": False, "withdrawal_enabled": True}),
    ("CONNECTOR_DEGRADED", {"failure_count": 3, "reachable": False}),
    ("PROVIDER_RATE_LIMIT", {"rate_limited": True, "retry_bucket": "LT_1M"}),
    ("MARKET_DATA_STALE", {"age_bucket": "S300_899", "source_count": 1}),
    ("ADVISORY_UNAVAILABLE", {"failure_class": "TIMEOUT", "latency_bucket": "TIMEOUT"}),
]


def batch_item(index, trigger, facts):
    observed = NOW + timedelta(minutes=5 * index)
    plan = plan_observation(
        trigger_id=trigger, observed_at=observed, facts=facts,
        hard_verdict="HOLD", advisory_verdict="ALLOW", freshness="FRESH")
    return {
        "plan": plan, "requestedAt": observed + timedelta(seconds=1),
        "evaluatedAt": observed + timedelta(seconds=2),
        "decidedAt": observed + timedelta(seconds=3),
        "recordedAt": observed + timedelta(seconds=4),
    }


def test_complete_offline_replay_tightens_and_projects_without_state(tmp_path):
    before = list(tmp_path.iterdir())
    result = run_replay()
    assert list(tmp_path.iterdir()) == before
    assert result["advisoryResponse"]["advisoryVerdict"] == "MANUAL"
    assert result["dispatch"]["combinedVerdict"] == "MANUAL"
    assert result["projectedRecord"]["decision"]["combinedVerdict"] == "MANUAL"
    assert result["projectedRecord"]["sequence"] == 1
    assert result["projectedRecord"]["previousHash"] == GENESIS_HASH
    assert result["projectionOnly"] is True
    assert result["executionEffect"] == "NONE" and result["actionAllowed"] is False


def test_complete_replay_matches_frozen_fixture_exactly():
    expected = json.loads(
        (ROOT / "contracts/e2-shadow/offline-replay.v1.json").read_text())
    assert run_replay() == expected


def test_projection_is_byte_equivalent_to_real_append_format(tmp_path):
    result = run_replay()
    projected = result["projectedRecord"]
    journal = ShadowDecisionJournal(tmp_path / "decisions.jsonl")
    appended = journal.append(
        evidence=projected["evidence"], decision=projected["decision"],
        recorded_at=NOW + timedelta(seconds=4))
    assert appended == projected


def test_all_five_triggers_form_one_contiguous_head_aware_chain(tmp_path):
    items = [batch_item(index, *case) for index, case in enumerate(TRIGGER_CASES)]
    base_hash = "a" * 64
    result = replay_many(items, base_sequence=40, base_hash=base_hash)
    records = [item["projectedRecord"] for item in result["results"]]
    assert [record["sequence"] for record in records] == [41, 42, 43, 44, 45]
    assert records[0]["previousHash"] == base_hash
    assert all(records[index]["previousHash"] == records[index - 1]["recordHash"]
               for index in range(1, len(records)))
    assert result["headHash"] == records[-1]["recordHash"]
    assert result["lastSequence"] == 45 and result["projectedCount"] == 5
    assert [item["dispatch"]["combinedVerdict"] for item in result["results"]] \
        == ["FREEZE", "MANUAL", "HOLD", "HOLD", "HOLD"]
    assert result["executionEffect"] == "NONE" and result["actionAllowed"] is False

    journal = ShadowDecisionJournal(
        tmp_path / "decisions.jsonl", base_sequence=40, base_hash=base_hash)
    appended = [journal.append(
        evidence=record["evidence"], decision=record["decision"],
        recorded_at=datetime.fromisoformat(record["recordedAt"])) for record in records]
    assert appended == records
    assert journal.verify()["headHash"] == result["headHash"]


def test_exact_duplicate_is_idempotent_and_does_not_advance_head():
    item = batch_item(0, *TRIGGER_CASES[0])
    result = replay_many([item, item])
    assert result["inputCount"] == 2 and result["projectedCount"] == 1
    assert result["duplicateCount"] == 1
    assert result["duplicateObservationIds"] == [item["plan"]["observationId"]]
    assert result["lastSequence"] == 1
    assert result["headHash"] == result["results"][0]["projectedRecord"]["recordHash"]


def test_head_aware_duplicate_batch_matches_frozen_fixture_exactly():
    item = batch_item(0, *TRIGGER_CASES[1])
    expected = json.loads(
        (ROOT / "contracts/e2-shadow/offline-batch.v1.json").read_text())
    assert replay_many(
        [item, item], base_sequence=40, base_hash="a" * 64) == expected


def test_frozen_batch_strict_verification_matches_frozen_result():
    batch = json.loads(
        (ROOT / "contracts/e2-shadow/offline-batch.v1.json").read_text())
    expected = json.loads((
        ROOT / "contracts/e2-shadow/offline-batch-verification.v1.json").read_text())
    assert verify_batch(batch) == expected


def test_whole_batch_equals_two_resumed_chunks():
    items = [batch_item(index, *case) for index, case in enumerate(TRIGGER_CASES)]
    whole = replay_many(items, base_sequence=40, base_hash="a" * 64)
    first = replay_many(items[:2], base_sequence=40, base_hash="a" * 64)
    second = replay_many(
        items[2:], base_sequence=first["lastSequence"], base_hash=first["headHash"])
    assert [item["projectedRecord"] for item in whole["results"]] == [
        *[item["projectedRecord"] for item in first["results"]],
        *[item["projectedRecord"] for item in second["results"]],
    ]
    assert second["lastSequence"] == whole["lastSequence"]
    assert second["headHash"] == whole["headHash"]
    assert verify_batch(whole)["valid"] is True
    assert verify_batch(first)["valid"] is True
    assert verify_batch(second)["valid"] is True


@pytest.mark.parametrize("mutation", [
    lambda value: value.update({"headHash": "0" * 64}),
    lambda value: value.update({"projectedCount": 2}),
    lambda value: value.update({"actionAllowed": True}),
    lambda value: value["duplicateObservationIds"].__setitem__(0, "obs_" + "0" * 64),
    lambda value: value["results"][0]["dispatch"].update({"combinedVerdict": "ALLOW"}),
    lambda value: value["results"][0]["projectedRecord"].update({"sequence": 99}),
    lambda value: value["results"][0]["projectedRecord"].update({"recordHash": "0" * 64}),
    lambda value: value.update({"extra": True}),
])
def test_batch_tamper_matrix_fails_closed(mutation):
    value = json.loads(
        (ROOT / "contracts/e2-shadow/offline-batch.v1.json").read_text())
    mutation(value)
    with pytest.raises((ValueError, TypeError)):
        verify_batch(value)


def test_duplicate_observation_with_decision_time_drift_fails_closed():
    first = batch_item(0, *TRIGGER_CASES[0])
    changed = dict(first)
    changed["decidedAt"] = first["decidedAt"] + timedelta(seconds=1)
    changed["recordedAt"] = first["recordedAt"] + timedelta(seconds=1)
    with pytest.raises(ValueError, match="duplicate observation drift"):
        replay_many([first, changed])


@pytest.mark.parametrize(("sequence", "head"), [
    (-1, GENESIS_HASH), (True, GENESIS_HASH), (0, "x" * 64), (0, "0" * 63),
])
def test_invalid_batch_head_fails_before_projection(sequence, head):
    with pytest.raises(ValueError, match="base"):
        replay_many([batch_item(0, *TRIGGER_CASES[0])],
                    base_sequence=sequence, base_hash=head)


@pytest.mark.parametrize("mutation", [
    lambda value: value.update({"observationId": "obs_" + "0" * 64}),
    lambda value: value["submission"]["evidence"][0]["facts"].update({"failure_count": "3"}),
    lambda value: value.update({"extra": True}),
])
def test_plan_drift_fails_before_projection(mutation):
    value = json.loads(json.dumps(make_plan()))
    mutation(value)
    with pytest.raises((ValueError, TypeError)):
        run_replay(value)


def test_replay_and_projection_sources_have_no_io_network_or_execution_surface():
    sources = (inspect.getsource(replay).lower() + inspect.getsource(replay_many).lower()
               + inspect.getsource(verify_batch).lower()
               + inspect.getsource(project_record).lower()
               + inspect.getsource(verify_record_projection).lower())
    assert all(term not in sources for term in (
        "open(", "os.", "pathlib", "requests", "urllib", "http://", "https://",
        "socket", "subprocess", "append(", "write", "trade", "order", "execute"))
