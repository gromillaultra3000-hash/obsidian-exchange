"""Exact read-only repository SQL and history serialization, in-memory data only."""
import ast
import asyncio
from datetime import date, datetime
from decimal import Decimal
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
backend = ROOT / 'relay-fastapi/main.py'
order_source = ROOT / 'relay/repositories/order_read_store.py'
session_source = ROOT / 'relay/repositories/payment_session_store.py'


def isolated(path, names, class_name=None, context=None):
    tree = ast.parse(path.read_text())
    body = tree.body if class_name is None else next(
        node.body for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name)
    nodes = [node for node in body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names]
    assert {node.name for node in nodes} == set(names)
    for node in nodes:
        node.decorator_list = []
    namespace = {} if context is None else context
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), str(path), 'exec'), namespace)
    return namespace


db = sqlite3.connect(':memory:')
db.row_factory = sqlite3.Row
db.executescript('''
CREATE TABLE orders(order_id INTEGER, user_id INTEGER, rub_amount REAL,
 crypto_address TEXT, currency TEXT, status TEXT, created_at TEXT,
 paid_btc_tx TEXT, network TEXT, receipt_sent_at TEXT);
CREATE TABLE payment_sessions(id INTEGER, order_id INTEGER, session_token TEXT,
 status TEXT, created_at TEXT);
CREATE TABLE order_receipts(order_id INTEGER);
INSERT INTO orders VALUES(42,42,2000,'synthetic-address','TON','pending',
 '2026-09-08 00:00','','TON','');
INSERT INTO payment_sessions VALUES(1,42,'synthetic_closed_session','failed',
 '2026-09-08 00:01');
''')
value_context = isolated(order_source, ['_value', '_dict'], context={
    'Decimal': Decimal, 'datetime': datetime, 'date': date})
order_methods = isolated(order_source, ['customer_orders', 'receipt_order_ids'],
    'SQLiteOrderReadStore', value_context)
order_reads = SimpleNamespace(_c=lambda: db)
for name in ['customer_orders', 'receipt_order_ids']:
    setattr(order_reads, name, lambda *args, _name=name, **kwargs: order_methods[_name](order_reads, *args, **kwargs))
session_context = isolated(session_source, ['_order_authority'], context={'Any': Any})
session_methods = isolated(session_source, ['latest_for_authorized_order'],
    'SQLitePaymentSessionStore', session_context)
payment_sessions = SimpleNamespace(_connect=lambda: db)
payment_sessions.latest_for_authorized_order = lambda *args, **kwargs: session_methods[
    'latest_for_authorized_order'](payment_sessions, *args, **kwargs)
spec = importlib.util.spec_from_file_location('acceptance_txid', ROOT / 'relay/core/txid.py')
txid = importlib.util.module_from_spec(spec)
spec.loader.exec_module(txid)
context = isolated(backend, ['api_history', '_session_dead'], context={
    'Request': object, 'verify_init_data': lambda _: {'id': 42},
    '_order_reads': order_reads, '_payment_sessions': payment_sessions,
    '_delayed_ids': lambda: set(), '_txid': txid})
request = SimpleNamespace(headers={'X-Telegram-Init-Data': 'synthetic-only'})
response = asyncio.run(context['api_history'](request))
dead = context['_session_dead'](42, user_id=42)
assert dead is True
assert response[0]['status'] == 'pending'
assert response[0]['session_token'] is None
assert 'dead' not in response[0]
report = {
    'schemaVersion': 'e4-activity-session-lifecycle-contract-reproduction.v1',
    'result': 'VALID_BACKEND_STATE_REPRODUCED',
    'method': 'AST-extracted exact SQLite read methods over sqlite3 :memory: fixtures, exact api_history and _session_dead functions; only pure core.txid imported. No application import, production DB, real identity, provider or network calls.',
    'inputs': [{'path': str(path.relative_to(ROOT)), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        for path in [backend, order_source, session_source, ROOT / 'relay/core/txid.py']],
    'fixture': {'orderStatus': 'pending', 'latestPaymentSessionStatus': 'failed', 'receiptPresent': False},
    'actualRepositoryLatestSession': payment_sessions.latest_for_authorized_order(42, user_id=42),
    'actualSessionDead': dead,
    'apiResponse': response,
    'omittedSessionLifecycle': 'dead' not in response[0],
    'productionDataAccessed': False,
}
(OUT / 'next-prerequisite-backend.json').write_text(json.dumps(report, indent=2) + '\n')
db.close()
print(json.dumps({'result': report['result'], 'actualSessionDead': dead,
    'historyStatus': response[0]['status'], 'sessionTokenAbsent': response[0]['session_token'] is None}))
