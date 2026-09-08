'use strict';
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const source = fs.readFileSync(process.argv[2], 'utf8');
const orders = JSON.parse(fs.readFileSync(0, 'utf8')), order = orders[0];
const nodes = new Map(['history-list','history-summary','history-load-status']
    .map(id => [id, {innerHTML:'',textContent:'',style:{},setAttribute(){},querySelectorAll:()=>[]} ]));
const ctx = vm.createContext({fixture:orders, location:{origin:'https://session.invalid'},
    document:{getElementById:id=>nodes.get(id),querySelectorAll:()=>[]}});
const start=source.indexOf('        let historyOrders ='), end=source.indexOf('        (function wireHistoryControls()',start);
const es=source.indexOf('        function esc(s) {'), ee=source.indexOf('        async function loadWalletBook()',es);
assert.ok([start,end,es,ee].every(n=>n>=0));
vm.runInContext(source.slice(es,ee)+source.slice(start,end),ctx);
vm.runInContext("historyOrders=fixture;historyLoadState='ready';renderHistoryOrders();",ctx);
const html=nodes.get('history-list').innerHTML;
const closed=order.status==='pending' && ['failed','expired'].includes(order.payment_session_state);
assert.equal(html.includes('history-session-advice'),closed);
if(closed){
    assert.match(html,/Не переводите по прежним реквизитам/);
    assert.match(html,/Если уже оплатили — не платите повторно и обратитесь в поддержку/);
    const label=order.receipt==='sent'?'Чек на проверке':order.receipt?'Чек получен':'Сессия оплаты закрыта';
    assert.ok(html.includes('class="status">'+label+'</span>'));
    assert.ok(!html.includes('class="btn-pay"'),'closed session must suppress even a legacy action token');
    assert.doesNotMatch(html,/Заявка закрыта|Заявка отменена|Оплата не прошла|Возврат выполнен/);
}
assert.equal(html.includes('history-receipt-evidence'),!!order.receipt);
assert.equal(html.includes('history-transaction-evidence'),order.status==='sent'&&!!order.tx_url);
assert.equal(html.includes('💳 Оплатить'),order.status==='pending'&&!closed&&!order.receipt&&!!order.session_token);
assert.ok(html.includes('history-support-order'));
ctx.setHistoryFilter('sent');ctx.setHistoryFilter('all');assert.equal(nodes.get('history-list').innerHTML,html);
console.log(JSON.stringify({result:'PASS',closed}));
