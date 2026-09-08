"""Independent exact-handler acceptance. No application import or host ledger.

Uses retained installed order classes, the candidate adapter, real SQLite with
query_only, exact Telegram verifier and exact numeric proof code with explicitly
synthetic keys. Emits exact pay HTML for the disconnected browser rehearsal.
"""
import ast
import asyncio
from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
import hmac
from io import BytesIO
import json
from pathlib import Path
import sqlite3
import sys
import time
from types import ModuleType, SimpleNamespace
import urllib.parse

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'relay'))
from core import order_access, txid

paths = ['relay-fastapi/main.py', 'relay/repositories/payment_status_read_store.py',
         'relay/core/order_access.py', 'relay/core/telegram_freshness.py',
         'relay/core/requisites.py', 'relay/services/requisite_origin.py', 'relay/core/txid.py']
inputs = [{'path': p, 'sha256': hashlib.sha256((ROOT / p).read_bytes()).hexdigest()} for p in paths]
installed = Path('/opt/obsidian-exchange/relay/repositories/order_read_store.py')
tree = ast.parse(installed.read_text())
ns = {'date': date, 'datetime': datetime, 'Decimal': Decimal, 'sqlite3': sqlite3}
nodes = [n for n in tree.body if isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.Assign))]
exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), str(installed), 'exec'), ns)
adapter_source = ROOT / 'relay/repositories/payment_status_read_store.py'
nodes = [n for n in ast.parse(adapter_source.read_text()).body if not isinstance(n, ast.ImportFrom)]
exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), str(adapter_source), 'exec'), ns)
db = sqlite3.connect(':memory:')
db.row_factory = sqlite3.Row
db.executescript('''
CREATE TABLE orders(order_id INTEGER PRIMARY KEY,user_id INTEGER,rub_amount NUMERIC,
 status TEXT,paid_btc_tx TEXT,currency TEXT,network TEXT,verification_requested TEXT,receipt_sent_at TEXT);
CREATE TABLE payment_sessions(id INTEGER PRIMARY KEY,order_id INTEGER,session_token TEXT UNIQUE,
 status TEXT,amount NUMERIC,provider_payload TEXT,qr_payload TEXT,expires_at TEXT);
CREATE TABLE order_receipts(order_id INTEGER PRIMARY KEY);
''')
base_req = {'phone': '+000 SYNTHETIC ONLY', 'recipient': 'Synthetic Fixture', 'bank_name': 'Fixture bank'}
malicious = "</script><script>window.__injected=1</script><img src=x onerror='window.__injected=2'>\"');window.__injected=3;//\u2028\u2029END"
cases, pages = [], []
oid = 0


def fixture(status='pending', session='invoice_created', receipt='', *, stale=False,
            missing=False, attack=False, verification="", expires="2099-01-01T00:00:00Z"):
    global oid
    oid += 1
    order_id = oid
    token = f'synthetic-latest-{order_id}'
    currency = malicious if attack else 'TON'
    req = dict(base_req)
    if attack:
        req.update(phone=malicious, recipient=malicious, bank_name=malicious)
    db.execute('INSERT INTO orders VALUES(?,?,?,?,?,?,?,?,?)',
               (order_id, 7, 2000, status, 'a'*64 if status == 'sent' else '', currency,
                'TON', verification, 'sent-marker' if receipt == 'sent' else ''))
    if not missing:
        db.execute('INSERT INTO payment_sessions VALUES(?,?,?,?,?,?,?,?)',
                   (order_id*10, order_id, token, session, 2000,
                    repr({'requisites': req}), '', expires))
        if stale:
            db.execute('INSERT INTO payment_sessions VALUES(?,?,?,?,?,?,?,?)',
                       (order_id*10+1, order_id, f'newer-{order_id}', 'invoice_created',
                        2000, repr({'requisites': base_req}), '', '2099-01-01T00:00:00Z'))
    if receipt:
        db.execute('INSERT INTO order_receipts VALUES(?)', (order_id,))
    return order_id, token


matrix = []
for receipt in ['', 'stored', 'sent']:
    for unavailable in [False, True]:
        for verification in ['', 'video', 'pdf']:
            pair = fixture(session='failed' if unavailable else 'invoice_created',
                           receipt=receipt, verification=verification)
            matrix.append((pair, receipt, unavailable, verification))
