import hashlib
import json
from pathlib import Path

DOC = Path('/root/docs/e0-4-generated-fastapi-docs-runtime-observation.v1.json')


def test_fastapi_docs_observation_is_restrictive():
    data = json.loads(DOC.read_text())
    assert data['route'] == 'E0/E0.4/GENERATED_FASTAPI_DOCS'
    assert data['status'] == 'BLOCKED_OWNER'
    assert all(value is False for value in data['authority'].values())
    assert data['combinedInferredRouteObjects'] == 346


def test_fastapi_artifact_hashes_match():
    data = json.loads(DOC.read_text())
    for item in data['applications']:
        assert hashlib.sha256(Path(item['path']).read_bytes()).hexdigest() == item['sha256']


def test_docs_exposure_is_explicit():
    data = json.loads(DOC.read_text())
    relay = next(item for item in data['applications'] if item['name'] == 'RELAY')
    lumi = next(item for item in data['applications'] if item['name'] == 'LUMI')
    assert relay['docsEnabledByDefault'] and lumi['docsEnabledByDefault']
    assert 'PUBLIC_GENERATED_DOCS_SURFACE_UNCLASSIFIED' in {x['id'] for x in data['findings']}
