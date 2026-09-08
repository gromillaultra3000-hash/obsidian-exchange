"""Independent exact-code legacy/candidate comparison on in-memory fixtures."""
import ast
import asyncio
from datetime import date, datetime
from decimal import Decimal
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import subprocess
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
REVISION = '72cb3aa'
paths = ['relay-fastapi/main.py', 'relay/repositories/order_read_store.py',
         'relay/repositories/activity_read_store.py', 'relay/webapp.html', 'relay/core/txid.py']
old = {path: subprocess.check_output(['git', 'show', REVISION + ':' + path], cwd=ROOT, text=True)
       for path in paths if path != 'relay/repositories/activity_read_store.py'}
new = {path: (ROOT / path).read_text() for path in paths}


def isolate(source, names, context, class_name=None, include_constants=False):
    tree = ast.parse(source)
    body = tree.body if class_name is None else next(
        node.body for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name)
    nodes = [node for node in body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names]
    assert {node.name for node in nodes} == set(names)
    if include_constants:
        nodes = [node for node in body if isinstance(node, ast.Assign)] + nodes
    for node in nodes:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            node.decorator_list = []
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), '<exact-acceptance>', 'exec'), context)
    return context


db = sqlite3.connect(':memory:')
db.row_factory = sqlite3.Row
db.executescript('''
CREATE TABLE orders(order_id INTEGER,user_id INTEGER,rub_amount REAL,crypto_address TEXT,
 currency TEXT,status TEXT,created_at TEXT,paid_btc_tx TEXT,network TEXT,receipt_sent_at TEXT);
CREATE TABLE payment_sessions(id INTEGER,order_id INTEGER,session_token TEXT,status TEXT,created_at TEXT);
CREATE TABLE order_receipts(order_id INTEGER);
''')
sql = []
db.set_trace_callback(lambda statement: sql.append(statement) if statement.lstrip().upper().startswith('SELECT') else None)
helpers = isolate(new['relay/repositories/order_read_store.py'], ['_value', '_dict'],
                  {'Decimal': Decimal, 'datetime': datetime, 'date': date})
legacy = isolate(old['relay/repositories/order_read_store.py'], ['customer_orders', 'receipt_order_ids'],
                 helpers, 'SQLiteOrderReadStore')


class SQLiteOrderReadStore:
    def _c(self):
        return db

    def customer_orders(self, *args, **kwargs):
        return legacy['customer_orders'](self, *args, **kwargs)

    def receipt_order_ids(self, *args, **kwargs):
        return legacy['receipt_order_ids'](self, *args, **kwargs)


class PostgresOrderReadStore:
    pass


activity = isolate(new['relay/repositories/activity_read_store.py'], ['customer_orders'],
    {'SQLiteOrderReadStore': SQLiteOrderReadStore, 'PostgresOrderReadStore': PostgresOrderReadStore,
     '_dict': helpers['_dict']}, include_constants=True)
store = SQLiteOrderReadStore()
spec = importlib.util.spec_from_file_location('acceptance_txid', ROOT / 'relay/core/txid.py')
txid = importlib.util.module_from_spec(spec)
spec.loader.exec_module(txid)
contexts = []
for sources in [old, new]:
    contexts.append(isolate(sources['relay-fastapi/main.py'], ['api_history'], {
        'Request': object, 'verify_init_data': lambda _: {'id': 42}, '_order_reads': store,
        '_delayed_ids': lambda: set(), '_txid': txid,
        '_activity_read_store_module': SimpleNamespace(customer_orders=activity['customer_orders']),
    }))
