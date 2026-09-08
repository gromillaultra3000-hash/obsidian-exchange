#!/usr/bin/env python3
"""Independent synthetic API/renderer security checks; no application import or I/O."""
import ast
import asyncio
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import types

ROOT = Path('/root')
SOURCE = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT / 'relay/webapp.html'
API = ROOT / 'relay-fastapi/main.py'
TXID = ROOT / 'relay/core/txid.py'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Denied(Exception):
    def __init__(self, **kwargs):
        self.status_code = kwargs['status_code']


class Rows:
    def __init__(self):
        self.rows = []
        self.receipts = set()
        self.raise_receipts = False
        self.reads = 0

    def customer_orders(self, uid, limit):
        assert uid == 991 and limit == 30
        self.reads += 1
        return self.rows

    def receipt_order_ids(self, ids):
        assert set(ids) == {r['order_id'] for r in self.rows}
        if self.raise_receipts:
            raise RuntimeError('synthetic absent receipt store')
        return self.receipts


async def main():
    tx = types.ModuleType('synthetic_txid')
    exec(compile(TXID.read_text(), str(TXID), 'exec'), tx.__dict__)
    node = next(n for n in ast.parse(API.read_text()).body
                if isinstance(n, ast.AsyncFunctionDef) and n.name == 'api_history')
    node.decorator_list = []
    store = Rows()
    env = {'Request': object, 'verify_init_data': lambda value: {'id': 991} if value == 'synthetic' else None,
           'HTTPException': Denied, '_order_reads': store, '_txid': tx,
           '_delayed_ids': lambda: set(), 'logger': types.SimpleNamespace(warning=lambda *args: None)}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(API), 'exec'), env)
    try:
        await env['api_history'](types.SimpleNamespace(headers={}))
        raise AssertionError('missing authentication accepted')
    except Denied as denied:
        assert denied.status_code == 403 and store.reads == 0
    request = types.SimpleNamespace(headers={'X-Telegram-Init-Data': 'synthetic'})
    cases = []
    statuses = ['pending', 'paid', 'sent', 'expired', 'failed', 'cancelled', 'unknown']
    currencies = ['BTC', 'LTC', 'USDT', 'TRX', 'ETH', 'XRP', 'TON', 'XMR']
    for status in statuses:
        for receipt in ['', 'stored', 'sent']:
            for currency in currencies:
                for rawtx in ['a' * 64, 'manual', "https://evil.invalid/\"');globalThis.pwned=true;//"]:
                    row = {'order_id': 'synthetic-order', 'rub_amount': 123,
                           'currency': currency, 'status': status, 'created_at': '2026-01-01',
                           'session_token': 'synthetic_token_123', 'paid_btc_tx': rawtx,
                           'receipt_sent_at': '2026-01-01' if receipt == 'sent' else '', 'network': ''}
                    store.rows, store.receipts = [row], {'synthetic-order'} if receipt else set()
                    result = (await env['api_history'](request))[0]
                    assert result['receipt'] == receipt
                    if rawtx != 'a' * 64:
                        assert result['tx_url'] == ''
                    else:
                        assert result['tx_url'].startswith('https://')
                        assert not any(c in result['tx_url'] for c in "'\"<>\\")
                    cases.append(result)
    store.raise_receipts = True
    assert (await env['api_history'](request))[0]['receipt'] == ''
    javascript = r'''
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const html = fs.readFileSync(input.source, 'utf8');
function extract(start, end) { const a = html.indexOf(start); const b = html.indexOf(end, a); assert(a >= 0 && b > a); return html.slice(a,b); }
const list = { innerHTML:'', setAttribute(){}, querySelectorAll(){return [];} };
const context = vm.createContext({
  document: { getElementById(id){return id === 'history-list' ? list : null;} },
  location: {origin: 'https://example.invalid'},
  historyLoadState:'ready', historyFilter:'all', historyOrders:[],
  renderHistorySummary(){},
});
vm.runInContext(extract('function esc(s)', 'async function loadWalletBook(') + '\n' + extract('function historyStatus(o)', 'function renderHistorySummary(') + '\n' + extract('function renderHistoryOrders()', 'function setHistoryFilter('), context);
let checks = 0;
for (const order of input.cases) {
  context.historyOrders = [order]; context.renderHistoryOrders();
  const out = list.innerHTML;
  const transactionExplanation = out.includes('Подтверждения проверьте в обозревателе сети.');
  assert.equal(transactionExplanation, order.status === 'sent' && !!order.tx_url); checks++;
  assert.equal(out.includes('🔍 Транзакция</a>'), order.status === 'sent' && !!order.tx_url); checks++;
  assert.equal(out.includes('/pay/'), order.status === 'pending'); checks++;
  assert(!out.includes('Его статус появится здесь.')); checks++;
  assert(!out.includes('Доказательство выдачи')); checks++;
  if (order.receipt && order.status !== 'pending') {
    assert(!out.includes('Не оплачивайте повторно.'));
    assert(out.includes(order.receipt === 'sent' ? 'Чек был передан на проверку.' : 'Файл чека сохранён в истории заявки.')); checks += 2;
  }
  if (order.receipt && order.status === 'pending') {
    assert(!out.includes('💳 Оплатить')); checks++;
  }
  assert(!out.includes('evil.invalid')); checks++;
}
const payload = '<img src=x onerror=globalThis.pwned=true>';
context.historyOrders = [{order_id:payload,amount:payload,currency:payload,status:payload,created:payload,receipt:payload}];
context.renderHistoryOrders();
assert(!list.innerHTML.includes(payload)); checks++;
assert(!list.innerHTML.includes('globalThis.pwned=true>')); checks++;
assert.equal(context.pwned, undefined); checks++;
console.log(JSON.stringify({checks, cases:input.cases.length, escapedLiteralMetadata:true}));
'''
    result = subprocess.run(['node', '-e', javascript], input=json.dumps({'source': str(SOURCE), 'cases': cases}),
                            text=True, capture_output=True, timeout=20)
    assert result.returncode == 0, result.stderr
    print(json.dumps({'schemaVersion': 'e4-activity-receipt-security-probe.v1',
                      'result': 'PASS', 'inputs': {str(p.relative_to(ROOT)): digest(p) for p in [SOURCE, API, TXID]},
                      'renderer': json.loads(result.stdout), 'unauthenticatedReadRejected': True,
                      'receiptMetadataFailureDoesNotInventEvidence': True,
                      'productionImportsReadsWritesNetwork': False}, indent=2))


if __name__ == '__main__':
    asyncio.run(main())
