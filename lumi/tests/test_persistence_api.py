from fastapi.testclient import TestClient
from lumi.app.main import app
from lumi.app.core.runtime import runtime_instance

client = TestClient(app)

def setup_function():
    runtime_instance.reset_for_tests()

def test_persistence_status_health_profiles():
    assert client.get('/persistence/status').status_code == 200
    h = client.get('/persistence/health')
    assert h.status_code == 200
    assert h.json()['status'] in ['ready','degraded','not_initialized']
    p = client.get('/persistence/profiles')
    assert p.status_code == 200
    assert any(x['profileId'] == 'default' for x in p.json())

def test_profile_create_activate_reset():
    r = client.post('/persistence/profiles', json={'profileId':'pilot_profile','displayName':'Pilot Profile'})
    assert r.status_code == 200
    assert r.json()['profileId'] == 'pilot_profile'
    assert client.post('/persistence/profiles/pilot_profile/activate').status_code == 200
    assert client.post('/persistence/profiles/pilot_profile/reset').status_code == 200

def test_invalid_profile_rejected():
    r = client.post('/persistence/profiles', json={'profileId':'../bad','displayName':'Bad'})
    assert r.status_code == 400

def test_save_load_export_import_redacted():
    provider = {
        'providerId':'persist-provider','displayName':'Persist Provider','providerType':'mock','apiFormat':'json','enabled':True,
        'roles':['reviewer'],'capabilities':['text_reasoning'],'costProfile':{},'latencyProfile':{},'reliabilityScore':0.9,'secretRef':'sk-test-secret'
    }
    client.post('/providers', json=provider)
    save = client.post('/persistence/save', json={})
    assert save.status_code == 200
    assert save.json()['status'] == 'saved'
    load = client.post('/persistence/load', json={})
    assert load.status_code == 200
    exp = client.post('/persistence/export', json={})
    assert exp.status_code == 200
    data = exp.json()
    body = str(data).lower()
    assert 'sk-test-secret' not in body
    imp = client.post('/persistence/import', json={'profileId':'default','snapshot':data['snapshot'],'mode':'merge'})
    assert imp.status_code == 200
    assert imp.json()['status'] == 'imported'

def test_retention_dry_run():
    r = client.post('/persistence/retention-policy/dry-run')
    assert r.status_code == 200
    assert r.json()['dryRun'] is True
