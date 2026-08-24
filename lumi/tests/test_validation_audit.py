from fastapi.testclient import TestClient
from lumi.app.main import app

client = TestClient(app)


def add_provider(pid, notes):
    return client.post('/providers', json={'providerId':pid,'displayName':pid,'providerType':'mock','apiFormat':'json','enabled':True,'capabilities':['text_reasoning'],'roles':['reviewer'],'costProfile':{},'latencyProfile':{},'reliabilityScore':0.9,'notes':notes})


def events():
    return [entry['eventType'] for entry in client.get('/audit').json()]


def test_validation_events_in_audit():
    add_provider('audit-valid','valid_with_evidence')
    client.post('/resolve', json={'taskType':'general_question','input':'general question audit events'})
    ev = events()
    assert 'validation_pipeline_started' in ev
    assert 'validation_pipeline_completed' in ev
    assert 'provider_output_normalized' in ev
    assert 'provider_output_validated' in ev


def test_rejected_output_audit_event():
    add_provider('audit-reject','unsafe_execution_claim')
    client.post('/resolve', json={'taskType':'general_question','input':'general question rejection audit'})
    ev = events()
    assert 'provider_output_rejected' in ev or 'unsafe_wording_detected' in ev


def test_secret_like_content_audit_event():
    add_provider('audit-secret','secret_leak_attempt')
    client.post('/resolve', json={'taskType':'general_question','input':'general question secret audit'})
    assert 'secret_like_content_detected' in events()