controls = []
for status in ['expired', 'failed', 'cancelled']:
    for receipt in ['stored', 'sent']:
        controls.append((f'{status}-{receipt}', fixture(status=status, session='failed',
                         receipt=receipt, verification='video')))
for status in ['paid', 'sent']:
    for receipt in ['', 'stored', 'sent']:
        controls.append((f'{status}-{receipt or "absent"}', fixture(status=status, receipt=receipt)))
# PostgreSQL TIMESTAMPTZ maps to an aware datetime. Use the exact retained
# serializer to construct a supported value without opening PostgreSQL.
aware_expiry = ns['_value'](datetime(2099, 1, 1, tzinfo=timezone.utc))
assert aware_expiry == '2099-01-01T00:00:00+00:00'
aware_fixture = fixture(expires=aware_expiry)
db.commit()
db.execute('PRAGMA query_only=ON')
queries = []
db.set_trace_callback(queries.append)
store = ns['SQLiteOrderReadStore']('not-used')
store._c = lambda: db
reader = ns['PaymentStatusReadStore'](store)


class HTTPException(Exception):
    def __init__(self, status_code, detail=None):
        self.status_code = status_code


class RedirectResponse:
    def __init__(self, url, status_code):
        self.url, self.status_code = url, status_code


audit = []
warnings = []
synthetic_bot_key = 'synthetic-only-not-a-telegram-token'
namespace = {'Request': object, 'HTTPException': HTTPException, 'RedirectResponse': RedirectResponse,
    '_payment_status_reads': reader, '_txid': txid, '_payout_delayed': lambda _: False,
    'audit_log': lambda *args: audit.append(args[0]),
    'logger': SimpleNamespace(warning=lambda *args: warnings.append(args[0]), error=lambda *args: None),
    'SECRET_KEY': 'synthetic-only-internal-key', 'BOT_TOKEN': synthetic_bot_key,
    'hmac': hmac, 'hashlib': hashlib, 'urllib': urllib, 'json': json, 'BytesIO': BytesIO}
main_path = ROOT / ('output/manual/e4-payment-pending-receipt-20260908/baseline/relay-fastapi/main.py' if '--baseline' in sys.argv else 'relay-fastapi/main.py')
inputs = [row for row in inputs if row['path'] != 'relay-fastapi/main.py'] + [{'path': str(main_path.relative_to(ROOT)), 'sha256': hashlib.sha256(main_path.read_bytes()).hexdigest()}]
all_nodes = ast.parse(main_path.read_text()).body
nodes = [n for n in all_nodes if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    and n.name in ['api_order', 'pay', '_receipt_state', '_session_dead', 'verify_init_data']]
for n in nodes:
    n.decorator_list = []
exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), str(main_path), 'exec'), namespace)
# Pure proof cryptography uses a fixture key; _secret is never called against env.
order_access._secret = lambda: b'synthetic-only-proof-key'


def request(uid=None, **query):
    headers = {}
    if uid is not None:
        data = {'auth_date': str(int(time.time())), 'user': json.dumps({'id': uid})}
        body = '\n'.join(f'{k}={v}' for k, v in sorted(data.items()))
        key = hmac.new(b'WebAppData', synthetic_bot_key.encode(), hashlib.sha256).digest()
        data['hash'] = hmac.new(key, body.encode(), hashlib.sha256).hexdigest()
        headers['X-Telegram-Init-Data'] = urllib.parse.urlencode(data)
    return SimpleNamespace(headers=headers, query_params=query, client=SimpleNamespace(host='synthetic-local'))


def api(order_id, req):
    return asyncio.run(namespace['api_order'](order_id, req))


def pay(token, req=None):
    return asyncio.run(namespace['pay'](token, req or request()))


def expect_error(name, status, call):
    try:
        call()
    except HTTPException as error:
        assert error.status_code == status, (name, error.status_code)
    else:
        raise AssertionError(name + ' did not reject')
    cases.append({'name': name, 'status': status, 'result': 'PASS'})


