"""Terminal reason survives receipt, stale verification and client timer state."""
import itertools
import json
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


def render(**state):
    result = subprocess.run(
        ['node', str(ROOT / 'tests/e4_payment_terminal_behavior.cjs')],
        input=json.dumps({'path': str(ROOT / 'relay-fastapi/main.py'), **state}),
        text=True, capture_output=True, timeout=5)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.mark.parametrize('status,title', [('expired', 'Время истекло'),
    ('failed', 'Заявка не выполнена'), ('cancelled', 'Заявка отменена')])
@pytest.mark.parametrize('receipt', ['', 'stored', 'sent'])
def test_terminal_reason_and_receipt_remain_independent(status, title, receipt):
    for verification, dead, timer in itertools.product(['', 'video', 'pdf'], [False, True], [False, True]):
        result = render(status=status, receipt=receipt, verification=verification,
                        dead=dead, localExpired=timer)
        html = result['html']
        assert title in html
        assert result['state']['status'] == status
        assert all(forbidden not in html for forbidden in ['class="reqs"', 'class="qr"',
            '<button', 'Требуется подтверждение', 'Ожидаем оплату', 'Обычно до',
            'Заявка НЕ отменена', 'Разбираем вручную'])
        assert 'Поддержка в Telegram' in html and 'не переводите' in html
        if status != 'expired':
            assert 'истекло' not in html and 'истёк' not in html
        if receipt == 'stored':
            assert 'Файл чека получен, но платёжному партнёру пока не передан.' in html
        elif receipt == 'sent':
            assert 'Чек получен и передан платёжному партнёру.' in html
        else:
            assert 'terminal-receipt' not in html


@pytest.mark.parametrize('status', ['expired', 'failed', 'cancelled'])
def test_unknown_receipt_is_not_claimed_as_evidence(status):
    html = render(status=status, receipt='<script>unsafe</script>')['html']
    assert 'terminal-receipt' not in html and '<script>' not in html


@pytest.mark.parametrize('status,title', [('paid', 'Оплата получена'), ('sent', 'Выполнено')])
def test_success_outcomes_keep_precedence(status, title):
    html = render(status=status, receipt='sent', verification='video', dead=True,
                  localExpired=True)['html']
    assert title in html and 'Заявка отменена' not in html and '<button' not in html


def test_pending_local_timer_never_changes_order_outcome():
    result = render(status='pending', localExpired=True)
    assert result['state']['status'] == 'pending'
    assert 'Время истекло' in result['html']
