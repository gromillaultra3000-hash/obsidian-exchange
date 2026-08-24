import hashlib
import json
from pathlib import Path

DOC = Path('/root/docs/e0-4-framework-generated-admin-http-surface-runtime-observation.v1.json')


def test_admin_generated_surface_is_restrictive():
    data = json.loads(DOC.read_text())
    assert data['route'] == 'E0/E0.4/FRAMEWORK_GENERATED_ADMIN_HTTP_SURFACE'
    assert data['status'] == 'BLOCKED_OWNER'
    assert all(value is False for value in data['authority'].values())
    assert data['observedDeclarations']['generatedRuntimeRouteCount'].startswith('not provable')


def test_admin_artifact_hashes_match():
    data = json.loads(DOC.read_text())
    for item in data['artifacts']:
        assert hashlib.sha256(Path(item['path']).read_bytes()).hexdigest() == item['sha256']


def test_admin_findings_close_generated_route_gap():
    data = json.loads(DOC.read_text())
    ids = {finding['id'] for finding in data['findings']}
    assert {'GENERATED_ROUTE_UNIVERSE_UNPROVEN', 'ADMIN_MUTATION_SCOPE_NOT_CLOSED'} <= ids
    assert data['nextSafeRoute'] == 'E0/E0.4/GENERATED_FASTAPI_DOCS'
