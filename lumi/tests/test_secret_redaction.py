from fastapi.testclient import TestClient
from lumi.app.main import app
from lumi.app.providers.redaction import RedactionUtil

client = TestClient(app)

def test_api_key_redacted():
    result = RedactionUtil().redact_dict({'apiKey': 'sk-12345', 'name': 'test'})
    assert result['apiKey'] == '***REDACTED***'
    assert result['name'] == 'test'

def test_secret_token_password_redacted():
    result = RedactionUtil().redact_dict({'secret': 'abc', 'token': 'def', 'password': 'ghi', 'normal': 'ok', 'nested': {'authorization': 'Bearer x'}})
    assert result['secret'] == '***REDACTED***'
    assert result['token'] == '***REDACTED***'
    assert result['password'] == '***REDACTED***'
    assert result['nested']['authorization'] == '***REDACTED***'
    assert result['normal'] == 'ok'

def test_provider_response_no_raw_secret():
    provider = {'providerId':'sec-test','displayName':'Secret Test','providerType':'mock','apiFormat':'json','enabled':True,'roles':[],'capabilities':['mock'],'costProfile':{},'latencyProfile':{},'reliabilityScore':1.0,'secretRef':'vault:mock-secret'}
    response = client.post('/providers', json=provider)
    text = response.text
    assert 'vault:mock-secret' not in text
    assert '***REDACTED***' in text

def test_audit_no_raw_secret():
    provider = {'providerId':'audit-sec','displayName':'Audit Secret','providerType':'mock','apiFormat':'json','enabled':True,'roles':[],'capabilities':['mock'],'costProfile':{},'latencyProfile':{},'reliabilityScore':1.0,'secretRef':'vault:raw-secret'}
    client.post('/providers', json=provider)
    client.post('/resolve', json={'input': 'test'})
    text = client.get('/audit').text
    assert 'vault:raw-secret' not in text
    assert 'apiKey' not in text
