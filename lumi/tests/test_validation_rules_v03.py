from lumi.app.validation.validation_rules import ValidationRules
from lumi.app.schemas.provider import ProviderOutput


def test_empty_success_creates_issue():
    issues = ValidationRules().check_non_empty_answer(ProviderOutput(providerId='test', status='success', answer='', confidence=0.9, suggestedStatus='APPROVE'))
    assert issues and issues[0].code == 'EMPTY_ANSWER_FOR_SUCCESS'


def test_invalid_status_dict_normalized_then_issue():
    from lumi.app.validation.output_normalizer import OutputNormalizer
    from lumi.app.schemas.provider import ProviderProfile
    p = ProviderProfile(providerId='test', displayName='test', providerType='mock', apiFormat='json', reliabilityScore=1.0)
    out = OutputNormalizer().normalize_provider_output({'providerId':'test','status':'wrong','answer':'x','confidence':0.5}, p).output
    assert out.status == 'invalid'
    issues = ValidationRules().run_all_rules(out)
    assert any(i.code == 'MISSING_ERRORS_FOR_ERROR_STATUS' for i in issues)


def test_invalid_suggested_status_creates_issue():
    issues = ValidationRules().check_schema_validity(ProviderOutput(providerId='test', status='success', answer='test', confidence=0.8, suggestedStatus='INVALID_APPROVAL'))
    assert any('SUGGESTED_STATUS' in i.code for i in issues)


def test_missing_evidence_for_approval():
    issues = ValidationRules().check_evidence_required_for_approval(ProviderOutput(providerId='test', status='success', answer='Approved', confidence=0.9, suggestedStatus='APPROVE'))
    assert issues


def test_error_status_without_errors():
    issues = ValidationRules().check_errors_required_for_error_status(ProviderOutput(providerId='test', status='error', errors=[]))
    assert issues
