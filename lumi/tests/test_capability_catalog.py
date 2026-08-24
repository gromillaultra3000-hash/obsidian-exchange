from fastapi.testclient import TestClient
from lumi.app.main import app

client = TestClient(app)

def test_get_capabilities():
    response = client.get('/capabilities')
    assert response.status_code == 200
    data = response.json()
    assert data['status'] == 'ok'
    assert len(data['capabilities']) >= 20

def test_capability_ids_unique():
    ids = [cap['id'] for cap in client.get('/capabilities').json()['capabilities']]
    assert len(ids) == len(set(ids))

def test_required_capabilities_exist():
    ids = [cap['id'] for cap in client.get('/capabilities').json()['capabilities']]
    for required in ['text_reasoning','code_analysis','validation','risk_review','decision_support','fallback_use','critique']:
        assert required in ids