baseline = '--baseline' in sys.argv
numeric_mismatches = []
for (order_id, token), receipt, unavailable, verification in matrix:
    result = api(order_id, request(7))
    assert result['status'] == 'pending' and result['receipt'] == receipt
    assert result['verification'] == verification and result['dead'] is unavailable
    assert api(order_id, request(token=token)) == result
    name = f'pending-{receipt or "absent"}-{"unavailable" if unavailable else "active"}-{verification or "none"}'
    expect_error(name + '-foreign-owner', 404, lambda: api(order_id, request(8, token=token)))
    pages.append({'name': name, 'html': pay(token), 'expected': result, 'pending': True})
    if not verification:
        numeric = pay(str(order_id), request(proof=order_access.issue(order_id, 7)))
        if unavailable:
            assert isinstance(numeric, str)
            if receipt == 'stored' and '<h1>Файл чека получен</h1>' not in numeric:
                numeric_mismatches.append(name)
            pages.append({'name': 'numeric-' + name, 'html': numeric,
                          'expected': result, 'pending': True, 'numeric': True})
        else:
            assert numeric.status_code == 302 and numeric.url == '/pay/' + token
    cases.append({'name': name + '-exact-api-and-page', 'result': 'PASS'})

for name, (order_id, token) in controls:
    result = api(order_id, request(token=token))
    assert result['status'] == name.split('-')[0] and result['dead'] is False
    pages.append({'name': name, 'html': pay(token), 'expected': result, 'pending': False})
    cases.append({'name': name + '-canonical-regression', 'result': 'PASS'})

order_id, token = aware_fixture
result = api(order_id, request(token=token))
pages.append({'name': 'aware-expiry-format', 'html': pay(token), 'expected': result,
              'pending': True, 'expiryFormatProbe': True, 'serializedExpiry': aware_expiry})
cases.append({'name': 'aware-datetime-uses-exact-retained-serializer', 'result': 'PASS'})
if baseline:
    assert numeric_mismatches == ['pending-stored-unavailable-none']
else:
    assert not numeric_mismatches, numeric_mismatches
assert all(query.lstrip().upper().startswith('SELECT ') for query in queries)
for path in [Path(__file__), ROOT / 'deploy/postgres/007_payment_sessions.sql']:
    inputs.append({'path': str(path.relative_to(ROOT)), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
if not baseline:
    (OUT / 'acceptance-pages.json').write_text(json.dumps({
        'schemaVersion': 'e4-payment-pending-receipt-pages.v1', 'inputs': inputs, 'pages': pages,
        'backend': 'Exact installed SQLite class + unchanged adapter; query_only in-memory synthetic ledger',
    }, ensure_ascii=False) + '\n')
report = {'schemaVersion': 'e4-payment-pending-receipt-handler-acceptance.v1',
    'result': 'BASELINE_PENDING_RECEIPT_OMISSION_REPRODUCED' if baseline else 'PASS',
    'method': 'Exact api_order/pay/helper ASTs over real query_only SQLite with retained installed class and unchanged adapter. Synthetic Telegram/proof HMAC only. Baseline emits no duplicate page bundle.',
    'inputs': inputs,
    'installedInputs': [{'path': str(installed), 'sha256': hashlib.sha256(installed.read_bytes()).hexdigest()}],
    'cases': cases, 'count': len(cases), 'generatedPages': len(pages),
    'baselinePagesRetained': False, 'numericStoredReceiptMismatches': numeric_mismatches,
    'selectQueries': len(queries), 'databaseWritesAllowed': False, 'providerOrMoneyCalls': 0,
    'awareExpiryProbe': {'supportedColumn': 'payment_sessions.expires_at TIMESTAMPTZ',
        'exactRetainedSerializerResult': aware_expiry,
        'method': 'datetime(2099,1,1,tzinfo=UTC) through installed order-store _value; resulting string through the exact pay handler. No PostgreSQL runtime or host data.'},
    'limits': ['No application/ASGI import, live account/database/provider, real authority or production actions.',
               'Current exact HTML is rendered by separate actual-browser evidence; baseline opaque omission is already proven by the previous sealed terminal-slice next prerequisite.',
               'Database/API/read behavior is unchanged, so PostgreSQL is not rerun for this presentation change.']}
name = 'acceptance-baseline.json' if baseline else 'acceptance-probe.json'
(OUT / name).write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')
print(json.dumps({'result': report['result'], 'checks': len(cases), 'pages': len(pages),
                  'numericMismatches': len(numeric_mismatches)}))

