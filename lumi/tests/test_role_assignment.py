from fastapi.testclient import TestClient
from lumi.app.main import app
from lumi.app.core.runtime import runtime_instance
import pytest

client = TestClient(app)

@pytest.fixture(autouse=True)
def reset_runtime():
    runtime_instance.reset_for_tests()

def register(pid, capabilities, roles=None, reliability=0.9):
    return client.post('/providers', json={
        'providerId': pid, 'displayName': pid, 'providerType': 'mock', 'apiFormat': 'json',
        'enabled': True, 'capabilities': capabilities, 'roles': roles or [], 'costProfile': {},
        'latencyProfile': {}, 'reliabilityScore': reliability
    })

def test_code_analysis_gets_code_reviewer_suggestion():
    register('code-prov', ['code_analysis', 'critique', 'validation'])
    data = client.post('/providers/code-prov/suggest-roles').json()
    assert 'code_reviewer' in data['suggestedRoles']

def test_risk_review_gets_risk_checker_suggestion():
    register('risk-prov', ['risk_review', 'policy_checking'])
    data = client.post('/providers/risk-prov/suggest-roles').json()
    assert 'risk_checker' in data['suggestedRoles']

def test_multiple_roles_suggested():
    register('multi-prov', ['code_analysis', 'critique', 'validation', 'error_analysis'])
    assert len(client.post('/providers/multi-prov/suggest-roles').json()['suggestedRoles']) >= 2

def test_unknown_capabilities_warn_not_crash():
    register('unknown-prov', ['unknown_capability'])
    data = client.post('/providers/unknown-prov/suggest-roles').json()
    assert data['warnings']

def test_role_fit_endpoint():
    register('fit-prov', ['code_analysis', 'critique', 'validation'], ['code_reviewer', 'critic'])
    data = client.get('/providers/fit-prov/role-fit').json()
    assert 'roleFits' in data
    assert any(r['roleId'] == 'code_reviewer' for r in data['roleFits'])
