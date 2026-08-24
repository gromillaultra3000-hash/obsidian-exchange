from fastapi.testclient import TestClient
from lumi.app.main import app
from lumi.app.core.runtime import runtime_instance
import pytest

client = TestClient(app)

@pytest.fixture(autouse=True)
def reset_runtime():
    runtime_instance.reset_for_tests()

def test_routing_metadata_no_secret():
    provider = {'providerId':'secret-routing-prov','displayName':'Secret Routing Provider','providerType':'mock','apiFormat':'json','enabled':True,'capabilities':['text_reasoning'],'roles':['reviewer'],'costProfile':{},'latencyProfile':{},'reliabilityScore':0.9,'secretRef':'vault:secret-123'}
    resp = client.post('/providers', json=provider).json()
    assert resp['secretRef'] == '***REDACTED***'
    data = client.post('/resolve', json={'input':'test secret in routing'}).json()
    assert 'vault:secret-123' not in str(data)

def test_audit_no_secret_in_routing():
    provider = {'providerId':'audit-secret-routing','displayName':'Audit Secret Routing','providerType':'mock','apiFormat':'json','enabled':True,'capabilities':['text_reasoning'],'roles':['reviewer'],'costProfile':{},'latencyProfile':{},'reliabilityScore':0.9,'secretRef':'vault:audit-secret'}
    client.post('/providers', json=provider)
    client.post('/resolve', json={'input':'test'})
    assert 'vault:audit-secret' not in str(client.get('/audit').json())

def test_role_fit_no_secret():
    provider = {'providerId':'role-fit-secret','displayName':'Role Fit Secret','providerType':'mock','apiFormat':'json','enabled':True,'capabilities':['text_reasoning'],'roles':['reviewer'],'costProfile':{},'latencyProfile':{},'reliabilityScore':0.9,'secretRef':'vault:role-secret'}
    client.post('/providers', json=provider)
    assert 'vault:role-secret' not in str(client.get('/providers/role-fit-secret/role-fit').json())
