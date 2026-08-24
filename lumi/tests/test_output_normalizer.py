from lumi.app.validation.output_normalizer import OutputNormalizer
from lumi.app.schemas.provider import ProviderProfile, ProviderOutput


def profile(pid='normalizer-test'):
    return ProviderProfile(providerId=pid, displayName=pid, providerType='mock', apiFormat='json', enabled=True, roles=['reviewer'], capabilities=['text_reasoning'], costProfile={}, latencyProfile={}, reliabilityScore=1.0)


def test_normalize_provider_output_object():
    result = OutputNormalizer().normalize_provider_output(ProviderOutput(providerId='normalizer-test', status='success', answer='Test answer', confidence=0.9, suggestedStatus='APPROVE'), profile())
    assert result.output.status == 'success'
    assert result.output.answer == 'Test answer'
    assert result.output.confidence == 0.9


def test_normalize_dict():
    result = OutputNormalizer().normalize_provider_output({'providerId':'normalizer-test','status':'success','answer':'Dict answer','confidence':0.8,'suggestedStatus':'WAIT'}, profile())
    assert result.output.answer == 'Dict answer'


def test_normalize_plain_string():
    result = OutputNormalizer().normalize_provider_output('Plain string answer', profile())
    assert 'plain_string_normalized' in result.normalizationWarnings
    assert result.output.answer == 'Plain string answer'
    assert result.output.confidence == 0.5


def test_normalize_none():
    result = OutputNormalizer().normalize_provider_output(None, profile())
    assert result.output.status == 'invalid'
    assert 'none_output' in result.normalizationWarnings


def test_clamp_confidence_high_and_low():
    high = OutputNormalizer().normalize_provider_output({'providerId':'normalizer-test','status':'success','answer':'test','confidence':1.5}, profile())
    low = OutputNormalizer().normalize_provider_output({'providerId':'normalizer-test','status':'success','answer':'test','confidence':-0.5}, profile())
    assert high.output.confidence == 1.0
    assert low.output.confidence == 0.0
    assert 'confidence_clamped' in high.normalizationWarnings


def test_invalid_confidence_type_and_missing_suggested_status():
    result = OutputNormalizer().normalize_provider_output({'providerId':'normalizer-test','status':'success','answer':'test','confidence':'bad'}, profile())
    assert result.output.confidence == 0.0
    assert result.output.suggestedStatus == 'WAIT'
    assert 'invalid_confidence_type' in result.normalizationWarnings
    assert 'missing_suggested_status' in result.normalizationWarnings


def test_redact_secret_in_raw_and_answer():
    result = OutputNormalizer().normalize_provider_output({'providerId':'normalizer-test','status':'success','answer':'Using apiKey=sk-secret-123','apiKey':'sk-secret-123'}, profile())
    assert 'sk-secret-123' not in str(result.rawOutputRedacted)
    assert 'sk-secret-123' not in str(result.output.answer)