cases = [
    ('failed', 'pending', '', [(1, 'failed', '2026-09-08 00:01')]),
    ('expired', 'pending', '', [(1, 'expired', '2026-09-08 00:01')]),
    ('old-active-latest-failed', 'pending', '', [(1, 'invoice_created', '2026-09-08 00:00'), (2, 'failed', '2026-09-08 00:01')]),
    ('latest-id-dominates-time', 'pending', '', [(1, 'invoice_created', '2026-09-08 00:09'), (2, 'failed', '2026-09-08 00:01')]),
    ('latest-active-recovers', 'pending', '', [(1, 'failed', '2026-09-08 00:00'), (2, 'invoice_created', '2026-09-08 00:01')]),
    ('unknown-status', 'pending', '', [(1, 'future_unrecognized_state', '2026-09-08 00:01')]),
    ('no-session', 'pending', '', []),
    ('closed-stored-receipt', 'pending', 'stored', [(1, 'failed', '2026-09-08 00:01')]),
    ('closed-sent-receipt', 'pending', 'sent', [(1, 'failed', '2026-09-08 00:01')]),
    ('paid-order-precedence', 'paid', 'stored', [(1, 'failed', '2026-09-08 00:01')]),
    ('sent-order-precedence', 'sent', 'sent', [(1, 'failed', '2026-09-08 00:01')]),
    ('cancelled-order-precedence', 'cancelled', 'stored', [(1, 'failed', '2026-09-08 00:01')]),
]
results = []
for case, status, receipt, sessions in cases:
    db.execute('DELETE FROM order_receipts')
    db.execute('DELETE FROM payment_sessions')
    db.execute('DELETE FROM orders')
    db.execute('INSERT INTO orders VALUES(42,42,2000,?,?,?,? ,?,?,?)', ('synthetic-address', 'TON', status,
        '2026-09-08 00:00', 'a' * 64 if status == 'sent' else '', 'TON', '2026-09-08 00:01' if receipt == 'sent' else ''))
    db.execute("INSERT INTO orders VALUES(43,43,9000,'synthetic-foreign','TON','pending','2026-09-08 00:00','','TON','')")
    db.execute("INSERT INTO payment_sessions VALUES(99,43,'synthetic_foreign','failed','2026-09-08 00:09')")
    for identifier, state, created in sessions:
        db.execute('INSERT INTO payment_sessions VALUES(?,?,?,?,?)', (identifier, 42, 'synthetic_' + str(identifier), state, created))
    if receipt:
        db.execute('INSERT INTO order_receipts VALUES(42)')
    legacy_before = store.customer_orders(42, limit=30)
    sql.clear()
    snapshot = activity['customer_orders'](store, 42, limit=30)
    assert len(sql) == 1 and len(snapshot) == 1 and snapshot[0]['order_id'] == 42
    assert activity['customer_orders'](store, 999, limit=30) == []
    assert store.customer_orders(42, limit=30) == legacy_before
    before, after = [asyncio.run(ctx['api_history'](SimpleNamespace(headers={}))) for ctx in contexts]
    assert len(before) == len(after) == 1
    expected_state = sessions[-1][1] if sessions else 'unknown'
    if expected_state == 'future_unrecognized_state':
        expected_state = 'unknown'
    assert after[0]['payment_session_state'] == expected_state
    if expected_state in {'failed', 'expired', 'unknown'}:
        assert after[0]['session_token'] is None
    else:
        assert after[0]['session_token'] == 'synthetic_' + str(sessions[-1][0])
    for field in ['order_id', 'amount', 'currency', 'status', 'created', 'txid', 'receipt', 'delayed', 'tx_url']:
        assert before[0][field] == after[0][field]
    results.append({'case': case, 'before': before, 'after': after,
        'snapshotSelectCount': 1, 'foreignOwnerExcluded': True, 'legacyBotSnapshotUnchanged': True})
