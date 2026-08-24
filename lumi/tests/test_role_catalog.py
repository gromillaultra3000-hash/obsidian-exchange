from fastapi.testclient import TestClient
from lumi.app.main import app

client = TestClient(app)

def test_get_roles():
    response = client.get('/roles')
    assert response.status_code == 200
    data = response.json()
    assert data['status'] == 'ok'
    assert len(data['roles']) >= 15

def test_role_ids_unique():
    ids = [role['roleId'] for role in client.get('/roles').json()['roles']]
    assert len(ids) == len(set(ids))

def test_roles_have_required_capabilities():
    for role in client.get('/roles').json()['roles']:
        assert role['requiredCapabilities']
