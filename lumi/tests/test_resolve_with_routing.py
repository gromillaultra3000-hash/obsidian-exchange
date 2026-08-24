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

def test_resolve_includes_routing_metadata():
    client.post('/providers', json=provider('route-meta-prov',['text_reasoning','summarization'],['reviewer']))
    data = client.post('/resolve', json={'input':'general question'}).json()
    assert 'routePlan' in data['metadata']
    assert 'taskClassification' in data['metadata']
    assert data['metadata']['routePlan']['routeStatus'] == 'READY'

def test_code_review_selects_code_reviewer_provider():
    client.post('/providers', json=provider('code-prov',['code_analysis','critique','validation'],['code_reviewer','validator'], notes='code_review_success'))
    data = client.post('/resolve', json={'taskType':'code_review','input':'Review this code for bugs'}).json()
    assert 'code-prov' in data['metadata']['routePlan']['selectedProviders']
    assert data['providerOutputsCount'] >= 1

def test_no_route_returns_wait():
    data = client.post('/resolve', json={'input':'complex task requiring special capabilities'}).json()
    assert data['status'] == 'WAIT'
    assert data['requiredNextStep'] in ['register_provider','register_provider_with_required_capabilities']

def test_fallback_route_uses_fallback_provider():
    client.post('/providers', json=provider('fallback-resolve-prov',['fallback_use','text_reasoning'],['fallback_provider'], reliability=0.5, notes='fallback_success'))
    data = client.post('/resolve', json={'input':'code review needed'}).json()
    assert data['metadata']['routePlan']['fallbackUsed'] is True
    assert 'fallback-resolve-prov' in data['metadata']['routePlan']['selectedProviders']

def test_multi_provider_route_invokes_selected_providers():
    client.post('/providers', json=provider('planner',['planning','text_reasoning'],['planner']))
    client.post('/providers', json=provider('risk',['risk_review','decision_support'],['risk_checker']))
    data = client.post('/resolve', json={'taskType':'decision_request','input':'Should we proceed?'}).json()
    assert len(data['metadata']['routePlan']['selectedProviders']) >= 2
    assert data['providerOutputsCount'] >= 2
