from fastapi.testclient import TestClient
from lumi.app.main import app
from lumi.app.core.runtime import runtime_instance
import pytest

client = TestClient(app)

@pytest.fixture(autouse=True)
def reset_runtime():
    runtime_instance.reset_for_tests()


def provider(pid, caps, roles, notes, reliability=0.9):
    return {
        'providerId': pid,
        'displayName': pid,
        'providerType': 'mock',
        'apiFormat': 'json',
        'enabled': True,
        'capabilities': caps,
        'roles': roles,
        'costProfile': {},
        'latencyProfile': {},
        'reliabilityScore': reliability,
        'notes': notes,
    }


def test_resolve_contains_conflict_metadata_for_decision_request():
    client.post('/providers', json=provider('planner-approve', ['decision_support','planning','text_reasoning'], ['planner'], 'valid_with_evidence'))
    client.post('/providers', json=provider('risk-wait', ['risk_review','policy_checking','decision_support'], ['risk_checker'], 'risk_review_wait'))
    task = {'taskType':'decision_request','input':'Should we approve this change?','context':{},'requirements':{}}
    resp = client.post('/resolve', json=task)
    assert resp.status_code == 200
    data = resp.json()
    assert 'conflictReport' in data['metadata']
    assert 'deterministicResolution' in data['metadata']
    assert data['status'] in ['WAIT','ASK_USER','APPROVE','REJECT','SAFE_DEFAULT']


def test_conflicting_approve_reject_forces_formal_non_approve():
    client.post('/providers', json=provider('planner-approve', ['decision_support','planning','text_reasoning'], ['planner'], 'valid_with_evidence'))
    client.post('/providers', json=provider('risk-reject', ['risk_review','policy_checking','decision_support'], ['risk_checker'], 'critic_reject'))
    task = {'taskType':'decision_request','input':'Should we approve this change?','context':{},'requirements':{}}
    data = client.post('/resolve', json=task).json()
    assert data['conflictDetected'] is True
    assert data['metadata']['conflictReport']['primaryConflictType'] in ['ACTION_CONFLICT','STRATEGY_CONFLICT','RISK_CONFLICT']
    assert data['status'] in ['ASK_USER','WAIT','REJECT']
    assert data['actionAllowed'] is False


def test_conflict_api_analyze_and_resolve():
    payload = {
        'task': {'input': 'decide', 'context': {}, 'requirements': {}},
        'outputs': [
            {'providerId': 'p1', 'rawOutput': {'providerId':'p1','status':'success','answer':'ok','confidence':0.9,'suggestedStatus':'APPROVE','assumptions':['a'],'evidenceRefs':['e']}},
            {'providerId': 'p2', 'rawOutput': {'providerId':'p2','status':'success','answer':'no','confidence':0.8,'suggestedStatus':'REJECT','assumptions':['a'],'evidenceRefs':['e']}},
        ]
    }
    r = client.post('/conflict/analyze', json=payload)
    assert r.status_code == 200
    assert r.json()['conflictDetected'] is True
    r2 = client.post('/conflict/resolve', json=payload)
    assert r2.status_code == 200
    assert r2.json()['resolution']['status'] == 'ASK_USER'
