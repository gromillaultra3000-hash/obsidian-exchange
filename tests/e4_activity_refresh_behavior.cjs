'use strict';
// Shipped history functions with deferred synthetic GET/header/body outcomes.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const [sourcePath, scenario] = process.argv.slice(2);
const source = fs.readFileSync(sourcePath, 'utf8');
const elements = new Map(['history-list', 'history-summary', 'history-load-status', 'ecosystem-activity-status']
    .map(id => [id, {id, innerHTML: '', textContent: '', style: {}, attributes: {},
        querySelectorAll() {return [];}, setAttribute(k, v) {this.attributes[k] = v;}}]));
const requests = [];
const ctx = vm.createContext({
    document: {getElementById: id => elements.get(id), querySelectorAll: () => []},
    fetch: (url, options) => new Promise((resolve, reject) => requests.push({url, options, resolve, reject})),
    tg: {initData: ''}, userId: 'synthetic-user', location: {origin: 'https://activity.invalid'},
});
const begin = source.indexOf('        let historyOrders =');
const end = source.indexOf('        (function wireHistoryControls()', begin);
const escBegin = source.indexOf('        function esc(s) {');
const escEnd = source.indexOf('        async function loadWalletBook()', escBegin);
assert.ok([begin, end, escBegin, escEnd].every(x => x >= 0));
vm.runInContext(source.slice(escBegin, escEnd) + source.slice(begin, end), ctx);
const base = {order_id: 'synthetic-race', currency: 'TON', amount: 2000, created: '2026-09-08'};
const pending = {...base, status: 'pending', session_token: 'synthetic-session'};
const sent = {...base, status: 'sent', tx_url: 'https://explorer.invalid/synthetic-race'};
const paid = {...base, status: 'paid', delayed: true};
const el = id => elements.get(id);
const snapshot = () => ({orders: JSON.parse(vm.runInContext('JSON.stringify(historyOrders)', ctx)),
    list: el('history-list').innerHTML, busy: el('history-list').attributes['aria-busy'],
    summary: el('history-summary').innerHTML, display: el('history-summary').style.display,
    overview: el('ecosystem-activity-status').textContent, feedback: el('history-load-status').textContent});
