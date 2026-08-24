from fastapi.testclient import TestClient
from lumi.app.main import app

client = TestClient(app)

def provider(pid='mock-ok', enabled=True, notes='success'):
    return {
        'providerId': pid,
        'displayName': pid,
        'providerType': 'mock',
        'apiFormat': 'json',
        'enabled': enabled,
        'roles': ['responder'],
        'capabilities': ['mock'],
        'costProfile': {},
        'latencyProfile': {},
        'reliabilityScore': 1.0,
        'notes': notes
    }

def test_resolve_no_providers_returns_wait():
    response = client.post('/resolve', json={'input': 'test'})
    assert response.status_code == 200
    data = response.json()
    assert data['status'] == 'WAIT'
    assert data['winningRule'] == 'no_enabled_providers'
    assert data['actionAllowed'] is False

def test_resolve_with_mock_success():
    client.post('/providers', json=provider())
    response = client.post('/resolve', json={'input': 'approve this'})
    assert response.status_code == 200
    data = response.json()
    assert data['status'] == 'APPROVE'
    assert data['actionAllowed'] is True
    assert data['providerOutputsCount'] == 1

def test_low_confidence_returns_wait():
    client.post('/providers', json=provider('low-conf', True, 'low_confidence'))
    data = client.post('/resolve', json={'input': 'check'}).json()
    assert data['status'] == 'WAIT'
    assert data['winningRule'] == 'low_confidence_wait'

def test_provider_error_returns_safe_default():
    client.post('/providers', json=provider('err-prov', True, 'error'))
    data = client.post('/resolve', json={'input': 'error test'}).json()
    assert data['status'] == 'SAFE_DEFAULT'
    assert data['winningRule'] == 'no_valid_outputs'

def test_disabled_provider_not_used():
    client.post('/providers', json=provider('dis-me', False))
    data = client.post('/resolve', json={'input': 'test'}).json()
    assert data['status'] == 'WAIT'
    assert data['winningRule'] == 'no_enabled_providers'
