import hashlib
import json
from pathlib import Path

DOC = Path('/root/docs/e0-4-deployed-generated-universe-reconciliation.v1.json')


def test_reconciliation_is_restrictive_and_detects_drift():
    data = json.loads(DOC.read_text())
    assert data['route'] == 'E0/E0.4/DEPLOYED_GENERATED_UNIVERSE_RECONCILIATION'
    assert data['status'] == 'BLOCKED_OWNER'
    assert all(value is False for value in data['authority'].values())
    assert all(item['reconciled'] is False for item in data['reconciliation'])


def test_reconciliation_hashes_match():
    data = json.loads(DOC.read_text())
    for item in data['reconciliation']:
        assert hashlib.sha256(Path(item['unitPath']).read_bytes()).hexdigest() == item['unitSha256']
        assert hashlib.sha256(Path(item['observedDeployedSourcePath']).read_bytes()).hexdigest() == item['sourceSha256']


def test_reconciliation_finds_path_drift():
    data = json.loads(DOC.read_text())
    assert any(item['unitExecPath'] != item['observedDeployedSourcePath'] for item in data['reconciliation'])
    assert 'SYSTEMD_SOURCE_PATH_DRIFT' in {x['id'] for x in data['findings']}
