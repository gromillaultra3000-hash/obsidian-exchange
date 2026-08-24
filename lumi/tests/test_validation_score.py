from lumi.app.validation.validation_score import ValidationScorer
from lumi.app.schemas.provider import ProviderOutput
from lumi.app.schemas.validation import ValidationIssue


def issue(sev):
    return ValidationIssue(issueId='x', code='X', severity=sev, message='m')


def test_no_issues_high_score():
    score = ValidationScorer().score([], ProviderOutput(providerId='test', status='success', answer='Valid answer', confidence=0.8, suggestedStatus='APPROVE', assumptions=['a'], evidenceRefs=['e']))
    assert score >= 0.9


def test_warning_reduces_score():
    score = ValidationScorer().score([issue('warning')], ProviderOutput(providerId='test', status='success', answer='Valid', confidence=0.8))
    assert score < 1.0


def test_critical_reduces_score_to_rejected():
    score = ValidationScorer().score([issue('critical')], ProviderOutput(providerId='test', status='success', answer='I executed the action', confidence=0.9))
    assert score < 0.45


def test_score_clamped_zero_to_one():
    score = ValidationScorer().score([issue('critical'), issue('critical'), issue('critical')], ProviderOutput(providerId='test', status='success', answer='test', confidence=0.5))
    assert 0.0 <= score <= 1.0
