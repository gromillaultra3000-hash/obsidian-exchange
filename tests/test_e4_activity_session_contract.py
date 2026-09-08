"""Owner-scoped activity uses one read-only snapshot and the latest session row."""
import ast
import asyncio
import json
import logging
from pathlib import Path
import sqlite3
import subprocess
import sys
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'relay'))
from repositories import activity_read_store, order_read_store
from core import txid


@pytest.fixture
def ledger(tmp_path):
    path = tmp_path / 'activity.db'
    with sqlite3.connect(path) as c:
        c.executescript('''
        CREATE TABLE orders(order_id INTEGER PRIMARY KEY,user_id INTEGER,rub_amount REAL,
            crypto_address TEXT,currency TEXT,status TEXT,created_at TEXT,
            paid_btc_tx TEXT,network TEXT,receipt_sent_at TEXT);
        CREATE TABLE payment_sessions(id INTEGER PRIMARY KEY,order_id INTEGER,
            session_token TEXT,status TEXT,created_at TEXT);
        CREATE TABLE order_receipts(order_id INTEGER);
        INSERT INTO orders VALUES(42,7,2000,'synthetic','TON','pending',
            '2026-09-08','','TON','');
        INSERT INTO orders VALUES(43,8,4000,'foreign','TON','pending',
            '2026-09-09','','TON','');
        INSERT INTO payment_sessions VALUES(999,43,'foreign-session','failed','2099-01-01');
        ''')
    store = order_read_store.SQLiteOrderReadStore(str(path))
    queries = []
    connect = store._c

    def readonly():
        c = connect()
        c.execute('PRAGMA query_only=ON')
        c.set_trace_callback(queries.append)
        return c

    store._c = readonly
    return path, store, queries


def serialize(store, *, authenticated=True):
    source = ROOT / 'relay-fastapi/main.py'
    function = next(n for n in ast.parse(source.read_text()).body
                    if isinstance(n, ast.AsyncFunctionDef) and n.name == 'api_history')
    function.decorator_list = []
    ctx = {'Request': object, 'HTTPException': HTTPException,
           'verify_init_data': lambda data: {'id': 7} if authenticated and data == 'signed-owner-seven' else None,
           '_order_reads': store, '_activity_read_store_module': activity_read_store,
           '_delayed_ids': lambda: set(), '_txid': txid, 'logger': logging.getLogger(__name__)}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[])), str(source), 'exec'), ctx)
    request = SimpleNamespace(headers={'X-Telegram-Init-Data': 'signed-owner-seven'},
                              query_params={'user_id': '8', 'session_token': 'foreign-session'})
    return asyncio.run(ctx['api_history'](request))


@pytest.mark.parametrize('status', sorted(activity_read_store.SESSION_STATES) + [None, '', 'future-state'])
@pytest.mark.parametrize('receipt', ['', 'stored', 'sent'])
def test_session_state_and_ui_precedence(ledger, status, receipt):
    path, store, queries = ledger
    with sqlite3.connect(path) as c:
        # Newest id deliberately has the OLDEST timestamp. An older active
        # session must not resurface when the latest session is closed/unknown.
        c.execute("INSERT INTO payment_sessions VALUES(1,42,'older-active','invoice_created','2099-01-01')")
        c.execute('INSERT INTO payment_sessions VALUES(2,42,?,?,?)', ('latest-session', status, '2000-01-01'))
        if receipt:
            c.execute('INSERT INTO order_receipts VALUES(42)')
        if receipt == 'sent':
            c.execute("UPDATE orders SET receipt_sent_at='2026-09-08' WHERE order_id=42")
    rows = activity_read_store.customer_orders(store, 7)
    assert len(queries) == 1 and queries[0].lstrip().upper().startswith('SELECT')
    expected = status if status in activity_read_store.SESSION_STATES else 'unknown'
    assert len(rows) == 1 and rows[0]['payment_session_state'] == expected
    assert rows[0]['session_token'] == (None if expected in {'failed', 'expired', 'unknown'} else 'latest-session')
    response = serialize(store)
    assert response[0]['order_id'] == 42 and response[0]['receipt'] == receipt
    assert response[0]['payment_session_state'] == expected
    assert 'foreign-session' not in json.dumps(response)
    result = subprocess.run(['node', str(ROOT / 'tests/e4_activity_session_behavior.cjs'),
                             str(ROOT / 'relay/webapp.html')], input=json.dumps(response),
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


def test_no_session_is_unknown_and_not_a_closed_payment(ledger):
    _, store, _ = ledger
    response = serialize(store)
    assert response[0]['payment_session_state'] == 'unknown'
    assert response[0]['session_token'] is None


def test_latest_active_session_replaces_older_failed_session(ledger):
    path, store, _ = ledger
    with sqlite3.connect(path) as c:
        c.executemany('INSERT INTO payment_sessions VALUES(?,?,?,?,?)', [
            (1,42,'failed-old','failed','2099-01-01'),
            (2,42,'active-new','invoice_created','2000-01-01')])
    response = serialize(store)
    assert response[0]['payment_session_state'] == 'invoice_created'
    assert response[0]['session_token'] == 'active-new'


def test_auth_failure_reads_nothing_and_owner_scope_ignores_query(ledger):
    _, store, queries = ledger
    with pytest.raises(HTTPException) as error:
        serialize(store, authenticated=False)
    assert error.value.status_code == 403 and queries == []
    assert [r['order_id'] for r in serialize(store)] == [42]
    assert activity_read_store.customer_orders(store, 999) == []


@pytest.mark.parametrize('uid', [0, -1, None, '7 OR 1=1'])
def test_invalid_owner_fails_before_read(ledger, uid):
    _, store, queries = ledger
    with pytest.raises((ValueError, TypeError)):
        activity_read_store.customer_orders(store, uid)
    assert queries == []


def test_limit_is_bounded(ledger):
    _, store, queries = ledger
    activity_read_store.customer_orders(store, 7, limit=10**9)
    assert queries[-1].endswith('LIMIT 100')
    activity_read_store.customer_orders(store, 7, limit=0)
    assert queries[-1].endswith('LIMIT 1')
