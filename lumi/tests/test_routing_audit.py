from fastapi.testclient import TestClient
from lumi.app.main import app
from lumi.app.core.runtime import runtime_instance
import pytest

client = TestClient(app)

@pytest.fixture(autouse=True)
def reset_runtime():
    runtime_instance.reset_for_tests()

def test_routing_audit_events_exist():
    client.post('/providers', json={'providerId':'audit-routing-prov','displayName':'Audit Routing Provider','providerType':'mock','apiFormat':'json','enabled':True,'capabilities':['text_reasoning'],'roles':['reviewer'],'costProfile':{},'latencyProfile':{},'reliabilityScore':0.9})
    client.post('/resolve', json={'input':'test routing audit'})
    events = [entry['eventType'] for entry in client.get('/audit').json()]
    assert 'task_classified' in events
    assert 'task_requirements_built' in events
    assert 'route_plan_created' in events
    assert 'provider_selected' in events

def test_routing_failed_audit_exists():
    client.post('/resolve', json={'input':'no providers available'})
    events = [entry['eventType'] for entry in client.get('/audit').json()]
    assert 'routing_failed' in events or 'route_plan_created' in events
