"""Clipboard feedback must describe the current payment-requisites copy."""
import json
import os
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('scenario', [
    'pending_success', 'duplicate', 'reject_retry', 'unavailable', 'throw',
    'accessible', 'literal_phone', 'literal_card', 'new_order', 'same_id',
    'empty_reset', 'detached_same_ids', 'terminal_paid', 'terminal_sent',
    'terminal_cancelled', 'terminal_expired', 'terminal_failed',
    'terminal_receipt', 'terminal_dead', 'terminal_timer',
    'cross_order_success', 'cross_order_reject', 'cross_order_same_id',
    'waiting_reset', 'waiting_terminal', 'waiting_newer',
])
def test_payment_requisites_copy_integrity(scenario):
    result = subprocess.run([
        'node', str(ROOT / 'tests/e4_payment_requisites_copy_behavior.cjs'),
        os.environ.get('E4_WEBAPP_SOURCE', str(ROOT / 'relay/webapp.html')), scenario,
    ], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == {'scenario': scenario, 'result': 'PASS'}
