import json
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "docs" / "e0-gate-status.v1.json"
STATUSES = {"NOT_STARTED", "IN_PROGRESS", "VERIFIED", "BLOCKED_OWNER", "BLOCKED_EXTERNAL", "SUPERSEDED"}
CRITERIA = ["E0.1", "E0.2", "E0.3", "E0.4", "E0.5"]


def _load():
    return json.loads(LEDGER.read_text(encoding="utf-8"))


def test_gate_ledger_has_complete_ordered_e0_criteria():
    ledger = _load()
    assert ledger["schema"] == "obsidian-e0-gate-status.v1"
    assert (ROOT / ledger["canonicalRoadmap"]).exists()
    assert datetime.fromisoformat(ledger["observedAt"].replace("Z", "+00:00")).utcoffset() is not None
    assert ledger["observationSources"]
    assert ledger["stage"]["id"] == "E0"
    assert [item["id"] for item in ledger["stage"]["criteria"]] == CRITERIA


def test_statuses_are_closed_and_verified_requires_evidence():
    ledger = _load()
    stage = ledger["stage"]
    assert stage["status"] in STATUSES
    for criterion in stage["criteria"]:
        assert criterion["status"] in STATUSES
        assert criterion["accountableOwner"] != "unassigned"
        assert criterion["evidence"]
        for evidence in criterion["evidence"]:
            assert (ROOT / evidence).exists(), evidence
        if criterion["status"] == "VERIFIED":
            assert criterion.get("acceptance")
            assert "blocker" not in criterion
        else:
            assert criterion.get("blocker")


def test_superseded_scope_item_advances_to_first_open_criterion():
    ledger = _load()
    stage = ledger["stage"]
    first_unmet = next(item["id"] for item in stage["criteria"] if item["status"] not in {"VERIFIED", "SUPERSEDED"})
    assert stage["firstUnmetCriterion"] == first_unmet
    assert stage["status"] == "IN_PROGRESS"
    assert stage["criteria"][0]["status"] == "SUPERSEDED"
    assert first_unmet == "E0.3"
