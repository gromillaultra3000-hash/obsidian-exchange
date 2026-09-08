"""Independent exact-handler acceptance. No application import or host ledger.

Uses retained installed order classes, the candidate adapter, real SQLite with
query_only, exact Telegram verifier and exact numeric proof code with explicitly
synthetic keys. Emits exact pay HTML for the disconnected browser rehearsal.
"""
import ast
import asyncio
from datetime import date, datetime
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
            missing=False, attack=False):
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
                'TON', '', 'sent-marker' if receipt == 'sent' else ''))
    if not missing:
        db.execute('INSERT INTO payment_sessions VALUES(?,?,?,?,?,?,?,?)',
                   (order_id*10, order_id, token, session, 2000,
                    repr({'requisites': req}), '', '2099-01-01T00:00:00Z'))
        if stale:
            db.execute('INSERT INTO payment_sessions VALUES(?,?,?,?,?,?,?,?)',
                       (order_id*10+1, order_id, f'newer-{order_id}', 'invoice_created',
                        2000, repr({'requisites': base_req}), '', '2099-01-01T00:00:00Z'))
    if receipt:
        db.execute('INSERT INTO order_receipts VALUES(?)', (order_id,))
    return order_id, token


matrix = []
for status in ['pending', 'paid', 'sent', 'expired', 'failed', 'cancelled']:
    for receipt in ['', 'stored', 'sent']:
        matrix.append((fixture(status, 'failed', receipt), status, receipt))
active = fixture()
stale = fixture(stale=True)
unknown = fixture(session='future-state')
missing = fixture(missing=True)
attack = fixture(attack=True)
db.execute('INSERT INTO payment_sessions VALUES(99999,99999,?,?,?,?,?,?)',
           ('orphan-fixture', 'invoice_created', 2000, '{}', '', '2099-01-01'))
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
main_path = ROOT / 'relay-fastapi/main.py'
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


for (order_id, token), status, receipt in matrix:
    result = api(order_id, request(7))
    assert result['status'] == status and result['receipt'] == receipt
    assert result['dead'] is (status == 'pending')
    assert api(order_id, request(token=token)) == result
    expect_error(f'{status}-{receipt}-foreign-owner', 404, lambda: api(order_id, request(8, token=token)))
    page = pay(token)
    assert isinstance(page, str) and '<!DOCTYPE html>' in page
    pages.append({'name': f'{status}-{receipt or "absent"}', 'html': page,
                  'expected': result, 'hasRequisites': False})
    proof = order_access.issue(order_id, 7)
    numeric = pay(str(order_id), request(proof=proof))
    assert isinstance(numeric, str)
    assert 'Реквизиты готовятся' not in numeric, (status, receipt)
    if status == 'pending':
        assert 'Обычно до 30 минут' not in numeric, receipt
    pages.append({'name': f'numeric-{status}-{receipt or "absent"}', 'html': numeric,
                  'expected': result, 'hasRequisites': False, 'numeric': True})
    cases.append({'name': f'exact-{status}-{receipt or "absent"}-opaque-and-numeric', 'result': 'PASS'})

for name, pair, expected_dead in [('active', active, False), ('stale', stale, True),
                                 ('unknown', unknown, True), ('attack', attack, False)]:
    order_id, token = pair
    result = api(order_id, request(token=token))
    assert result['dead'] is expected_dead
    pages.append({'name': name, 'html': pay(token), 'expected': result,
                  'hasRequisites': not expected_dead, 'maliciousValue': malicious if name == 'attack' else ''})
    cases.append({'name': name + '-opaque-state', 'result': 'PASS'})
assert api(missing[0], request(7))['dead'] is True
assert 'Не переводите по прежним реквизитам' in pay(str(missing[0]), request(proof=order_access.issue(missing[0], 7)))
active_redirect = pay(str(active[0]), request(proof=order_access.issue(active[0], 7)))
assert active_redirect.url == '/pay/' + active[1] and active_redirect.status_code == 302
cases.append({'name': 'numeric-current-only-redirect-and-no-session-closure', 'result': 'PASS'})

for token in ['', 'x'*257, '²', '１２', 'orphan-fixture', "' OR 1=1 --"]:
    expect_error('malformed-or-orphan-pay-' + repr(token[:20]), 404, lambda: pay(token))
