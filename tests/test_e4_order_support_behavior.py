"""Order support is independent of optional local clipboard copying."""
import json
import os
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('scenario', [
    'support_stalled', 'support_only', 'support_browser', 'rejection',
    'unavailable', 'insecure', 'throw', 'getter_throw', 'malformed',
    'haptic_throw', 'literal', 'duplicate', 'cross_order_success',
    'cross_order_rejection', 'stale_success', 'stale_rejection', 'detached', 'empty',
])
def test_order_support_clipboard_independence(scenario):
    result = subprocess.run([
        'node', str(ROOT / 'tests/e4_order_support_behavior.cjs'),
        os.environ.get('E4_WEBAPP_SOURCE', str(ROOT / 'relay/webapp.html')), scenario,
    ], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == {'scenario': scenario, 'result': 'PASS'}
