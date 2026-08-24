from lumi.app.providers.mock_adapter import MockProviderAdapter
from lumi.app.schemas.provider import ProviderProfile
from lumi.app.schemas.task import TaskRequest


def profile(pid, notes='success'):
    return ProviderProfile(providerId=pid, displayName=pid, providerType='mock', apiFormat='json', enabled=True, roles=[], capabilities=['mock'], costProfile={}, latencyProfile={}, reliabilityScore=1.0, notes=notes)

def test_mock_success():
    output = MockProviderAdapter().invoke(TaskRequest(input='test'), profile('success'))
    assert output.status == 'success'
    assert output.confidence == 0.9
    assert output.suggestedStatus == 'APPROVE'

def test_mock_low_confidence():
    output = MockProviderAdapter().invoke(TaskRequest(input='test'), profile('low', 'low_confidence'))
    assert output.confidence == 0.4
    assert output.suggestedStatus == 'WAIT'

def test_mock_error():
    assert MockProviderAdapter().invoke(TaskRequest(input='test'), profile('err', 'error')).status == 'error'

def test_mock_invalid():
    assert MockProviderAdapter().invoke(TaskRequest(input='test'), profile('inv', 'invalid')).status == 'invalid'

def test_mock_timeout_simulated():
    assert MockProviderAdapter().invoke(TaskRequest(input='test'), profile('time', 'timeout_simulated')).status == 'timeout'
