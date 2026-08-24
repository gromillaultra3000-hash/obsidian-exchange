from fastapi.testclient import TestClient
from lumi.app.main import app
from lumi.app.core.runtime import runtime_instance
import pytest

client = TestClient(app)

@pytest.fixture(autouse=True)
def reset_runtime():
    runtime_instance.reset_for_tests()

def provider(pid, caps, roles=None, enabled=True, reliability=0.9, notes='success'):
    return {'providerId':pid,'displayName':pid,'providerType':'mock','apiFormat':'json','enabled':enabled,'capabilities':caps,'roles':roles or [],'costProfile':{},'latencyProfile':{},'reliabilityScore':reliability,'notes':notes}

def test_no_providers_returns_no_route():
    data = client.post('/routing/plan', json={'input':'test task'}).json()
    assert data['routeStatus'] == 'NO_ROUTE'

def test_disabled_providers_ignored():
    client.post('/providers', json=provider('disabled-prov',['text_reasoning'],['reviewer'],False))
    assert client.post('/routing/plan', json={'input':'test task'}).json()['routeStatus'] == 'NO_ROUTE'

def test_matching_provider_returns_ready():
    client.post('/providers', json=provider('match-prov',['text_reasoning','summarization'],['reviewer']))
    data = client.post('/routing/plan', json={'input':'general question'}).json()
    assert data['routeStatus'] == 'READY'
    assert 'match-prov' in data['selectedProviders']

def test_fallback_provider_used():
    client.post('/providers', json=provider('fallback-prov',['fallback_use','text_reasoning'],['fallback_provider'], notes='fallback_success'))
    data = client.post('/routing/plan', json={'input':'complex code review task'}).json()
    assert data['routeStatus'] in ['FALLBACK','READY']
    assert 'fallback-prov' in data['selectedProviders']

def test_higher_reliability_provider_selected_first():
    client.post('/providers', json=provider('low',['text_reasoning'],['reviewer'], reliability=0.2))
    client.post('/providers', json=provider('high',['text_reasoning'],['reviewer'], reliability=0.9))
    data = client.post('/routing/plan', json={'input':'general question'}).json()
    assert data['selectedProviders'][0] == 'high'
