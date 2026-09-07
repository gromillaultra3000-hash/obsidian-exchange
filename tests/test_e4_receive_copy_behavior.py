"""Clipboard completion and receive address integrity; no browser or network."""
import json
import os
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('scenario', [
    'pending', 'repeat', 'reject', 'unavailable', 'throw', 'empty',
    'out_of_order', 'close', 'shared_labels', 'rerender', 'haptic_throw',
    'receive_reorder', 'receive_failure', 'receive_reset',
])
def test_receive_copy(scenario):
    result = subprocess.run([
        'node', str(ROOT / 'tests/e4_receive_copy_behavior.cjs'),
        os.environ.get('E4_WEBAPP_SOURCE', str(ROOT / 'relay/webapp.html')), scenario,
    ], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == {'scenario': scenario, 'result': 'PASS'}
