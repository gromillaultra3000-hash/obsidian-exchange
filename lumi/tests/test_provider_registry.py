from fastapi.testclient import TestClient
from lumi.app.main import app

client = TestClient(app)

def provider(pid='mock-1', enabled=True, notes='success'):
    return {
        'providerId': pid,
        'displayName': 'Mock Provider',
        'providerType': 'mock',
        'apiFormat': 'json',
        'enabled': enabled,
        'roles': ['responder'],
        'capabilities': ['mock'],
        'costProfile': {},
        'latencyProfile': {},
        'reliabilityScore': 1.0,
        'notes': notes,
        'secretRef': 'vault:secret-value'
    }

def test_add_provider():
    response = client.post('/providers', json=provider())
    assert response.status_code == 200
    data = response.json()
    assert data['providerId'] == 'mock-1'
    assert data['secretRef'] == '***REDACTED***'

def test_list_providers():
    client.post('/providers', json=provider('mock-2'))
    response = client.get('/providers')
    assert response.status_code == 200
    assert len(response.json()) == 1

def test_duplicate_provider_rejected():
    payload = provider('mock-dup')
    client.post('/providers', json=payload)
    response = client.post('/providers', json=payload)
    assert response.status_code == 409

def test_disable_enable_provider():
    client.post('/providers', json=provider('mock-toggle'))
    client.post('/providers/mock-toggle/disable')
    prov = client.get('/providers/mock-toggle').json()
    assert prov['enabled'] is False
    client.post('/providers/mock-toggle/enable')
    prov = client.get('/providers/mock-toggle').json()
    assert prov['enabled'] is True

def test_health_provider():
    client.post('/providers', json=provider('mock-health'))
    res = client.get('/providers/mock-health/health')
    assert res.status_code == 200
    assert res.json()['status'] == 'healthy'
