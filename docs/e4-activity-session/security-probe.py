#!/usr/bin/env python3
"""Independent exact-source ownership/snapshot probes with in-memory rows only."""
import ast
import asyncio
import hashlib
import importlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
from types import SimpleNamespace

ROOT = Path('/root')
sys.path.insert(0, str(ROOT / 'relay'))
activity = importlib.import_module('repositories.activity_read_store')
orders = importlib.import_module('repositories.order_read_store')
txid = importlib.import_module('core.txid')

db = sqlite3.connect(':memory:')
db.row_factory = sqlite3.Row
db.executescript('''
CREATE TABLE orders(order_id INTEGER PRIMARY KEY,user_id INTEGER,rub_amount REAL,
crypto_address TEXT,currency TEXT,status TEXT,created_at TEXT,paid_btc_tx TEXT,
network TEXT,receipt_sent_at TEXT);
CREATE TABLE payment_sessions(id INTEGER PRIMARY KEY,order_id INTEGER,session_token TEXT,
status TEXT,created_at TEXT);
CREATE TABLE order_receipts(order_id INTEGER);
''')
raw_states = [None, 'failed', 'invoice_created', 'expired', 'unrecognized',
              '<svg onload=globalThis.pwned=true>', 'created', 'awaiting_payment',
              'payment_detected', 'confirming', 'payout_queued', 'payout_sent', 'completed']
expected_known = {'created', 'invoice_created', 'awaiting_payment', 'payment_detected',
                  'confirming', 'payout_queued', 'payout_sent', 'completed', 'failed', 'expired'}
for oid, raw in enumerate(raw_states, 1):
    db.execute('INSERT INTO orders VALUES(?,?,?,?,?,?,?,?,?,?)',
               (oid, 111, 1, 'synthetic', 'TON', 'pending', '2026-01-01', '', 'TON', ''))
    db.execute('INSERT INTO payment_sessions VALUES(?,?,?,?,?)',
               (oid * 10, oid, 'synthetic-older', 'invoice_created', '2099-01-01'))
    db.execute('INSERT INTO payment_sessions VALUES(?,?,?,?,?)',
               (oid * 10 + 1, oid, 'synthetic-latest', raw, '2001-01-01'))
db.execute('INSERT INTO orders VALUES(90,111,1,"synthetic","TON","pending","2026-01-01","","TON","")')
db.execute('INSERT INTO orders VALUES(91,111,1,"synthetic","TON","pending","2026-01-01","","TON","")')
db.execute('INSERT INTO payment_sessions VALUES(910,91,NULL,"invoice_created","2026-01-01")')
db.execute('INSERT INTO orders VALUES(200,222,1,"foreign","TON","pending","2026-01-01","","TON","")')
db.execute('INSERT INTO payment_sessions VALUES(2000,200,"foreign-must-stay-private","failed","2026-01-01")')
db.execute('INSERT INTO payment_sessions VALUES(9999,999,"orphan-must-stay-private","failed","2026-01-01")')
db.commit()
db.execute('PRAGMA query_only=ON')
changed = db.total_changes
trace = []
db.set_trace_callback(trace.append)


class FixtureSQLite(orders.SQLiteOrderReadStore):
    def _c(self):
        return db

    def receipt_order_ids(self, ids):
        return set()


store = FixtureSQLite(':memory:')
result = activity.customer_orders(store, 111, limit=100)
assert len(result) == 15
assert len(trace) == 1 and trace[0].startswith('SELECT ')
assert db.total_changes == changed
by_id = {r['order_id']: r for r in result}
assert set(by_id) == set(range(1, 14)) | {90, 91}
for oid, raw in enumerate(raw_states, 1):
    row = by_id[oid]
    expected = raw if raw in expected_known else 'unknown'
    assert row['payment_session_state'] == expected
    assert row['session_token'] == (None if expected in {'failed', 'expired', 'unknown'} else 'synthetic-latest')
    assert row['session_token'] != 'synthetic-older'
assert by_id[90]['payment_session_state'] == 'unknown' and by_id[90]['session_token'] is None
assert by_id[91]['payment_session_state'] == 'invoice_created' and by_id[91]['session_token'] is None
assert activity.customer_orders(store, 222)[0]['order_id'] == 200
assert activity.customer_orders(store, 333) == []
assert len(activity.customer_orders(store, 111, limit=-1)) == 1
assert len(activity.customer_orders(store, 111, limit=100000)) == 15
for bad in [0, -1, '111 OR 1=1', None]:
    before = len(trace)
    try:
        activity.customer_orders(store, bad)
        raise AssertionError('invalid owner accepted')
    except (ValueError, TypeError):
        assert len(trace) == before
try:
    activity.customer_orders(object(), 111)
    raise AssertionError('unsupported store accepted')
except TypeError:
    pass

# Capture actual PG query and bound arguments without opening any PG connection.
captured = []
class PgConnection:
    def __enter__(self): return self
    def __exit__(self, *args): return None
    def execute(self, sql, args):
        captured.append((sql, args))
        return SimpleNamespace(fetchall=lambda: [])
class FixturePostgres(orders.PostgresOrderReadStore):
    def _c(self): return PgConnection()
