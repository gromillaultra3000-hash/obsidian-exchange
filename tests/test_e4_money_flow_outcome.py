"""Order outcome remains uncertain when the response cannot confirm it."""
import json
import os
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path(os.environ.get('E4_WEBAPP_SOURCE', ROOT / 'relay/webapp.html'))


def run(action, **params):
    r = subprocess.run(['node', str(ROOT / 'tests/e4_money_flow_outcome.cjs')],
        input=json.dumps({'path': str(SOURCE), 'action': action, **params}),
        text=True, capture_output=True, check=True, timeout=10)
    return json.loads(r.stdout)


@pytest.mark.parametrize('action', ['buy', 'sell'])
@pytest.mark.parametrize('case', [
    {'mode': 'lost-response'}, {'mode': 'truncated-json'},
    {'status': 503, 'response': {'detail': 'temporary failure'}},
    {'response': None}, {'response': {}}, {'response': {'ok': True}},
    {'status': 408, 'response': {'detail': 'timeout'}},
    {'status': 409, 'response': {'detail': 'conflict'}},
    {'status': 400, 'response': {}},
    {'status': 403, 'response': {'ok': True, 'order_id': 42, 'sell_id': 42}},
    {'status': 429, 'response': {'ok': False, 'detail': 'conflict', 'order_id': 42}},
    {'response': {'ok': False}},
])
def test_unconfirmed_response_never_claims_no_order_or_invites_repeat(action, case):
    d = run(action, **case)
    text = d['result']['textContent']
    assert 'Не удалось подтвердить результат создания заявки' in text
    assert 'Активность' in text and 'поддержку' in text
    assert 'повторно' in text and 'не создана' not in text
    assert 'Попробуйте ещё раз' not in text
    assert len(d['requests']) == 1 and not d['tracking'] and not d['storage']
    assert 'success' not in d['haptics']


@pytest.mark.parametrize('action', ['buy', 'sell'])
@pytest.mark.parametrize('status', [200, 400, 403, 429])
def test_explicit_rejection_retains_literal_reason_without_success(action, status):
    reason = '<img src=x onerror=alert(1)> Параметры отклонены'
    d = run(action, status=status, response={'ok': False, 'detail': reason, 'error': reason})
    assert reason in d['result']['textContent']
    assert '<img' not in d['result']['innerHTML']
    assert not d['tracking'] and not d['storage'] and len(d['requests']) == 1


@pytest.mark.parametrize('action', ['buy', 'sell'])
def test_confirmed_response_preserves_one_existing_success_handoff(action):
    d = run(action, response={'ok': True, 'order_id': 42, 'sell_id': 42,
        'currency': 'TON', 'amount': 2, 'address': 'synthetic', 'rub': 2000})
    assert len(d['requests']) == len(d['tracking']) == 1
    assert 'success' in d['haptics']
    assert len(d['storage']) == (1 if action == 'buy' else 0)


@pytest.mark.parametrize('action', ['buy', 'sell'])
@pytest.mark.parametrize('status', [400, 403, 429])
def test_current_api_precreation_http_exception_retains_literal_detail(action, status):
    d = run(action, status=status, response={'detail': 'Проверьте параметры'})
    assert 'Проверьте параметры' in d['result']['textContent']
    assert not d['tracking'] and not d['storage'] and len(d['requests']) == 1


@pytest.mark.parametrize('action', ['buy', 'sell'])
@pytest.mark.parametrize('order_id', [0, -1, 1.5, '42', 9007199254740992])
def test_invalid_success_identity_stays_unknown(action, order_id):
    d = run(action, response={'ok': True, 'order_id': order_id, 'sell_id': order_id})
    assert 'Она могла быть создана' in d['result']['textContent']
    assert not d['tracking'] and not d['storage'] and len(d['requests']) == 1
