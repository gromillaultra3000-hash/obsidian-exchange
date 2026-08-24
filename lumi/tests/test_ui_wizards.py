from fastapi.testclient import TestClient
from lumi.app.main import app

client = TestClient(app)

def test_integration_wizard():
    r = client.get('/ui/wizards/integration')
    assert r.status_code == 200
    data = r.json()
    assert data['wizardId'] == 'integration_wizard'
    assert len(data['steps']) >= 3

def test_project_wizard():
    r = client.get('/ui/wizards/project')
    assert r.status_code == 200
    data = r.json()
    assert data['wizardId'] == 'project_wizard'
    assert len(data['steps']) >= 3
