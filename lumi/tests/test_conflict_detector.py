from lumi.app.conflict.conflict_detector import ConflictDetector
from lumi.app.schemas.provider import ProviderOutput


def test_detect_action_conflict_approve_reject():
    outputs = [
        ProviderOutput(providerId='p1', status='success', answer='ok', confidence=0.9, suggestedStatus='APPROVE', assumptions=['a'], evidenceRefs=['e']),
        ProviderOutput(providerId='p2', status='success', answer='bad', confidence=0.8, suggestedStatus='REJECT', assumptions=['a'], evidenceRefs=['e']),
    ]
    report = ConflictDetector().analyze('task', outputs)
    assert report.conflictDetected is True
    assert report.primaryConflictType == 'ACTION_CONFLICT'
    assert report.disagreementScore > 0


def test_detect_confidence_conflict():
    outputs = [
        ProviderOutput(providerId='p1', status='success', answer='ok', confidence=0.95, suggestedStatus='WAIT', assumptions=['a']),
        ProviderOutput(providerId='p2', status='success', answer='ok', confidence=0.2, suggestedStatus='WAIT', assumptions=['a']),
    ]
    report = ConflictDetector().analyze('task', outputs)
    assert report.conflictDetected is True
    assert any(f.conflictType == 'CONFIDENCE_CONFLICT' for f in report.findings)


def test_no_conflict_for_aligned_approval():
    outputs = [
        ProviderOutput(providerId='p1', status='success', answer='ok', confidence=0.9, suggestedStatus='APPROVE', assumptions=['a'], evidenceRefs=['e']),
        ProviderOutput(providerId='p2', status='success', answer='ok', confidence=0.85, suggestedStatus='APPROVE', assumptions=['a'], evidenceRefs=['e']),
    ]
    report = ConflictDetector().analyze('task', outputs)
    assert report.conflictDetected is False
    assert report.primaryConflictType == 'NONE'
