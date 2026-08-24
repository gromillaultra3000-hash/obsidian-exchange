from fastapi.testclient import TestClient
from lumi.app.main import app

client = TestClient(app)


def add_provider(pid, notes, capabilities=None, roles=None):
    provider = {
        'providerId': pid,
        'displayName': pid,
        'providerType': 'mock',
        'apiFormat': 'json',
        'enabled': True,
        'capabilities': capabilities or ['text_reasoning'],
        'roles': roles or ['reviewer'],
        'costProfile': {},
        'latencyProfile': {},
        'reliabilityScore': 0.9,
        'notes': notes,
    }
    return client.post('/providers', json=provider)


def test_resolve_includes_validation_metadata():
    add_provider('resolve-valid', 'valid_with_evidence')
    data = client.post('/resolve', json={'taskType':'general_question','input':'general question'}).json()
    assert 'validationPipeline' in data['metadata']
    assert 'validationSummary' in data['metadata']


def test_all_rejected_outputs_returns_safe_default():
    add_provider('rejected-prov', 'unsafe_execution_claim')
    data = client.post('/resolve', json={'taskType':'general_question','input':'general question'}).json()
    assert data['status'] == 'SAFE_DEFAULT'
    assert data['winningRule'] in ['all_outputs_rejected_by_validation','unsafe_content_detected']


def test_valid_with_evidence_can_approve_or_wait():
    add_provider('evidence-prov', 'valid_with_evidence')
    data = client.post('/resolve', json={'taskType':'general_question','input':'approve this request'}).json()
    assert data['metadata']['validationPipeline']['overallValidationStatus'] == 'valid'
    assert data['status'] in ['APPROVE','WAIT']


def test_degraded_caps_confidence():
    add_provider('degraded-prov', 'degraded_missing_evidence')
    data = client.post('/resolve', json={'taskType':'general_question','input':'approve this request'}).json()
    if data['metadata']['validationPipeline']['overallValidationStatus'] == 'degraded':
        assert data['confidence'] <= 0.74