for name, proof in [('absent', ''), ('oversized', 'x'*257), ('malformed', '1.2.3.4.é'),
                    ('expired', order_access.issue(active[0], 7, now=int(time.time())-7202)),
                    ('future', order_access.issue(active[0], 7, now=int(time.time())+5)),
                    ('other-order', order_access.issue(active[0]+1, 7)),
                    ('other-owner', order_access.issue(active[0], 8))]:
    expect_error('numeric-proof-' + name, 404, lambda: pay(str(active[0]), request(proof=proof)))
for name, req in [('absent', request()), ('foreign-token', request(token=matrix[0][0][1])),
                  ('owner-wins-token', request(8, token=active[1])),
                  ('internal-owner-wins-token', request(key=namespace['SECRET_KEY'], user_id='8', token=active[1])),
                  ('nonascii-key', request(key='é', user_id='7')),
                  ('invalid-key', request(key='wrong', user_id='7'))]:
    expect_error('api-auth-' + name, 404, lambda: api(active[0], req))
assert api(active[0], request(key=namespace['SECRET_KEY'], user_id='7'))['status'] == 'pending'
tampered = request(7)
tampered.headers['X-Telegram-Init-Data'] += 'x'
expect_error('invalid-telegram-signature', 404, lambda: api(active[0], tampered))


class ReadFailure:
    def __init__(self, method):
        self.method = method

    def __getattr__(self, name):
        if name == self.method:
            def fail(*args, **kwargs):
                raise sqlite3.OperationalError('synthetic read unavailable')
            return fail
        return getattr(reader, name)


for method in ['authorized_snapshot', 'get_by_token', 'authorized_state', 'session_closed']:
    namespace['_payment_status_reads'] = ReadFailure(method)
    expect_error('opaque-read-error-' + method, 503, lambda: pay(active[1]))
    if method != 'get_by_token':
        expect_error('api-read-error-' + method, 503, lambda: api(active[0], request(7)))
namespace['_payment_status_reads'] = ReadFailure('latest_active_for_authorized_order')
expect_error('numeric-session-read-error', 503,
             lambda: pay(str(active[0]), request(proof=order_access.issue(active[0], 7))))
namespace['_payment_status_reads'] = reader
assert all(q.lstrip().upper().startswith('SELECT ') for q in queries)
try:
    db.execute("UPDATE orders SET status='paid'")
except sqlite3.OperationalError:
    pass
else:
    raise AssertionError('query_only write guard failed')
# The two public handlers may not import providers or call payment writers.
for node in nodes:
    if node.name not in ('api_order', 'pay'):
        continue
    code = ast.unparse(node)
    assert 'providers.' not in code and '_mark_order_paid' not in code

fixture_report = {'schemaVersion': 'e4-payment-status-pages.v1', 'inputs': inputs, 'pages': pages,
                  'pollProgression': {'initial': 'active', 'closed': api(active[0], request(token=active[1]))}}
# Simulate a later canonical response using already executed exact closed data.
fixture_report['pollProgression']['closed'] = pages[0]['expected']
(OUT / 'acceptance-pages.json').write_text(json.dumps(fixture_report, ensure_ascii=False) + '\n')
inputs.append({'path': str(Path(__file__).relative_to(ROOT)), 'sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})
report = {'schemaVersion': 'e4-payment-status-handler-acceptance.v1', 'result': 'PASS',
    'method': 'Exact handler/helper/Telegram verifier ASTs, exact candidate adapter over retained installed SQLite class, in-memory query_only ledger, real HMAC with synthetic keys; generated exact HTML.',
    'inputs': inputs, 'installedInputs': [{'path': str(installed), 'sha256': hashlib.sha256(installed.read_bytes()).hexdigest()}],
    'cases': cases, 'count': len(cases), 'generatedPages': len(pages), 'selectQueries': len(queries),
    'databaseWritesAllowed': False, 'providerOrMoneyCalls': 0,
    'limitations': ['No ASGI server or production database imported. HTTPException/RedirectResponse are fixture equivalents.',
                    'Payout delay is a declared false fixture; that retained dependency is separately audited.',
                    'No production incident or loaded application-state claim.']}
(OUT / 'acceptance-probe.json').write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')
print(json.dumps({'result': report['result'], 'checks': len(cases), 'pages': len(pages)}))
