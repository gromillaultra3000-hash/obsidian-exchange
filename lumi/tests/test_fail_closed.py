from fastapi.testclient import TestClient
from lumi.app.main import app

client = TestClient(app)

def test_invalid_request_does_not_crash():
    response = client.post('/resolve', json={'invalid': 'data'})
    assert response.status_code == 422

def test_provider_failure_does_not_crash():
    provider = {'providerId':'crash-me','displayName':'Crash','providerType':'mock','apiFormat':'json','enabled':True,'roles':[],'capabilities':['mock'],'costProfile':{},'latencyProfile':{},'reliabilityScore':0.0,'notes':'error'}
    client.post('/providers', json=provider)
    response = client.post('/resolve', json={'input': 'test'})
    assert response.status_code == 200
    assert 'decisionId' in response.json()

def test_runtime_returns_status_on_get_provider_nonexistent():
    response = client.get('/providers/nonexistent')
    assert response.status_code == 404
    data = response.json()
    assert data['detail']['code'] == 'PROVIDER_NOT_FOUND'
