from lumi.app.conflict.conflict_detector import ConflictDetector
from lumi.app.conflict.deterministic_resolver import DeterministicResolver
from lumi.app.schemas.provider import ProviderOutput
from lumi.app.schemas.validation import ValidationPipelineResult


def pipeline(ids):
    return ValidationPipelineResult(taskId='task', totalOutputs=len(ids), validOutputs=len(ids), acceptedProviderIds=ids, rejectedProviderIds=[], overallValidationStatus='valid')


def test_resolution_approve_when_no_conflict_high_confidence():
    outputs = [ProviderOutput(providerId='p1', status='success', answer='ok', confidence=0.9, suggestedStatus='APPROVE', assumptions=['a'], evidenceRefs=['e'])]
    report = ConflictDetector().analyze('task', outputs)
    res = DeterministicResolver().resolve('task', outputs, pipeline(['p1']), report)
    assert res.status == 'APPROVE'
    assert res.actionAllowed is True


def test_resolution_ask_user_on_action_conflict():
    outputs = [
        ProviderOutput(providerId='p1', status='success', answer='ok', confidence=0.9, suggestedStatus='APPROVE', assumptions=['a'], evidenceRefs=['e']),
        ProviderOutput(providerId='p2', status='success', answer='no', confidence=0.8, suggestedStatus='REJECT', assumptions=['a'], evidenceRefs=['e']),
    ]
    report = ConflictDetector().analyze('task', outputs)
    res = DeterministicResolver().resolve('task', outputs, pipeline(['p1','p2']), report)
    assert res.status == 'ASK_USER'
    assert res.userApprovalRequired is True
    assert res.actionAllowed is False


def test_resolution_wait_on_risk_conflict():
    outputs = [ProviderOutput(providerId='p1', status='success', answer='risk', confidence=0.9, suggestedStatus='APPROVE', riskFlags=['critical_risk'], assumptions=['a'], evidenceRefs=['e'])]
    report = ConflictDetector().analyze('task', outputs)
    res = DeterministicResolver().resolve('task', outputs, pipeline(['p1']), report)
    assert res.status == 'WAIT'
    assert res.riskLevel == 'high'
