import hashlib
import json
from pathlib import Path

ROOT = Path('/root')
DOC = ROOT / 'docs/e0-4-legacy-payment-edge-upstream-runtime-observation.v1.json'


def test_edge_observation_is_restrictive_and_unowned():
    data = json.loads(DOC.read_text())
    assert data['route'] == 'E0/E0.4/LEGACY_PAYMENT_EDGE_UPSTREAM'
    assert data['status'] == 'BLOCKED_OWNER'
    assert all(value is False for value in data['authority'].values())
    assert data['edge']['upstream'] == 'http://127.0.0.1:8080'


def test_edge_config_hashes_match():
    data = json.loads(DOC.read_text())
    for item in data['edge']['nginxConfigs']:
        assert hashlib.sha256(Path(item['path']).read_bytes()).hexdigest() == item['sha256']


def test_edge_findings_cover_owner_and_reachability():
    data = json.loads(DOC.read_text())
    ids = {finding['id'] for finding in data['findings']}
    assert {'PUBLIC_PAYMENT_ALIAS_UNOWNED', 'REACHABILITY_AND_TLS_RUNTIME_UNPROVEN'} <= ids
    assert 'authenticated owner acceptance absent' in data['knownBlockers']
