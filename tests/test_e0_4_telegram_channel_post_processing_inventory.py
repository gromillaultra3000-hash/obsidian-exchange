import hashlib
import json
from pathlib import Path

ROOT = Path('/root')
DOC = ROOT / 'docs/e0-4-telegram-channel-post-processing-runtime-observation.v1.json'


def test_channel_observation_is_restrictive():
    data = json.loads(DOC.read_text())
    assert data['route'] == 'E0/E0.4/TELEGRAM_CHANNEL_POST_PROCESSING'
    assert data['status'] == 'BLOCKED_OWNER'
    assert all(v is False for v in data['authority'].values())


def test_channel_observation_hashes_match():
    data = json.loads(DOC.read_text())
    for key in ('service', 'source', 'brandAsset'):
        item = data['scope'][key]
        assert hashlib.sha256(Path(item['path']).read_bytes()).hexdigest() == item['sha256']


def test_channel_controls_and_blockers_are_explicit():
    data = json.loads(DOC.read_text())
    assert set(data['surfaceClassification']) == {'telegram', 'site', 'miniApp', 'admin', 'api', 'native'}
    ids = {x['id'] for x in data['findings']}
    assert 'PREMIUM_USER_SESSION_IS_HIGH_AUTHORITY_BEARER' in ids
    assert 'WATCH_DEDUPLICATION_AND_RECONCILIATION_MISSING' in ids
    assert 'authenticated owner acceptance absent' in data['knownBlockers']
