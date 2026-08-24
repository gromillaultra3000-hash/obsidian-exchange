from fastapi.testclient import TestClient
from lumi.app.main import app
from lumi.app.core.runtime import runtime_instance
from lumi.app.schemas.security import SetupPasswordRequest, UnlockRequest, SecretCreateRequest

client = TestClient(app)


def setup_function():
    runtime_instance.reset_for_tests()


def test_password_setup_unlock_and_vault_no_raw_secret():
    r = client.post('/security/setup', json={'password':'StrongPass123', 'confirmPassword':'StrongPass123'})
    assert r.status_code == 200
    u = client.post('/security/unlock', json={'password':'StrongPass123'})
    assert u.status_code == 200
    token = u.json()['accessToken']
    s = client.post('/security/vault/secrets', json={'name':'test-key','kind':'api_key','value':'sk-test-secret-123456'}, headers={'Authorization': f'Bearer {token}'})
    assert s.status_code == 200
    body = s.json()
    assert 'sk-test-secret' not in str(body)
    assert body['secretRef'].startswith('vault://secret/')
    listed = client.get('/security/vault/secrets').json()
    assert 'sk-test-secret' not in str(listed)
    resolved = client.post('/security/vault/resolve', json={'secretRef': body['secretRef'], 'purpose':'test'}).json()
    assert resolved['valueAvailable'] is True
    assert 'sk-test-secret' not in str(resolved)
    assert runtime_instance.internal_get_secret_value(body['secretRef']) == 'sk-test-secret-123456'


def test_protected_mode_blocks_without_token_and_allows_with_token():
    runtime_instance.setup_security_password(SetupPasswordRequest(password='StrongPass123', confirmPassword='StrongPass123'))
    runtime_instance.security_config_service.enable_protected_mode()
    blocked = client.get('/providers')
    assert blocked.status_code == 401
    assert client.get('/health').status_code == 200
    unlock = client.post('/security/unlock', json={'password':'StrongPass123'})
    token = unlock.json()['accessToken']
    allowed = client.get('/providers', headers={'Authorization': f'Bearer {token}'})
    assert allowed.status_code == 200


def test_security_export_excludes_vault_values_and_plain_secret():
    runtime_instance.setup_security_password(SetupPasswordRequest(password='StrongPass123', confirmPassword='StrongPass123'))
    runtime_instance.unlock_security(UnlockRequest(password='StrongPass123'))
    rec = runtime_instance.create_secret(SecretCreateRequest(name='x', kind='api_key', value='sk-test-secret-123456'))
    result = client.post('/persistence/export', json={})
    assert result.status_code == 200
    txt = result.text
    assert 'vault_values' not in txt
    assert 'sk-test-secret-123456' not in txt


def test_security_static_ui_contract():
    html = client.get('/ui').text
    assert 'data-panel="security"' in html
    js = client.get('/ui/app.js').text
    assert 'localStorage.setItem' not in js
    assert 'type="password"' in js
    assert '/security/status' in js
    assert 'eval(' not in js