const load = kind => kind === 'overview' ? ctx.loadEcosystemActivity() : ctx.loadHistory();
const reply = (n, rows = [sent]) => requests[n].resolve({ok: true, json: async () => rows});
const flush = async () => {for (let n = 0; n < 6; n++) await Promise.resolve();};
async function error(n, mode) {
    if (mode === 'reject') requests[n].reject(Error('synthetic private failure'));
    else if (mode === 'http') requests[n].resolve({ok: false});
    else if (mode === 'json') requests[n].resolve({ok: true, json: async () => {throw Error('synthetic json');}});
    else reply(n, mode === 'invalid_row' ? [null] : {status: 'not-an-array'});
    await flush();
}
function isLoading() {
    const s = snapshot();
    assert.deepEqual(s.orders, []);
    assert.match(s.list, /skeleton-line/);
    assert.equal(s.busy, 'true'); assert.equal(s.display, 'none');
    assert.match(s.feedback, /Обновляем/); assert.match(s.overview, /Обновляем/);
    assert.doesNotMatch(s.list, /Оплатить|У вас пока нет заявок|История сейчас недоступна/);
}
function isSent() {
    const s = snapshot(); assert.equal(s.orders[0].status, 'sent');
    assert.match(s.list, /Транзакция/); assert.doesNotMatch(s.list, /Оплатить/);
    assert.equal(s.busy, 'false'); assert.equal(s.display, 'grid');
    assert.match(s.overview, /Нет активных/); assert.equal(s.feedback, 'Активность обновлена.');
}
function isError() {
    const s = snapshot(); assert.deepEqual(s.orders, []);
    assert.match(s.list, /История сейчас недоступна/); assert.doesNotMatch(s.list, /У вас пока нет заявок|Оплатить/);
    assert.equal(s.busy, 'false'); assert.equal(s.display, 'none');
    assert.match(s.overview, /временно недоступны/); assert.match(s.feedback, /Не удалось/);
}
async function main() {
    if (scenario.startsWith('older_')) {
        const a = load(), b = load(); reply(1); await b; isSent();
        const before = snapshot();
        if (scenario === 'older_success') reply(0, [pending]); else await error(0, scenario.slice(6));
        await a; assert.deepEqual(snapshot(), before);
    } else if (scenario === 'newer_failure') {
        const a = load(), b = load(); await error(1, 'reject'); await b; isError();
        const before = snapshot(); reply(0, [pending]); await a;
        assert.deepEqual(snapshot(), before);
    } else if (scenario === 'pending_older_success' || scenario === 'pending_older_failure') {
        const init = load(); reply(0, [pending]); await init;
        const a = load(), b = load(); isLoading();
        if (scenario.endsWith('success')) reply(1, [pending]); else await error(1, 'reject');
        await a; isLoading(); reply(2); await b; isSent();
    } else if (scenario.startsWith('body_')) {
        const a = load(); let resolveBody, rejectBody;
        requests[0].resolve({ok: true, json: () => new Promise((res, rej) => {resolveBody = res; rejectBody = rej;})});
        await flush(); assert.equal(typeof resolveBody, 'function');
        const b = load(); reply(1); await b; const before = snapshot();
        if (scenario === 'body_success') resolveBody([pending]); else rejectBody(Error('stale private body'));
        await a; assert.deepEqual(snapshot(), before); isSent();
    } else if (scenario.startsWith('cross_')) {
        const kinds = scenario.slice(6).split('_');
        const a = load(kinds[0]), b = load(kinds[1]); reply(1); await b; isSent();
        const before = snapshot(); reply(0, [pending]); await a;
        assert.deepEqual(snapshot(), before);
    } else if (scenario === 'filters_pending') {
        const a = load(); reply(0, [pending]); await a;
        assert.match(snapshot().list, /Оплатить/);
        const b = load();
        for (const f of ['pending', 'sent', 'paid', 'all']) {ctx.setHistoryFilter(f); isLoading();}
        assert.equal(requests.length, 2); reply(1); await b; isSent();
    } else if (scenario === 'filters_error_retry') {
        const a = load(); await error(0, 'http'); await a; isError();
        for (const f of ['pending', 'sent', 'paid', 'all']) {ctx.setHistoryFilter(f); isError();}
        assert.equal(requests.length, 1);
        const b = load(); isLoading(); ctx.setHistoryFilter('sent'); reply(1); await b; isSent();
        ctx.setHistoryFilter('pending'); assert.match(snapshot().list, /В этой группе заявок пока нет/);
        assert.equal(snapshot().orders.length, 1); ctx.setHistoryFilter('all'); isSent();
    } else if (scenario === 'empty_success') {
        const a = load(); reply(0, []); await a;
        assert.match(snapshot().list, /У вас пока нет заявок/);
        assert.equal(snapshot().busy, 'false'); assert.match(snapshot().overview, /Заявок пока нет/);
        ctx.setHistoryFilter('paid'); assert.match(snapshot().list, /У вас пока нет заявок/);
    } else if (scenario.startsWith('current_')) {
        const a = load(); await error(0, scenario.slice(8)); await a; isError();
        const b = load(); reply(1); await b; isSent();
    } else if (scenario === 'three_calls') {
        const a = load(), b = load('overview'), c = load();
        reply(1, [paid]); await b; isLoading(); reply(2); await c; isSent();
        const before = snapshot(); reply(0, [pending]); await a; assert.deepEqual(snapshot(), before);
    } else throw Error('unknown scenario');
    assert.ok(requests.every(r => r.options.cache === 'no-store' && !r.options.method
        && r.options.headers['X-Telegram-Init-Data'] === ''
        && r.url === '/api/history?user_id=synthetic-user'));
    console.log(JSON.stringify({scenario, result: 'PASS'}));
}
main().catch(error => {console.error(error); process.exitCode = 1;});
