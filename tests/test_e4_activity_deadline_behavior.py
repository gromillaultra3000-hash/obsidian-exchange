"""The whole activity read has a deadline independent of abort compliance."""
import json
import os
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('scenario', [
    'fetch_stall', 'body_stall', 'body_budget', 'late_fetch_success',
    'late_fetch_failure', 'late_body_success', 'late_body_failure',
    'retry_success', 'retry_failure', 'overview_retry', 'supersede_fetch',
    'supersede_body', 'old_timer', 'old_finally', 'success_before', 'success_at',
    'success_after', 'body_after', 'cleared_success_timer', 'network_error',
    'http_error', 'json_error', 'missing_abort', 'retired_headers', 'expired_headers',
])
def test_activity_read_deadline_and_retirement(scenario):
    result = subprocess.run([
        'node', str(ROOT / 'tests/e4_activity_deadline_behavior.cjs'),
        os.environ.get('E4_WEBAPP_SOURCE', str(ROOT / 'relay/webapp.html')), scenario,
    ], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == {'scenario': scenario, 'result': 'PASS'}
