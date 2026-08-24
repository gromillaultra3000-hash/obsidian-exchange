from fastapi.testclient import TestClient
from lumi.app.main import app

client = TestClient(app)

def test_ui_returns_html():
    r = client.get('/ui')
    assert r.status_code == 200
    assert 'Lumi Dashboard' in r.text

def test_dashboard_returns_html():
    r = client.get('/dashboard')
    assert r.status_code == 200
    assert 'Lumi Dashboard' in r.text

def test_ui_assets():
    assert client.get('/ui/app.js').status_code == 200
    assert client.get('/ui/styles.css').status_code == 200
    assert client.get('/ui/components/dialog.js').status_code == 200

def test_ui_state():
    r = client.get('/ui/state')
    assert r.status_code == 200
    data = r.json()
    assert data['version'] == '1.7.0'
    assert 'counts' in data
    assert 'safetyLabels' in data

def test_dashboard_state_alias():
    r = client.get('/dashboard/state')
    assert r.status_code == 200
    assert r.json()['version'] == '1.7.0'

def test_ui_safety_labels():
    r = client.get('/ui/safety-labels')
    assert r.status_code == 200
    labels = [x['title'] for x in r.json()]
    assert 'No host writes' in labels
    assert 'No real patch apply' in labels
    assert 'Approval required' in labels
    assert 'Sandbox only' in labels
    assert 'Secrets redacted' in labels
