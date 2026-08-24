import json
from pathlib import Path

DOC = Path('/root/docs/e0-4-owner-decision-intake-review.v1.json')


def test_review_confirms_blocker_without_authority():
    data = json.loads(DOC.read_text())
    assert data['route'] == 'E0/E0.4/OWNER_DECISION_INTAKE_REVIEW'
    assert data['status'] == 'BLOCKED_OWNER'
    assert data['review']['ownerDecisionPresent'] is False
    assert data['decision'] == 'NO_OWNER_DECISION_CAN_BE_INFERRED'
    assert all(value is False for value in data['authority'].values())


def test_review_lists_required_missing_inputs():
    data = json.loads(DOC.read_text())
    assert 'authenticated owner identity/role' in data['missingInputs']
    assert 'exact candidate artifact paths and raw-byte hashes' in data['missingInputs']
    assert data['nextSafeRoute'] == 'E0/E0.4/RESTRICTIVE_STATUS_REPORT'
