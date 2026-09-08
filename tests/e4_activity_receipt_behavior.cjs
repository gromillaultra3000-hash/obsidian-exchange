'use strict';
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const source = fs.readFileSync(process.argv[2], 'utf8');
const orders = JSON.parse(fs.readFileSync(0, 'utf8')), order = orders[0];
const elements = new Map(['history-list', 'history-summary', 'history-load-status']
    .map(id => [id, {innerHTML: '', textContent: '', style: {}, setAttribute() {}, querySelectorAll: () => []}]));
const ctx = vm.createContext({document: {getElementById: id => elements.get(id), querySelectorAll: () => []},
    location: {origin: 'https://receipt.invalid'}, fixture: orders});
const start = source.indexOf('        let historyOrders =');
const end = source.indexOf('        (function wireHistoryControls()', start);
const escapeStart = source.indexOf('        function esc(s) {');
const escapeEnd = source.indexOf('        async function loadWalletBook()', escapeStart);
assert.ok([start, end, escapeStart, escapeEnd].every(n => n >= 0));
vm.runInContext(source.slice(escapeStart, escapeEnd) + source.slice(start, end), ctx);
vm.runInContext("historyOrders=fixture;historyLoadState='ready';renderHistoryOrders();", ctx);
const markup = elements.get('history-list').innerHTML;
const evidence = [...markup.matchAll(/<div class="history-evidence[^"]*"[^>]*>(.*?)<\/div>/g)]
    .map(match => match[1]).join(' ');
const transactionAvailable = order.status === 'sent' && !!order.tx_url;
assert.equal(markup.includes('🔍 Транзакция'), transactionAvailable, 'transaction action follows actual status/link');
assert.equal(/транзакци/i.test(evidence), transactionAvailable, 'receipt must not suppress available transaction explanation');
if (transactionAvailable) assert.match(evidence, /Подтверждения проверьте в обозревателе сети/);
if (order.receipt) {
    assert.match(evidence, /Чек|чека/, 'retained receipt remains visible');
    if (order.status === 'pending') {
        assert.match(evidence, /Не оплачивайте повторно/);
        if (order.receipt === 'sent') assert.match(evidence, /Чек передан на проверку/);
        else assert.match(evidence, /Статус проверки пока не подтверждён/);
    } else {
        assert.doesNotMatch(evidence, /Его статус появится|Не оплачивайте повторно|Статус проверки пока/,
            'historical receipts cannot promise future review or reuse active-review instructions');
        assert.match(evidence, order.receipt === 'sent' ? /Чек был передан на проверку/ : /Файл чека сохранён в истории заявки/);
    }
} else assert.doesNotMatch(evidence, /Чек|чека/, 'absent metadata cannot become a receipt claim');
assert.doesNotMatch(evidence, /Оплата подтверждена|Чек проверен|Средства доставлены|Возврат выполнен/);
assert.equal(markup.includes('💳 Оплатить'), order.status === 'pending' && !order.receipt);
assert.equal(markup.includes('🧾 Открыть заявку'), order.status === 'pending' && !!order.receipt);
assert.ok(markup.includes('history-support-order') && markup.includes('history-copy-id'));
if (['expired', 'failed', 'cancelled'].includes(order.status)) assert.match(markup, /не переводите|Не переводите/);
const before = markup;
ctx.setHistoryFilter('sent');
if (order.status !== 'sent') assert.ok(!elements.get('history-list').innerHTML.includes('history-evidence'));
ctx.setHistoryFilter('all');
assert.equal(elements.get('history-list').innerHTML, before, 'filter restoration retains evidence and actions');
console.log(JSON.stringify({result: 'PASS', status: order.status, receipt: order.receipt, transactionAvailable}));
