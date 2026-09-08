"""Execute only the pure api_history serialization with synthetic repository rows."""
import ast
import asyncio
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

root = Path('/root')
out = root/'output/playwright/e4-activity-deadline-20260908/acceptance'
backend = root/'relay-fastapi/main.py'
tree = ast.parse(backend.read_text())
function = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == 'api_history')
function.decorator_list = []
module = ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[]))
spec = importlib.util.spec_from_file_location('acceptance_txid', root/'relay/core/txid.py')
txid = importlib.util.module_from_spec(spec)
spec.loader.exec_module(txid)
row = {}
class FakeReads:
    def customer_orders(self, user_id, limit):
        assert user_id == 42 and limit == 30
        return [row.copy()]
    def receipt_order_ids(self, order_ids):
        return set(order_ids)
ctx = {'Request': object, 'verify_init_data': lambda _: {'id':42}, '_order_reads':FakeReads(),
       '_delayed_ids':lambda:set(), '_txid':txid}
exec(compile(module,str(backend),'exec'),ctx)
results=[]
for state, receipt in [('pending','sent'),('sent','sent'),('sent','stored'),('cancelled','stored')]:
    row.clear()
    row.update(order_id=42, rub_amount=2000, currency='TON', status=state,created_at='2026-09-08 00:00',
               session_token='synthetic_urlsafe_session', paid_btc_tx='a'*64 if state=='sent' else '',
               receipt_sent_at='2026-09-08 00:01' if receipt=='sent' else '',network='TON')
    response=asyncio.run(ctx['api_history'](SimpleNamespace(headers={'X-Telegram-Init-Data':'synthetic-only'})))
    assert response[0]['receipt']==receipt
    results.append({'case':state+'-receipt-'+receipt,'apiResponse':response})
report={'method':'AST-extracted api_history function only; fake verified identity/repository rows/receipt IDs/delays; pure core.txid module computes actual canonical explorer URLs. No app import, database, account or real API access.',
        'backendFunctionLines':[function.lineno,function.end_lineno],
        'inputs':[{'path':str(p.relative_to(root)), 'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in [backend,root/'relay/core/txid.py',root/'relay/utils/tokens.py']],
        'results':results}
(out/'next-prerequisite-backend.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({'result':'VALID_BACKEND_SHAPES_REPRODUCED','cases':[r['case'] for r in results]}))
