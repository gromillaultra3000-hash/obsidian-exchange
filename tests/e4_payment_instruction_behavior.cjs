'use strict';
// Replay the shipped tracking functions with synthetic DOM, timers and GETs.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const [sourcePath, scenario] = process.argv.slice(2);
const source = fs.readFileSync(sourcePath, 'utf8');
const elements = new Map();
const ids = ['pay-card', 'pay-card-title', 'pay-card-status', 'pay-timer',
    'pay-open-btn', 'pay-check-btn', 'exchange-steps', 'pay-qr-wrap',
    'pay-qr', 'pay-amount-line', 'pay-req', 'pay-req-value', 'pay-req-copy', 'pay-req-copy-status'];
for (const id of ids) {
    let contents = '';
    elements.set(id, {style: {}, disabled: false,
        addEventListener() {},
        get textContent() {return contents;}, set textContent(v) {contents = v;},
        get innerHTML() {return contents;}, set innerHTML(v) {contents = v;},
        removeAttribute(name) {delete this[name];}});
}
const el = id => elements.get(id);
const requests = [], links = [], haptics = [], timers = new Map();
const deadlines = new Map();
let nextTimer = 0, historyLoads = 0;
const ctx = vm.createContext({document: {getElementById: el},
    tg: {initData: '', openLink: url => links.push(url),
        HapticFeedback: {notificationOccurred: type => haptics.push(type)}},
    window: {location: {}}, loadHistory: () => historyLoads++, AbortController,
    setTimeout: (fn, delay) => {deadlines.set(++nextTimer, {fn, delay}); return nextTimer;},
    clearTimeout: id => deadlines.delete(id),
    setInterval: (fn, delay) => {timers.set(++nextTimer, {fn, delay}); return nextTimer;},
    clearInterval: id => timers.delete(id),
    fetch: (url, options) => new Promise((resolve, reject) => {
        requests.push({url, options, resolve, reject});
        options.signal?.addEventListener('abort', () => reject(new Error('synthetic timeout')), {once: true});
    }),
});
const begin = source.indexOf('        let _orderPoll =');
const end = source.indexOf('        let historyOrders =', begin);
assert.ok(begin > 0 && end > begin);
vm.runInContext(source.slice(begin, end), ctx);
const flush = async () => {for (let n = 0; n < 6; n++) await Promise.resolve();};
const reply = async (index, body) => {
    requests[index].resolve({ok: true, json: async () => body}); await flush();
};
const qr = 'data:image/png;base64,c3ludGhldGljLXFy';
function start(id = 'new', image = null, amount = 2000, requisites = {phone: '+70000000002'}) {
    ctx.startOrderTracking(id, 'https://payment.invalid/' + id, 'TON', image, amount, requisites);
}
function fresh() {
    assert.equal(el('pay-card-title').textContent, 'Заявка #new');
    assert.equal(el('pay-timer').textContent, '15:00');
    assert.equal(el('pay-timer').style.color, '#c48cff');
    assert.equal(el('pay-open-btn').style.display, '');
    assert.equal(el('pay-open-btn').disabled, false);
    assert.equal(el('pay-open-btn').textContent, '💳 Оплатить');
    assert.equal(el('pay-check-btn').textContent, '🔄 Проверить статус');
    assert.equal(el('exchange-steps').style.display, 'flex');
    assert.match(el('exchange-steps').innerHTML, /Ожидание оплаты/);
    assert.equal(el('pay-qr-wrap').style.display, 'none');
    assert.equal(el('pay-qr').src, undefined);
    assert.equal(el('pay-amount-line').textContent, '');
    assert.match(el('pay-req').innerHTML, /2\s000/);
    assert.ok(!el('pay-req').innerHTML.includes('+70000000001'));
}
async function main() {
    start('old', qr, 1000, {phone: '+70000000001', bank_name: 'Synthetic bank A'});
    const oldOpen = el('pay-open-btn').onclick;
    const oldCheck = el('pay-check-btn').onclick;
    const oldTimer = [...timers.values()].find(t => t.delay === 1000).fn;
    if (scenario === 'qr_to_text') {start(); fresh();}
    else if (scenario === 'qr_without_amount') {
        start('new', qr, null, null);
        assert.equal(el('pay-amount-line').textContent, '');
        assert.equal(el('pay-qr-wrap').style.display, 'block');
    } else if (scenario === 'text_to_empty') {
        ctx.startOrderTracking('new', null, 'TON', null, null, null);
        assert.equal(el('pay-req').innerHTML, '');
        assert.equal(el('pay-req').style.display, 'none');
        assert.equal(el('pay-open-btn').disabled, true);
        assert.equal(el('pay-open-btn').style.display, 'none');
        el('pay-open-btn').onclick();
        assert.deepEqual(links, []);
    } else if (scenario === 'link_to_qr') {
        start('link', null, 2000, {payment_link: 'https://payment.invalid/link'});
        assert.match(el('pay-open-btn').textContent, /страницу/);
        start('new', qr, 3000, null);
        assert.equal(el('pay-req').innerHTML, '');
        assert.match(el('pay-open-btn').textContent, /банка/);
        el('pay-open-btn').onclick();
        assert.deepEqual(links, ['https://payment.invalid/new']);
    } else if (scenario.endsWith('_to_new')) {
        const status = scenario.split('_')[0];
        if (status === 'timer') {for (let i = 0; i < 900; i++) oldTimer();}
        else await reply(0, {status: ['receipt', 'dead'].includes(status) ? 'pending' : status,
            receipt: status === 'receipt' ? 'sent' : '', dead: status === 'dead'});
        assert.equal(el('pay-open-btn').style.display, 'none');
        start(); fresh();
        oldTimer(); fresh();
        el('pay-open-btn').onclick();
        assert.deepEqual(links, ['https://payment.invalid/new']);
    } else if (scenario === 'late_status' || scenario === 'late_json' || scenario === 'same_id_reopen') {
        let resolveJson;
        if (scenario === 'late_json') {
            requests[0].resolve({ok: true, json: () => new Promise(resolve => {resolveJson = resolve;})});
            await flush();
        }
        start(scenario === 'same_id_reopen' ? 'old' : 'new');
        const snapshot = ids.map(id => [el(id).textContent, {...el(id).style}, el(id).src]);
        const status = {status: 'sent', tx_url: 'https://explorer.invalid/old'};
        if (resolveJson) {resolveJson(status); await flush();} else await reply(0, status);
        assert.deepEqual(ids.map(id => [el(id).textContent, {...el(id).style}, el(id).src]), snapshot);
        assert.equal(historyLoads, 0); assert.deepEqual(haptics, []);
        assert.equal(timers.size, 2, 'old terminal response must not stop new timers');
    } else if (scenario === 'old_actions') {
        start(); oldOpen(); await oldCheck(); oldTimer();
        assert.deepEqual(links, []); assert.equal(requests.length, 2); fresh();
    } else if (scenario === 'poll_serialization') {
        el('pay-check-btn').onclick(); el('pay-check-btn').onclick();
        assert.equal(requests.length, 1, 'only one status read in flight per view');
        await reply(0, {status: 'pending'});
        const checked = el('pay-check-btn').onclick();
        assert.equal(requests.length, 2);
        await reply(1, {status: 'paid'}); await checked;
        assert.match(el('pay-card-title').textContent, /оплачена/);
        assert.equal(requests[1].options.cache, 'no-store');
    } else if (scenario === 'poll_timeout' || scenario === 'body_timeout') {
        if (scenario === 'body_timeout') {
            requests[0].resolve({ok: true, json: () => new Promise((resolve, reject) => {
                requests[0].options.signal.addEventListener('abort', () => reject(new Error('body timeout')), {once: true});
            })});
            await flush();
        }
        assert.equal(requests.length, 1);
        assert.equal(deadlines.size, 1);
        const deadline = [...deadlines.values()][0];
        assert.equal(deadline.delay, 10000);
        deadline.fn(); await flush();
        assert.equal(requests[0].options.signal.aborted, true);
        assert.equal(deadlines.size, 0);
        const checked = el('pay-check-btn').onclick();
        assert.equal(requests.length, 2, 'timed-out read must not disable future status checks');
        await reply(1, {status: 'paid'}); await checked;
        assert.match(el('pay-card-title').textContent, /оплачена/);
        assert.equal(deadlines.size, 0);
    } else if (scenario === 'poll_failure') {
        requests[0].reject(new Error('synthetic failure')); await flush();
        const checked = el('pay-check-btn').onclick();
        assert.equal(requests.length, 2);
        await reply(1, {status: 'paid'}); await checked;
        assert.match(el('pay-card-title').textContent, /оплачена/);
    } else if (scenario === 'terminal_open') {
        await reply(0, {status: 'paid'}); oldOpen();
        assert.deepEqual(links, []);
    } else if (scenario === 'paid_refresh') {
        await reply(0, {status: 'paid'});
        const checked = el('pay-check-btn').onclick();
        await reply(1, {status: 'sent'}); await checked;
        assert.match(el('pay-card-title').textContent, /выплачена/);
    } else throw new Error('unknown scenario');
    console.log(JSON.stringify({scenario, result: 'PASS'}));
}
main().catch(error => {console.error(error); process.exitCode = 1;});
