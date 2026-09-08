"""Real read-only SQLite checks for the installed-store-compatible page adapter."""
from pathlib import Path
import sqlite3
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'relay'))
from repositories.order_read_store import SQLiteOrderReadStore
from repositories.payment_status_read_store import PaymentStatusReadStore
from e4_payment_status_fixture import fixtures, verify


@pytest.fixture
def ledger(tmp_path):
    path = tmp_path / 'synthetic.db'
    with sqlite3.connect(path) as c:
        states = fixtures(c)
    store = SQLiteOrderReadStore(str(path))
    queries = []
    connect = store._c

    def readonly():
        c = connect()
        c.execute('PRAGMA query_only=ON')
        c.set_trace_callback(queries.append)
        return c

    store._c = readonly
    return path, PaymentStatusReadStore(store), states, queries


def test_owner_session_receipt_matrix_uses_only_bounded_selects(ledger):
    _, reader, states, queries = ledger
    assert verify(reader, states) == 26
    assert all(q.startswith('SELECT ') and q.endswith('LIMIT 1') for q in queries)


@pytest.mark.parametrize('method', ['authorized_snapshot', 'latest_for_authorized_order',
    'latest_active_for_authorized_order', 'session_closed', 'authorized_state'])
@pytest.mark.parametrize('authority', [{}, {'user_id': 0}, {'user_id': -1},
    {'user_id': True}, {'user_id': '7 OR 1=1'}, {'session_token': 'x'*257}])
def test_invalid_authority_never_opens_database(ledger, method, authority):
    _, reader, _, queries = ledger
    with pytest.raises((ValueError, TypeError)):
        getattr(reader, method)(1, **authority)
    assert queries == []


@pytest.mark.parametrize('receipt', ['', 'stored', 'sent'])
@pytest.mark.parametrize('state', ['pending', 'paid', 'sent', 'expired', 'cancelled', 'failed'])
def test_reads_preserve_canonical_order_outcome_and_independent_receipt(ledger, receipt, state):
    path, reader, _, _ = ledger
    with sqlite3.connect(path) as c:
        c.execute('UPDATE orders SET status=?,receipt_sent_at=? WHERE order_id=1',
                  (state, 'timestamp' if receipt == 'sent' else ''))
        if not receipt:
            c.execute('DELETE FROM order_receipts WHERE order_id=1')
    assert reader.authorized_snapshot(1, user_id=7)['status'] == state
    assert reader.authorized_state(1, user_id=7) == receipt


def test_database_failure_is_not_an_absence(ledger):
    path, reader, _, _ = ledger
    with sqlite3.connect(path) as c:
        c.execute('DROP TABLE order_receipts')
    with pytest.raises(sqlite3.OperationalError):
        reader.authorized_state(1, user_id=7)


def test_unknown_repository_is_rejected():
    with pytest.raises(TypeError):
        PaymentStatusReadStore(object())
