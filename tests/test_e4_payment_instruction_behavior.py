"""Payment instructions and callbacks must belong to the displayed order."""
import json
import os
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('scenario', [
    'qr_to_text', 'qr_without_amount', 'text_to_empty', 'link_to_qr',
    'paid_to_new', 'sent_to_new', 'expired_to_new', 'cancelled_to_new',
    'receipt_to_new', 'dead_to_new', 'timer_to_new', 'late_status',
    'late_json', 'old_actions', 'poll_serialization', 'poll_failure',
    'same_id_reopen', 'terminal_open', 'paid_refresh', 'poll_timeout', 'body_timeout',
])
def test_payment_instruction_isolation(scenario):
    result = subprocess.run([
        'node', str(ROOT / 'tests/e4_payment_instruction_behavior.cjs'),
        os.environ.get('E4_WEBAPP_SOURCE', str(ROOT / 'relay/webapp.html')), scenario,
    ], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == {'scenario': scenario, 'result': 'PASS'}
