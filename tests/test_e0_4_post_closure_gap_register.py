import json
from pathlib import Path

DOC = Path('/root/docs/e0-4-post-closure-gap-register.v1.json')


def test_gap_register_is_restrictive_and_complete():
    data = json.loads(DOC.read_text())
    assert data['route'] == 'E0/E0.4/POST_CLOSURE_GAP_REGISTER'
    assert data['status'] == 'BLOCKED_OWNER'
    assert all(value is False for value in data['authority'].values())
    assert len(data['confirmedGaps']) == 8
    assert len(data['evidence']) == 8
    assert data['nextSafeRoute'] == 'E0/E0.4/OWNER_GATED_REMEDIATION_PLAN'
