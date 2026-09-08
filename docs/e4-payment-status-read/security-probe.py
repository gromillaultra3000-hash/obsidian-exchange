#!/usr/bin/env python3
"""Independent synthetic SQL, handler authority, proof and HTML/JS safety probes.

No application startup, host database, production HTTP, provider or real key use.
"""
import ast
import asyncio
import hashlib
import hmac
from html.parser import HTMLParser
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
from types import SimpleNamespace

ROOT = Path('/root')
sys.path.insert(0, str(ROOT / 'relay'))
from repositories.order_read_store import SQLiteOrderReadStore, PostgresOrderReadStore
from repositories.payment_status_read_store import PaymentStatusReadStore
from core import order_access

MAIN = ROOT / 'relay-fastapi/main.py'
SOURCE = MAIN.read_text()
cases = []


def check(name, condition):
    assert condition, name
    cases.append(name)


class HTTPError(Exception):
    def __init__(self, status_code, detail=None):
        self.status_code = status_code


db = sqlite3.connect(':memory:')
db.row_factory = sqlite3.Row
db.executescript('''
CREATE TABLE orders(order_id INTEGER PRIMARY KEY,user_id INTEGER,rub_amount NUMERIC,
 status TEXT,paid_btc_tx TEXT,currency TEXT,network TEXT,verification_requested TEXT,receipt_sent_at TEXT);
CREATE TABLE payment_sessions(id INTEGER PRIMARY KEY,order_id INTEGER,session_token TEXT,
 status TEXT,provider_payload TEXT,qr_payload TEXT,expires_at TEXT,amount NUMERIC,created_at TEXT);
CREATE TABLE order_receipts(order_id INTEGER PRIMARY KEY);
''')
states = ['created', 'invoice_created', 'awaiting_payment', 'payment_detected',
          'confirming', 'payout_queued', 'payout_sent', 'completed', 'paid',
          'failed', 'expired', 'unknown-next', None, '']
for oid, state in enumerate(states, 101):
    db.execute('INSERT INTO orders VALUES(?,?,1500,?,?,?,?,?,?)',
               (oid, 7, 'pending', '', 'TON', 'TON', '', ''))
    db.execute('INSERT INTO order_receipts VALUES(?)', (oid,))
    for ident, token, status, created in [(oid*10, f'old-{oid}', 'created', '2099'),
                                        (oid*10+1, f'current-{oid}', state, '2000')]:
        db.execute('INSERT INTO payment_sessions VALUES(?,?,?,?,?,?,?,?,?)',
                   (ident, oid, token, status, '{}', '', '', 1500, created))
db.execute("INSERT INTO orders VALUES(202,8,2500,'sent','','TON','TON','','sent-marker')")
db.execute('INSERT INTO order_receipts VALUES(202)')
db.execute("INSERT INTO payment_sessions VALUES(2021,202,'foreign-current','invoice_created','{}','','',2500,'2000')")
db.execute("INSERT INTO payment_sessions VALUES(9999,9999,'orphan-current','invoice_created','{}','','',2500,'2000')")
db.execute("INSERT INTO orders VALUES(303,7,2500,'pending','','TON','TON','','')")
db.commit()
before_changes = db.total_changes
db.execute('PRAGMA query_only=ON')
queries = []
db.set_trace_callback(queries.append)
store = SQLiteOrderReadStore('not-used')
store._c = lambda: db
reader = PaymentStatusReadStore(store)

for oid, state in enumerate(states, 101):
    closed = state not in {'created', 'invoice_created', 'awaiting_payment'}
    check(f'{state!s}: owner read', reader.authorized_snapshot(oid, user_id=7)['status'] == 'pending')
    check(f'{state!s}: foreign owner plus correct bearer denied',
          reader.authorized_snapshot(oid, user_id=8, session_token=f'current-{oid}') is None)
    check(f'{state!s}: bearer scoped to own order',
          reader.authorized_snapshot(oid, session_token='foreign-current') is None)
    check(f'{state!s}: highest ID beats timestamp',
          reader.latest_for_authorized_order(oid, user_id=7)['session_token'] == f'current-{oid}')
    check(f'{state!s}: no post-payment or unknown transfer invitation',
          reader.session_closed(oid, user_id=7) == closed)
    check(f'{state!s}: stale bearer never displays old requisites',
          reader.session_closed(oid, session_token=f'old-{oid}') is True)
    check(f'{state!s}: no older active fallback',
          reader.latest_active_for_authorized_order(oid, user_id=7) ==
          (None if closed else {'session_token': f'current-{oid}'}))
    check(f'{state!s}: foreign receipt denied',
          reader.authorized_state(oid, user_id=8, session_token=f'current-{oid}') == '')

