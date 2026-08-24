from lumi.app.validation.output_normalizer import OutputNormalizer
from lumi.app.validation.output_validator import OutputValidator
from lumi.app.schemas.provider import ProviderProfile, ProviderOutput


def profile(pid='test'):
    return ProviderProfile(providerId=pid, displayName=pid, providerType='mock', apiFormat='json', reliabilityScore=1.0)


def validate(output):
    return OutputValidator().validate(OutputNormalizer().normalize_provider_output(output, profile(output.providerId)))


def test_valid_output():
    result = validate(ProviderOutput(providerId='test', status='success', answer='Valid answer with evidence', confidence=0.85, suggestedStatus='APPROVE', assumptions=['a'], evidenceRefs=['e']))
    assert result.validationStatus == 'valid'
    assert not result.rejected


def test_empty_success_rejected_or_degraded():
    result = validate(ProviderOutput(providerId='test', status='success', answer='', confidence=0.9, suggestedStatus='APPROVE'))
    assert result.validationStatus in ['degraded','rejected']
    assert result.rejected


def test_unsafe_execution_claim_rejected():
    result = validate(ProviderOutput(providerId='test', status='success', answer='I deployed to production', confidence=0.95, suggestedStatus='APPROVE'))
    assert result.rejected


def test_secret_like_content_rejected():
    result = validate(ProviderOutput(providerId='test', status='success', answer='api_key=sk-secret-123', confidence=0.9))
    assert result.rejected


def test_approve_without_evidence_degraded_or_rejected():
    result = validate(ProviderOutput(providerId='test', status='success', answer='Approved', confidence=0.88, suggestedStatus='APPROVE'))
    assert result.validationStatus in ['degraded','rejected']
