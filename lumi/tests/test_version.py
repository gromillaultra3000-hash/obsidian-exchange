from fastapi.testclient import TestClient
from lumi.app.main import app

client = TestClient(app)


def test_version():
    response = client.get('/version')
    assert response.status_code == 200
    data = response.json()
    assert data['moduleName'] == 'Lumi'
    assert data['version'] == '1.7.0'
    assert 'provider_registry' in data['capabilities']
    assert 'decision_history' in data['capabilities']
    assert 'dialog_sessions' in data['capabilities']
    assert data['status'] == 'ok'
