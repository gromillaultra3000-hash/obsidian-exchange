import json
from pathlib import Path

DOC = Path('/root/docs/e0-4-owner-decision-intake.v1.json')


def test_intake_has_no_decision_or_authority():
    data = json.loads(DOC.read_text())
    assert data['route'] == 'E0/E0.4/OWNER_DECISION_INTAKE'
    assert data['status'] == 'BLOCKED_OWNER'
    assert data['ownerDecisionPresent'] is False
    assert data['acceptedValues']['ownerDecision'] is None
    assert all(value is False for value in data['authority'].values())


def test_intake_rejects_ambiguous_or_unbound_decisions():
    data = json.loads(DOC.read_text())
    rules = set(data['rejectionRules'])
    assert 'missing authentication' in rules
    assert 'candidate hash/path mismatch' in rules
    assert 'expiry interpreted as allowance' in rules
    assert data['nextSafeRoute'] == 'E0/E0.4/READ_ONLY_REMEDIATION_REHEARSAL'
