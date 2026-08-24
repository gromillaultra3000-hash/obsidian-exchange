import json
from pathlib import Path

DOC = Path('/root/docs/e0-4-owner-gated-remediation-plan.v1.json')


def test_plan_is_documentation_only():
    data = json.loads(DOC.read_text())
    assert data['route'] == 'E0/E0.4/OWNER_GATED_REMEDIATION_PLAN'
    assert data['status'] == 'BLOCKED_OWNER'
    assert data['decisionEffect'] == 'DOCUMENTATION_ONLY_NO_AUTHORITY'
    assert all(value is False for value in data['authority'].values())
    assert len(data['workstreams']) == 4


def test_plan_preserves_owner_gates_and_restrictions():
    data = json.loads(DOC.read_text())
    assert 'provide authenticated acceptance decision for each exit artifact' in data['ownerDecisionsRequired']
    assert 'explicitly retain E0.3 restrictive deferral and prohibit 064B/064D' in data['ownerDecisionsRequired']
    assert data['nextSafeRoute'] == 'E0/E0.4/OWNER_DECISION_INTAKE'
