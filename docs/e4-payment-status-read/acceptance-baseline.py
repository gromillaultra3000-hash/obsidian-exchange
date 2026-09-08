"""Installed immediate dependency audit with synthetic read-only ledger only."""
import ast
import asyncio
from datetime import date, datetime
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
LIVE = Path('/opt/obsidian-exchange')
main_path = LIVE / 'relay-fastapi/main.py'
source = main_path.read_text()
required = {'order_read_store': ['authorized_snapshot'],
    'payment_session_store': ['get_by_token', 'latest_for_authorized_order',
        'latest_active_for_authorized_order', 'latest_provider_invoice_for_authorized_order'],
    'receipt_store': ['authorized_state']}
observed_inputs = []
contexts = {}
for name, methods in required.items():
    path = LIVE / 'relay/repositories' / (name + '.py')
    content = path.read_text()
    tree = ast.parse(content)
    nodes = [node for node in tree.body if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.Assign))
        or isinstance(node, ast.ImportFrom) and node.module == '__future__']
    namespace = {'date': date, 'datetime': datetime, 'Decimal': Decimal, 'sqlite3': sqlite3}
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), str(path), 'exec'), namespace)
    contexts[name] = namespace
    observed_inputs.append({'path': str(path), 'sha256': hashlib.sha256(content.encode()).hexdigest(),
        'requiredMethods': methods, 'installedClassMethods': {
            node.name: {method: hasattr(namespace[node.name], method) for method in methods}
            for node in tree.body if isinstance(node, ast.ClassDef)}})
assert all(not present for item in observed_inputs for methods in item['installedClassMethods'].values()
           for present in methods.values())
db = sqlite3.connect(':memory:')
db.executescript('''
CREATE TABLE orders(order_id INTEGER,user_id INTEGER,receipt_sent_at TEXT);
CREATE TABLE payment_sessions(id INTEGER,order_id INTEGER,session_token TEXT,status TEXT);
CREATE TABLE order_receipts(order_id INTEGER);
INSERT INTO orders VALUES(42,42,'2026-09-08 00:00');
INSERT INTO payment_sessions VALUES(1,42,'synthetic-only','failed');
INSERT INTO order_receipts VALUES(42);
''')
db.execute('PRAGMA query_only=ON')
reads = []
db.set_trace_callback(reads.append)
order_store = contexts['order_read_store']['SQLiteOrderReadStore']('unused')
session_store = contexts['payment_session_store']['SQLitePaymentSessionStore']('unused')
receipt_store = contexts['receipt_store']['SQLiteReceiptStore']('unused')
order_store._c = lambda: db
session_store._connect = lambda: db
receipt_store._c = lambda: db
warnings = []
namespace = {'Request': object, '_order_reads': order_store, '_payment_sessions': session_store,
    '_receipts': receipt_store, 'verify_init_data': lambda _: {'id': 42},
    'logger': SimpleNamespace(warning=lambda *args: warnings.append(str(args[0])), error=lambda *args: None)}


class SyntheticHTTPException(Exception):
    def __init__(self, status_code, detail=None):
        self.status_code = status_code


namespace['HTTPException'] = SyntheticHTTPException
selected = [node for node in ast.parse(source).body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name in ['api_order', 'pay', '_receipt_state', '_session_dead']]
for node in selected:
    node.decorator_list = []
exec(compile(ast.fix_missing_locations(ast.Module(body=selected, type_ignores=[])), str(main_path), 'exec'), namespace)
receipt_underlying = receipt_store.state(42)
session_underlying = session_store.latest_for_order(42)['status']
assert receipt_underlying == 'sent' and session_underlying == 'failed'
receipt_visible = namespace['_receipt_state'](42, user_id=42)
session_dead_visible = namespace['_session_dead'](42, user_id=42)
assert receipt_visible == '' and session_dead_visible is False
request = SimpleNamespace(headers={}, query_params={}, client=SimpleNamespace(host='synthetic-local'))
try:
    asyncio.run(namespace['api_order'](42, request))
except AttributeError as error:
    assert 'authorized_snapshot' in str(error)
    api_error = str(error)
else:
    raise AssertionError('missing order dependency was not reproduced')
try:
    asyncio.run(namespace['pay']('synthetic-only', request))
except SyntheticHTTPException as error:
    assert error.status_code == 500
else:
    raise AssertionError('missing session dependency was not reproduced')
assert all(statement.lstrip().upper().startswith('SELECT') for statement in reads)
db.close()
report = {'schemaVersion': 'e4-payment-status-read-acceptance-baseline.v1',
    'result': 'PREEXISTING_DEPENDENCY_FAILURES_REPRODUCED',
    'method': 'Exact installed class/handler/helper ASTs; real sqlite3 :memory: ledger with PRAGMA query_only=ON; synthetic verified identity. No application import, HTTP request, host DB, provider, wallet or real key access.',
    'inputs': [{'path': str(Path(__file__).relative_to(ROOT)), 'sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}],
    'installedInputs': [{'path': str(main_path), 'sha256': hashlib.sha256(source.encode()).hexdigest()}] + observed_inputs,
    'missingProofModule': not (LIVE / 'relay/core/order_access.py').exists(),
    'apiOrder': {'errorType': 'AttributeError', 'error': api_error, 'failsBeforeDatabaseOrProvider': True},
    'opaquePay': {'handlerExceptionStatus': 500, 'failsAt': 'payment_session_store.get_by_token'},
    'receiptHelper': {'actualLegacyState': receipt_underlying, 'helperReturned': receipt_visible,
        'missingAuthorizedMethodSilentlyTreatedAsNoReceipt': True},
    'sessionHelper': {'actualLegacyLatestState': session_underlying, 'helperReturnedDead': session_dead_visible,
        'missingAuthorizedMethodSilentlyTreatedAsNotClosed': True},
    'databaseReadQueries': len(reads), 'databaseWritesAllowed': False,
    'noUnauthenticatedFallbackPermitted': True,
    'limitations': ['Installed source and exact isolated behavior are proven, not actual customer incidence or loaded production object state.',
        'Legacy unscoped methods are used only as synthetic-ledger reference observations; they are not acceptable authorization fallbacks in repaired handlers.']}
(OUT / 'acceptance-baseline.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps({'result': report['result'], 'missingMethodNames': sum(map(len, required.values())),
    'receiptLost': receipt_visible == '', 'closureLost': session_dead_visible is False,
    'numericProofModuleMissing': report['missingProofModule']}))
