"""History/overview share latest-request ownership through loading, error and filtering."""
import json
import os
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('scenario', [
    'older_success', 'older_reject', 'older_http', 'older_json', 'older_invalid',
    'newer_failure', 'pending_older_success', 'pending_older_failure',
    'body_success', 'body_rejection', 'cross_overview_history',
    'cross_history_overview', 'cross_overview_overview', 'filters_pending',
    'filters_error_retry', 'empty_success', 'current_reject', 'current_http',
    'current_json', 'current_invalid', 'current_invalid_row', 'three_calls',
])
def test_latest_activity_refresh_owns_visible_state(scenario):
    result = subprocess.run([
        'node', str(ROOT / 'tests/e4_activity_refresh_behavior.cjs'),
        os.environ.get('E4_WEBAPP_SOURCE', str(ROOT / 'relay/webapp.html')), scenario,
    ], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == {'scenario': scenario, 'result': 'PASS'}
