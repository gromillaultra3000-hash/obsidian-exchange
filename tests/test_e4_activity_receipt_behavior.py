"""Actual history serialization and shipped rendering agree on receipt lifecycle."""
import ast
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def serialize():
    # Execute just the real read-only serializer, with synthetic repository rows.
    # Importing the application would initialize unrelated production services.
    path = ROOT / 'relay-fastapi/main.py'
    function = next(n for n in ast.parse(path.read_text()).body
                    if isinstance(n, ast.AsyncFunctionDef) and n.name == 'api_history')
    function.decorator_list = []
    module = ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[]))
    spec = importlib.util.spec_from_file_location('receipt_txid', ROOT / 'relay/core/txid.py')
    txid = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(txid)

    def response(status, receipt, has_transaction):
        row = dict(order_id=42, rub_amount=2000, currency='TON', status=status,
                   created_at='2026-09-08', session_token='synthetic_urlsafe_session',
                   paid_btc_tx='a' * 64 if has_transaction else '', network='TON',
                   receipt_sent_at='2026-09-08' if receipt == 'sent' else '')

        class Reads:
            def customer_orders(self, user_id, limit):
                assert user_id == 42 and limit == 30
                return [row]

            def receipt_order_ids(self, order_ids):
                assert list(order_ids) == [42]
                return {42} if receipt else set()

        ctx = {'Request': object, 'verify_init_data': lambda _: {'id': 42},
               '_order_reads': Reads(), '_delayed_ids': lambda: set(), '_txid': txid}
        exec(compile(module, str(path), 'exec'), ctx)
        result = asyncio.run(ctx['api_history'](SimpleNamespace(headers={})))
        assert result[0]['receipt'] == receipt
        assert bool(result[0]['tx_url']) == has_transaction
        return result

    return response


@pytest.mark.parametrize('status', ['pending', 'paid', 'sent', 'expired', 'failed', 'cancelled'])
@pytest.mark.parametrize('receipt', ['', 'stored', 'sent'])
@pytest.mark.parametrize('has_transaction', [False, True])
def test_receipt_lifecycle_and_independent_transaction_evidence(serialize, status, receipt, has_transaction):
    result = subprocess.run([
        'node', str(ROOT / 'tests/e4_activity_receipt_behavior.cjs'),
        os.environ.get('E4_WEBAPP_SOURCE', str(ROOT / 'relay/webapp.html')),
    ], input=json.dumps(serialize(status, receipt, has_transaction)),
        capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['result'] == 'PASS'
