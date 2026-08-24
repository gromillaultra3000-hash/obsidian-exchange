import json
from pathlib import Path

DOC = Path('/root/docs/e0-4-read-only-remediation-rehearsal.v1.json')


def test_rehearsal_is_synthetic_and_restrictive():
    data = json.loads(DOC.read_text())
    assert data['route'] == 'E0/E0.4/READ_ONLY_REMEDIATION_REHEARSAL'
    assert data['status'] == 'BLOCKED_OWNER'
    assert data['decisionEffect'] == 'SYNTHETIC_VALIDATION_ONLY'
    assert all(value is False for value in data['authority'].values())
    assert data['rehearsal']['result'] == 'PASS'
    assert data['rehearsal']['productionFilesWritten'] is False
    assert data['rehearsal']['networkCalls'] is False


def test_rehearsal_keeps_unresolved_owner_gates():
    data = json.loads(DOC.read_text())
    assert 'no authenticated owner decision' in data['unresolved']
    assert 'no independent acceptance review' in data['unresolved']
    assert data['nextSafeRoute'] == 'E0/E0.4/OWNER_DECISION_INTAKE_REVIEW'