db.close()
js = r'''
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const {sources,cases}=JSON.parse(fs.readFileSync(0,'utf8'));
for(const item of cases)for(const kind of ['before','after']){
 const source=sources[kind],nodes=new Map(['history-list','history-summary','history-load-status'].map(id=>[id,{innerHTML:'',textContent:'',style:{},setAttribute(){},querySelectorAll(){return[];}}]));
 const ctx=vm.createContext({document:{getElementById:id=>nodes.get(id)},location:{origin:'https://acceptance.invalid'},fixture:item[kind]});
 const a=source.indexOf('        let historyOrders ='),b=source.indexOf('        (function wireHistoryControls()',a),c=source.indexOf('        function esc(s) {'),d=source.indexOf('        async function loadWalletBook()',c);
 assert.ok([a,b,c,d].every(n=>n>=0));vm.runInContext(source.slice(c,d)+source.slice(a,b),ctx);vm.runInContext("historyOrders=fixture;historyLoadState='ready';renderHistoryOrders();",ctx);
 const html=nodes.get('history-list').innerHTML;
 item[kind+'Rendered']={label:html.match(/<span class="status">(.*?)<\/span>/)[1],closureAdvice:html.includes('class="history-session-advice"'),paymentAction:html.includes('💳 Оплатить')||html.includes('🧾 Открыть заявку'),transactionAction:html.includes('🔍 Транзакция'),support:html.includes('history-support-order')};
 if(kind==='after'){
  const order=item.after[0],closed=order.status==='pending'&&['failed','expired'].includes(order.payment_session_state);
  assert.equal(item.afterRendered.closureAdvice,closed);if(closed)assert.equal(item.afterRendered.paymentAction,false);
  if(closed)assert.equal(item.afterRendered.label,order.receipt==='sent'?'Чек на проверке':order.receipt==='stored'?'Чек получен':'Сессия оплаты закрыта');
  if(!closed)assert.equal(item.afterRendered.label,item.beforeRendered.label);
  assert.equal(item.afterRendered.transactionAction,item.beforeRendered.transactionAction);assert.equal(item.afterRendered.support,true);
 }
}
assert.equal(cases.find(x=>x.case==='old-active-latest-failed').beforeRendered.paymentAction,true);
assert.equal(cases.find(x=>x.case==='old-active-latest-failed').afterRendered.paymentAction,false);
console.log(JSON.stringify(cases));
'''
rendered = json.loads(subprocess.check_output(['node', '-e', js], text=True,
    input=json.dumps({'sources': {'before': old['relay/webapp.html'], 'after': new['relay/webapp.html']}, 'cases': results})))
report = {
    'schemaVersion': 'e4-activity-session-independent-acceptance-probe.v1',
    'result': 'BASELINE_REPRODUCED_AND_CANDIDATE_VERIFIED',
    'reviewer': 'Codex independent acceptance /root/receipt_acceptance',
    'method': 'AST-extracted exact legacy and candidate repository/API functions over sqlite3 :memory: fixtures, then exact old/candidate history rendering in Node VM. Marker-specific store types are inert local sentinels; actual SQL and normalization execute. No application import, real account, production database, provider or network action.',
    'baselineRevision': REVISION,
    'beforeSha256': {p: hashlib.sha256(s.encode()).hexdigest() for p, s in old.items()},
    'afterSha256': {p: hashlib.sha256(s.encode()).hexdigest() for p, s in new.items()},
    'cases': rendered,
    'verified': ['One SELECT binds latest session status/token by id chronology and excludes other owners.',
        'Failed/expired/unknown state never revives a token from an older row.',
        'The existing legacy customer_orders function and its named-field bot snapshots remain unchanged.',
        'Order and receipt semantics are unchanged while closure advice and action suppression agree with latest session metadata.',
        'Known active latest state recovers normally; unknown and missing state never become a closure claim.'],
    'limitations': ['This independent probe executes SQLite SQL and exact normalization; PostgreSQL execution and runtime dependencies are separately checked by primary/operations evidence.',
        'It is not browser-layout, human-comprehension or production customer-data evidence.'],
}
(OUT / 'acceptance-probe.json').write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')
print(json.dumps({'result': report['result'], 'cases': len(rendered), 'sqlSnapshotPerCase': 1}))