check('authorized stored receipt', reader.authorized_state(101, user_id=7) == 'stored')
check('authorized sent receipt', reader.authorized_state(202, session_token='foreign-current') == 'sent')
check('missing session is unusable', reader.session_closed(303, user_id=7))
check('missing receipt remains empty', reader.authorized_state(303, user_id=7) == '')
check('orphan session page denied', reader.get_by_token('orphan-current') is None)
check('SQL token injection treated as bound data', reader.get_by_token("' OR 1=1 --") is None)
check('authorized opaque payload selected', reader.get_by_token('foreign-current')['order_id'] == 202)
check('UID takes precedence even over oversized bearer',
      reader.authorized_snapshot(101, user_id=7, session_token='x'*257)['order_id'] == 101)
for value in ['', 'x'*257, None]:
    before = len(queries)
    check('invalid token denied before SQL', reader.get_by_token(value) is None and len(queries) == before)
for authority in [{}, {'user_id': 0}, {'user_id': True}, {'user_id': '7 OR 1=1'}, {'session_token': 'x'*257}]:
    for method in ['authorized_snapshot', 'latest_for_authorized_order',
                   'latest_active_for_authorized_order', 'session_closed', 'authorized_state']:
        before = len(queries)
        try:
            getattr(reader, method)(101, **authority)
        except (TypeError, ValueError):
            check(f'{method}: malformed authority no SQL', len(queries) == before)
        else:
            raise AssertionError('invalid authority accepted')

# Exercise the real PG branch with a capture-only connection; actual engine
# execution belongs to the separately reviewed disposable PostgreSQL rehearsal.
pg_queries = []
class Capture:
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def execute(self, sql, params):
        pg_queries.append((sql, params))
        return SimpleNamespace(fetchone=lambda: None)
pg_store = PostgresOrderReadStore.__new__(PostgresOrderReadStore)
pg_store._c = lambda: Capture()
pg = PaymentStatusReadStore(pg_store)
pg.authorized_snapshot(101, user_id=7, session_token='foreign-current')
pg.authorized_state(101, session_token="' OR 1=1 --")
pg.get_by_token("' OR 1=1 --")
pg.latest_for_authorized_order(101, user_id=7)
check('PG placeholders and parameter arity preserved', all('?' not in sql and sql.count('%s') == len(params) for sql, params in pg_queries))
check('PG UID removes alternate bearer', pg_queries[0][1] == (101, 7, None))
check('PG injection absent from SQL text', all("' OR 1=1" not in sql for sql, _ in pg_queries))

logs = []
namespace = {'Request': object, 'HTTPException': HTTPError, 'hmac': hmac,
    'SECRET_KEY': 'synthetic-internal-authority', '_payment_status_reads': reader,
    'verify_init_data': lambda text: {'id': 7} if text == 'synthetic-owner' else None,
    '_txid': SimpleNamespace(explorer_url=lambda *args: ''),
    '_payout_delayed': lambda oid: False,
    'audit_log': lambda *args: None,
    'logger': SimpleNamespace(warning=lambda *args: logs.append(args), error=lambda *args: logs.append(args)),
    'RedirectResponse': lambda url, status_code: {'url': url, 'status_code': status_code}}

def compile_handlers(source):
    nodes = [n for n in ast.parse(source).body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
             and n.name in {'api_order', 'pay', '_receipt_state', '_session_dead'}]
    for node in nodes:
        node.decorator_list = []
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), str(MAIN), 'exec'), namespace)

compile_handlers(SOURCE)

def request(header='', **query):
    return SimpleNamespace(headers={'X-Telegram-Init-Data': header}, query_params=query,
                           client=SimpleNamespace(host='synthetic-local'))

def call(name, value, req=None):
    return asyncio.run(namespace[name](value, req or request()))

def denied(name, value, req, status, label, no_sql=False):
    before = len(queries)
    try:
        call(name, value, req)
    except HTTPError as error:
        check(label, error.status_code == status and (not no_sql or len(queries) == before))
    else:
        raise AssertionError(label)

denied('api_order', 101, request(), 404, 'API no authority fails before SQL', True)
denied('api_order', 202, request('synthetic-owner', token='foreign-current'), 404,
       'API signed UID wins foreign bearer')
denied('api_order', 101, request(token='foreign-current'), 404, 'API foreign bearer denied')
denied('api_order', 202, request(key='synthetic-internal-authority', user_id='7', token='foreign-current'),
       404, 'API internal UID also wins foreign bearer')
check('API authorized status and receipt from canonical ledger',
      call('api_order', 101, request('synthetic-owner')) == {'status': 'pending', 'txid': '',
          'verification': '', 'receipt': 'stored', 'delayed': False, 'dead': False, 'tx_url': ''})
check('API old bearer retains status authority but closes instructions',
      call('api_order', 101, request(token='old-101'))['dead'] is True)
