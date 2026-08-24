from lumi.app.core.runtime import runtime_instance
from lumi.app.schemas.task import TaskRequest
from lumi.app.schemas.provider import ProviderProfile, ProviderOutput


def add_profile(pid):
    p = ProviderProfile(providerId=pid, displayName=pid, providerType='mock', apiFormat='json', reliabilityScore=0.5)
    runtime_instance.registry.add_provider(p)
    return p


def test_mixed_outputs_pipeline():
    profiles = [add_profile(pid) for pid in ['valid-prov','degraded-prov','rejected-prov']]
    outputs = [
        ProviderOutput(providerId='valid-prov', status='success', answer='Valid answer', confidence=0.85, suggestedStatus='APPROVE', assumptions=['a'], evidenceRefs=['e']),
        ProviderOutput(providerId='degraded-prov', status='success', answer='OK', confidence=0.7, suggestedStatus='APPROVE'),
        ProviderOutput(providerId='rejected-prov', status='success', answer='I executed the action', confidence=0.95, suggestedStatus='APPROVE'),
    ]
    result = runtime_instance.validation_pipeline.validate_outputs(outputs, TaskRequest(input='test'), profiles)
    assert result.totalOutputs == 3
    assert result.rejectedOutputs >= 1
    assert 'rejected-prov' in result.rejectedProviderIds
    assert 'valid-prov' in result.acceptedProviderIds


def test_pipeline_handles_string_output():
    p = add_profile('string-prov')
    result = runtime_instance.validation_pipeline.validate_outputs(['just a string output'], TaskRequest(input='test'), [p])
    assert result.totalOutputs == 1
    assert result.overallValidationStatus in ['valid','degraded']
