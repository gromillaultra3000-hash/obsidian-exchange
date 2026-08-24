from fastapi.testclient import TestClient
from lumi.app.main import app
from lumi.app.core.runtime import runtime_instance
from lumi.app.schemas.provider import ProviderProfile

client = TestClient(app)

def setup_function():
    runtime_instance.reset_for_tests()
    try:
        runtime_instance.register_provider(ProviderProfile(providerId='p1', displayName='Provider One', providerType='mock', apiFormat='json', enabled=True, capabilities=['text_reasoning']))
        runtime_instance.register_provider(ProviderProfile(providerId='p2', displayName='Provider Two', providerType='mock', apiFormat='json', enabled=True, capabilities=['text_reasoning']))
    except Exception:
        pass

def test_provider_intelligence_endpoints_metadata_only():
    assert client.get('/provider-intelligence/reliability').status_code == 200
    assert client.get('/provider-intelligence/quality').status_code == 200
    r = client.post('/provider-intelligence/review', json={'input':'check readiness','providerIds':['p1','p2'],'mode':'metadata_only'})
    assert r.status_code == 200
    data = r.json()
    assert data['mode'] == 'metadata_only'
    assert data['providerResults']

def test_budget_limits_block_excess():
    r = client.post('/provider-intelligence/budget-limits', json={'providerId':'p1','enabled':True,'maxCallsPerSession':0})
    assert r.status_code == 200
    r = client.post('/provider-intelligence/select', json={'candidateProviderIds':['p1'], 'strategy':'balanced'})
    assert r.status_code == 200
    assert r.json()['selectedProviderIds'] == []

def test_fallback_chain_report_and_ui():
    r = client.post('/provider-intelligence/fallback-chains', json={'chainId':'c1','displayName':'Main','providerIds':['p1','p2']})
    assert r.status_code == 200
    assert client.get('/provider-intelligence/fallback-chains').json()[0]['chainId'] == 'c1'
    report = client.post('/provider-intelligence/report').json()
    assert 'reportId' in report
    page = client.get('/ui').text
    assert 'providerIntelligence' in page