check('API sent ledger takes precedence over session state',
      call('api_order', 202, request(token='foreign-current'))['status'] == 'sent')
for method, action in [('authorized_snapshot', lambda: call('api_order', 101, request('synthetic-owner'))),
                       ('authorized_state', lambda: namespace['_receipt_state'](101, user_id=7)),
                       ('session_closed', lambda: namespace['_session_dead'](101, user_id=7)),
                       ('get_by_token', lambda: call('pay', 'current-101'))]:
    saved = getattr(reader, method)
    setattr(reader, method, lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError('synthetic read failure')))
    try:
        action()
    except HTTPError as error:
        check(f'{method}: failure is 503 rather than absence', error.status_code == 503)
    else:
        raise AssertionError('read failure hidden')
    setattr(reader, method, saved)

# Synthetic key replacement occurs before invoking any issuer/verifier; no
# actual RELAY_SECRET or full process environment is inspected.
order_access._secret = lambda: b'synthetic-review-key-only'
proof = order_access.issue(101, 7, now=20000)
check('proof round trip', order_access.verify(proof, 101, now=20001) == 7)
check('proof wrong order denied', order_access.verify(proof, 202, now=20001) is None)
check('proof expired denied', order_access.verify(proof, 101, now=30000) is None)
check('proof future denied', order_access.verify(proof, 101, now=19998) is None)
for value in [proof[:-1]+'z', proof.rsplit('.', 1)[0]+'.'+'я'*64, 'x'*257, '', '1.2.3.4']:
    check('malformed proof rejected without exception', order_access.verify(value, 101, now=20001) is None)
for value in ['', 'x'*257, '0', '101']:
    denied('pay', value, request(), 404, 'proofless or bounded numeric page denied before SQL', True)
denied('pay', '101', request(proof='x'*257), 404, 'oversized numeric proof no SQL', True)
proof = order_access.issue(101, 7)
redirect = call('pay', '101', request(proof=proof))
check('numeric proof redirects only authorized current session',
      redirect == {'url': '/pay/current-101', 'status_code': 302})
denied('pay', '202', request(proof=order_access.issue(202, 7)), 404,
       'signed proof cannot read another owner ledger')
denied('pay', 'orphan-current', request(), 404, 'opaque orphan page denied')
unavailable = call('pay', '104', request(proof=order_access.issue(104, 7)))
check('post-payment numeric fallback offers no payment or false closure promise',
      'Реквизиты недоступны' in unavailable and 'href="/pay/' not in unavailable)

# A provider-controlled string must remain data both in script JSON and in the
# generated copy-button attribute. No actual browser/clipboard/network is used.
payload = 'Synthetic </script><script>globalThis.__securityProbe=1</script> & \u2028\u2029 end'
detail = "7');globalThis.__securityProbe=2;//\" data-extra=\"oops"
saved_reader = namespace['_payment_status_reads']
fake = SimpleNamespace(get_by_token=lambda value: {'order_id': 101, 'amount': 1500,
        'provider_payload': repr({'requisites': {'bank_name': payload, 'phone': detail}}),
        'expires_at': '', 'qr_payload': '', 'status': 'invoice_created'},
    authorized_snapshot=lambda *args, **kwargs: {'order_id': 101, 'rub_amount': 1500,
        'status': 'pending', 'paid_btc_tx': '', 'currency': 'TON', 'network': 'TON', 'verification_requested': ''},
    authorized_state=lambda *args, **kwargs: '', session_closed=lambda *args, **kwargs: False)
namespace['_payment_status_reads'] = fake
page = call('pay', 'synthetic-page')
class Tags(HTMLParser):
    def __init__(self):
        super().__init__(); self.tags = []
    def handle_starttag(self, tag, attrs): self.tags.append((tag, dict(attrs)))
tags = Tags(); tags.feed(page)
check('provider JSON cannot terminate HTML script', sum(tag == 'script' for tag, _ in tags.tags) == 1)
script = page.split('<script>', 1)[1].split('</script>', 1)[0]
check('script JSON escapes HTML metacharacters and separators',
      '\\u003c/script\\u003e' in script and '\\u0026' in script and '\\u2028' in script and '\\u2029' in script)
js = r'''
const vm=require('node:vm'); const fs=require('node:fs');
const script=JSON.parse(fs.readFileSync(0,'utf8')); const view={innerHTML:''};
const c={document:{getElementById:()=>view},setInterval:()=>0,clearInterval:()=>{},setTimeout:()=>0};
vm.createContext(c); vm.runInContext(script,c); const html=view.innerHTML;
vm.runInContext('C.dead=true;C.receipt="stored";render()',c);
const storedDead=view.innerHTML;
vm.runInContext('C.receipt="sent";render()',c); const sentDead=view.innerHTML;
process.stdout.write(JSON.stringify({html,storedDead,sentDead,injected:c.__securityProbe||null}));
'''
rendered = json.loads(subprocess.run(['node', '-e', js], input=json.dumps(script),
                        text=True, capture_output=True, check=True).stdout)
