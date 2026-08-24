from fastapi.testclient import TestClient
from lumi.app.main import app
from lumi.app.core.runtime import runtime_instance

client = TestClient(app)

def setup_function():
    runtime_instance.reset_for_tests()


def test_real_apply_default_disabled():
    r = client.get('/real-apply/config')
    assert r.status_code == 200
    assert r.json()['mode'] == 'disabled'


def test_real_apply_gate_blocks_unsafe_by_default():
    r = client.post('/real-apply/gate/check', json={
        'workspaceId': 'missing',
        'fileChanges': [{'path': '../outside.py', 'operation': 'update', 'afterContent': 'x'}]
    })
    assert r.status_code == 200
    data = r.json()
    assert data['allowed'] is False
    assert any('Global apply mode' in b for b in data['blockers'])


def test_real_apply_workspace_apply_and_rollback(tmp_path):
    (tmp_path / 'docs').mkdir()
    target = tmp_path / 'docs' / 'example.md'
    target.write_text('old', encoding='utf-8')
    client.post('/real-apply/config/enable-controlled')
    ws = client.post('/real-apply/workspaces', json={
        'displayName': 'Test Workspace',
        'rootPath': str(tmp_path),
        'allowApply': False,
        'allowedPathPrefixes': ['docs/']
    }).json()['workspace']
    assert ws['allowApply'] is False
    client.post(f"/real-apply/workspaces/{ws['workspaceId']}/enable-apply")
    payload = {
        'workspaceId': ws['workspaceId'],
        'approvalPromptId': 'approved-for-test',
        'testRunResultId': 'passed-for-test',
        'fileChanges': [{'path': 'docs/example.md', 'operation': 'update', 'afterContent': 'new'}]
    }
    gate = client.post('/real-apply/gate/check', json=payload).json()
    assert gate['allowed'] is True
    result = client.post('/real-apply/execute', json=payload).json()
    assert result['status'] == 'applied'
    assert target.read_text(encoding='utf-8') == 'new'
    assert result['backupId']
    assert result['rollbackPackageId']
    preview = client.post(f"/real-apply/rollback-packages/{result['rollbackPackageId']}/preview").json()
    assert preview['canRollback'] is True
    rollback = client.post('/real-apply/rollback', json={'rollbackPackageId': result['rollbackPackageId'], 'approvalPromptId': 'approved-for-test'}).json()
    assert rollback['status'] == 'rolled_back'
    assert target.read_text(encoding='utf-8') == 'old'


def test_real_apply_blocks_secrets_and_traversal(tmp_path):
    (tmp_path / 'docs').mkdir()
    client.post('/real-apply/config/enable-controlled')
    ws = client.post('/real-apply/workspaces', json={
        'displayName': 'Test Workspace',
        'rootPath': str(tmp_path),
        'allowApply': True,
        'allowedPathPrefixes': ['docs/']
    }).json()['workspace']
    bad = {
        'workspaceId': ws['workspaceId'],
        'approvalPromptId': 'approved',
        'testRunResultId': 'passed',
        'fileChanges': [
            {'path': '../outside.py', 'operation': 'update', 'afterContent': 'x'},
            {'path': 'docs/.env', 'operation': 'update', 'afterContent': 'token=secret-token'},
            {'path': 'docs/private.key', 'operation': 'update', 'afterContent': '-----BEGIN PRIVATE KEY-----\nabc'},
        ]
    }
    gate = client.post('/real-apply/gate/check', json=bad).json()
    assert gate['allowed'] is False
    joined = ' '.join(gate['blockers']).lower()
    assert 'outside workspace' in joined or 'traversal' in joined
    assert 'secret' in joined or 'blocked extension' in joined
