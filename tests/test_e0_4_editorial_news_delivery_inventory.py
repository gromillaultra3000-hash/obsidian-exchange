import hashlib
import json
from pathlib import Path

ROOT = Path('/root')
DOC = ROOT / 'docs/e0-4-editorial-news-delivery-runtime-observation.v1.json'


def test_editorial_news_observation_is_restrictive_and_bound():
    data = json.loads(DOC.read_text())
    assert data['route'] == 'E0/E0.4/EDITORIAL_NEWS_DELIVERY'
    assert data['status'] == 'BLOCKED_OWNER'
    assert data['decisionEffect'] == 'RESTRICTIVE_READ_ONLY_OBSERVATION_ONLY'
    assert all(v is False for v in data['authority'].values())
    assert data['nextSafeRoute'] == 'E0/E0.4/TELEGRAM_CHANNEL_POST_PROCESSING'


def test_observation_hashes_match_raw_bytes():
    data = json.loads(DOC.read_text())
    for item in data['scope']['serviceUnits'] + data['scope']['sourceFiles']:
        path = Path(item['path'])
        assert hashlib.sha256(path.read_bytes()).hexdigest() == item['sha256']


def test_required_surfaces_and_blockers_present():
    data = json.loads(DOC.read_text())
    assert set(data['surfaceClassification']) == {'telegram', 'site', 'miniApp', 'admin', 'api', 'native'}
    ids = {finding['id'] for finding in data['findings']}
    assert {'END_TO_END_DELIVERY_NOT_IDEMPOTENT', 'SOURCE_PROVENANCE_AND_FRESHNESS_UNBOUND', 'SUBSCRIPTION_CONSENT_RETENTION_AUDIT_GAPS'} <= ids
    assert 'authenticated owner acceptance absent' in data['knownBlockers']