buttons = Tags(); buttons.feed(rendered['html'])
button = next(attrs for tag, attrs in buttons.tags if tag == 'button' and 'data-value' in attrs)
check('copy handler is constant code and provider text remains data',
      button['onclick'] == 'cp(this.dataset.value,this)' and button['data-value'] == detail and 'data-extra' not in button)
check('malicious provider script never executed in isolated JS', rendered['injected'] is None)
check('stored receipt cannot retain dead payment instructions',
      'data-value=' not in rendered['storedDead'] and 'не переводите повторно' in rendered['storedDead'])
check('sent receipt retains no-repeat guidance while unavailable',
      'data-value=' not in rendered['sentDead'] and 'Повторно не переводите' in rendered['sentDead'])

# Sensitivity control reverts only the script-JSON escaping to the prior sink.
# This is an in-memory mutant, never a product or runtime edit.
unsafe_source = SOURCE.replace("cfg_json = (_json.dumps(cfg, ensure_ascii=False)\n                    .replace('&', '\\\\u0026').replace('<', '\\\\u003c').replace('>', '\\\\u003e')\n                    .replace('\\u2028', '\\\\u2028').replace('\\u2029', '\\\\u2029'))",
                               'cfg_json = _json.dumps(cfg, ensure_ascii=False)')
check('unsafe sink sensitivity mutation applied', unsafe_source != SOURCE)
compile_handlers(unsafe_source)
unsafe_page = call('pay', 'synthetic-page')
unsafe_tags = Tags(); unsafe_tags.feed(unsafe_page)
check('unsafe sink mutant reproduces script breakout', sum(tag == 'script' for tag, _ in unsafe_tags.tags) == 2)
compile_handlers(SOURCE)
fake.get_by_token = lambda value: {'order_id': 101, 'amount': object(), 'provider_payload': '{}'}
denied('pay', 'synthetic-bearer-must-never-be-logged', request(), 500, 'unexpected page failure remains generic')
check('unexpected page log contains neither bearer nor exception contents',
      all('synthetic-bearer' not in repr(entry) and 'synthetic read failure' not in repr(entry) for entry in logs))
namespace['_payment_status_reads'] = saved_reader

baseline = subprocess.run(['git', 'show', '49fe2eaec2187f934624f788bde11c3fb73b3904:relay-fastapi/main.py'],
                          cwd=ROOT, text=True, capture_output=True, check=True).stdout
def defs(source):
    return {n.name: ast.dump(n, include_attributes=False) for n in ast.parse(source).body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
old, new = defs(baseline), defs(SOURCE)
changed = sorted(name for name in old.keys() | new.keys() if old.get(name) != new.get(name))
check('only four scoped handlers/helpers changed', changed == ['_receipt_state', '_session_dead', 'api_order', 'pay'])
api_node = next(n for n in ast.parse(SOURCE).body if isinstance(n, ast.AsyncFunctionDef) and n.name == 'api_order')
check('API contains no provider/network/money transition calls',
      all(term not in ast.unparse(api_node) for term in ['_mark_order_paid', 'get_status', 'PaymentService', 'Brabus', 'Vertu']))
check('all synthetic DB operations were bounded SELECTs', all(q.startswith('SELECT ') and q.endswith('LIMIT 1') for q in queries))
check('synthetic ledger unchanged throughout probes', db.total_changes == before_changes)
db.close()
paths = [Path(__file__), MAIN, ROOT/'relay/repositories/payment_status_read_store.py',
         ROOT/'relay/core/order_access.py', ROOT/'relay/core/requisites.py', ROOT/'relay/core/txid.py',
         ROOT/'relay/repositories/order_read_store.py', ROOT/'relay/core/db_runtime.py']
print(json.dumps({'schemaVersion': 'e4-payment-status-security-probe.v1', 'result': 'PASS',
    'inputs': [{'path': str(p.relative_to(ROOT)), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for p in paths],
    'checksPassed': len(cases), 'cases': cases, 'boundedSelectCount': len(queries),
    'mainFunctionsChanged': changed, 'unsafeScriptSinkMutantRejected': True,
    'scope': 'Actual pure adapter, SQLite memory query_only; AST-isolated real handlers; synthetic key; Node VM for actual page script; capture-only PG placeholders.',
    'productionDatabaseRequestsWritesRestarts': False,
    'limitations': ['No real Telegram signature, provider, payout or browser-engine acceptance inferred.',
                   'PG capture checks SQL binding only; actual engine is covered by separate isolated PostgreSQL evidence.']}, indent=2))
