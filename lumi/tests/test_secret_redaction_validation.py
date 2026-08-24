from fastapi.testclient import TestClient
from lumi.app.main import app

client = TestClient(app)


def add_secret_provider(pid):
    return client.post('/providers', json={'providerId':pid,'displayName':pid,'providerType':'mock','apiFormat':'json','enabled':True,'capabilities':['text_reasoning'],'roles':['reviewer'],'costProfile':{},'latencyProfile':{},'reliabilityScore':0.9,'notes':'secret_leak_attempt'})


def test_validation_output_no_secret():
    add_secret_provider('secret-valid')
    data = client.post('/resolve', json={'taskType':'general_question','input':'general question secret redaction'}).json()
    assert 'sk-test-secret-value' not in str(data)


def test_audit_no_raw_secret_in_validation():
    add_secret_provider('audit-secret-val')
    client.post('/resolve', json={'taskType':'general_question','input':'general question secret in audit val'})
    audit_data = client.get('/audit').json()
    assert 'sk-test-secret-value' not in str(audit_data)
