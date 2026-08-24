from pathlib import Path
from fastapi.testclient import TestClient
from lumi.app.main import app

client = TestClient(app)

def test_ui_storage_panel_assets():
    index = Path('lumi/app/static/index.html').read_text()
    appjs = Path('lumi/app/static/app.js').read_text()
    assert 'data-panel="persistence"' in index
    assert 'panel-persistence' in index
    assert 'renderPersistence' in appjs
    assert '/persistence/status' in appjs
    assert '/persistence/export' in appjs
    assert 'localStorage' not in appjs or 'snapshot' not in appjs.lower()

def test_persistence_endpoints_available():
    assert client.get('/persistence/status').status_code == 200
    assert client.get('/persistence/health').status_code == 200
    assert client.get('/persistence/profiles').status_code == 200