activity.customer_orders(FixturePostgres('unused-no-connection'), 111, limit=30)
assert len(captured) == 1 and captured[0][1] == (111, 30)
assert captured[0][0].count('%s') == 2 and '?' not in captured[0][0]
assert 'WHERE o.user_id=%s' in captured[0][0]
assert 'ORDER BY latest.id DESC LIMIT 1' in captured[0][0]

api_source = ROOT / 'relay-fastapi/main.py'
function = next(n for n in ast.parse(api_source.read_text()).body
                if isinstance(n, ast.AsyncFunctionDef) and n.name == 'api_history')
function.decorator_list = []
class Denied(Exception):
    def __init__(self, **kwargs): self.status_code = kwargs['status_code']
env = {'Request': object, 'HTTPException': Denied,
       'verify_init_data': lambda data: {'id': 111} if data == 'synthetic-owner-111' else None,
       '_order_reads': store, '_activity_read_store_module': activity,
       '_delayed_ids': lambda: set(), '_txid': txid}
exec(compile(ast.Module(body=[function], type_ignores=[]), str(api_source), 'exec'), env)
async def api_checks():
    before = len(trace)
    try:
        await env['api_history'](SimpleNamespace(headers={}, query_params={'user_id': '111'}))
        raise AssertionError('unauthenticated API read accepted')
    except Denied as error:
        assert error.status_code == 403 and len(trace) == before
    response = await env['api_history'](SimpleNamespace(
        headers={'X-Telegram-Init-Data': 'synthetic-owner-111'},
        query_params={'user_id': '222', 'token': 'foreign-must-stay-private'}))
    assert {r['order_id'] for r in response} == set(by_id)
    assert 'foreign-must-stay-private' not in json.dumps(response)
    assert '<svg' not in json.dumps(response)
    return response
response = asyncio.run(api_checks())

javascript = r'''
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const input=JSON.parse(fs.readFileSync(0,'utf8')),html=fs.readFileSync(input.path,'utf8');
function part(a,b){const x=html.indexOf(a),y=html.indexOf(b,x);assert(x>=0&&y>x);return html.slice(x,y);}
const list={innerHTML:'',setAttribute(){},querySelectorAll(){return [];}};
const ctx=vm.createContext({document:{getElementById(id){return id==='history-list'?list:null;}},
location:{origin:'https://example.invalid'},historyLoadState:'ready',historyFilter:'all',historyOrders:[],renderHistorySummary(){}});
vm.runInContext(part('function esc(s)','async function loadWalletBook(')+part('function historyStatus(o)','function renderHistorySummary(')+part('function renderHistoryOrders()','function setHistoryFilter('),ctx);
let cases=0;
for(const row of input.rows)for(const status of ['pending','paid','sent','expired','failed','cancelled'])for(const receipt of ['','stored','sent']){
const o={...row,status,receipt,tx_url:status==='sent'?'https://tonviewer.com/transaction/'+'a'.repeat(64):''};
ctx.historyOrders=[o];ctx.renderHistoryOrders();const out=list.innerHTML;
const closed=status==='pending'&&['failed','expired'].includes(o.payment_session_state);
assert.equal(out.includes('history-session-advice'),closed);
assert.equal(out.includes('/pay/'),status==='pending'&&!closed&&!!o.session_token);
if(closed){assert(out.includes('Не переводите по прежним реквизитам.'));assert(out.includes('Если уже оплатили — не платите повторно'));}
if(status==='pending'&&receipt==='sent')assert.equal(ctx.historyStatus(o).label,'Чек на проверке');
assert.equal(out.includes('history-transaction-evidence'),status==='sent');
assert(!out.includes('foreign-must-stay-private')&&!out.includes('<svg'));
assert(!out.includes('Платёж не получен')&&!out.includes('Возврат выполнен'));cases++;
}
// Reject a stale token even if an inconsistent closed-session client row carries it.
for(const state of ['failed','expired']){
ctx.historyOrders=[{...input.rows[0],status:'pending',receipt:'',payment_session_state:state,session_token:'synthetic-stale'}];
ctx.renderHistoryOrders();assert(!list.innerHTML.includes('/pay/'));cases++;
}
console.log(JSON.stringify({result:'PASS',cases}));
'''
render = subprocess.run(['node', '-e', javascript], input=json.dumps({'path': str(ROOT / 'relay/webapp.html'), 'rows': response}),
                        text=True, capture_output=True, timeout=30)
assert render.returncode == 0, render.stderr
assert db.total_changes == changed
db.close()
paths = ['relay/repositories/activity_read_store.py', 'relay/repositories/order_read_store.py',
         'relay-fastapi/main.py', 'relay/webapp.html', 'relay/core/txid.py']
print(json.dumps({'schemaVersion':'e4-activity-session-security-probe.v1','result':'PASS',
    'inputs':[{'path':p,'sha256':hashlib.sha256((ROOT/p).read_bytes()).hexdigest()} for p in paths],
    'syntheticOwnedRows':15,'singleReadOnlySQLiteStatement':True,'latestSessionUsesIdNotTimestamp':True,
    'foreignAndOrphanSessionsExcluded':True,'invalidOwnersRejectedBeforeSQL':True,
    'unknownAndClosedStatesSuppressPaymentLink':True,'signedOwnerIgnoresForeignQueryAuthority':True,
    'postgresStatementAndParametersCapturedWithoutDatabaseConnection':True,
    'renderer':json.loads(render.stdout),'productionReadWriteNetwork':False},indent=2))
