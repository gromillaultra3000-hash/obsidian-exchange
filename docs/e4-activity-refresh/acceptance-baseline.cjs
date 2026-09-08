'use strict';
const fs = require('node:fs');
const vm = require('node:vm');
const crypto = require('node:crypto');
const assert = require('node:assert/strict');
const sourcePath = process.argv[2] || '/root/relay/webapp.html';
const source = fs.readFileSync(sourcePath, 'utf8');
const out = '/root/output/playwright/e4-activity-refresh-20260908/acceptance';
const begin = source.indexOf('        let historyOrders =');
const end = source.indexOf('        (function wireHistoryControls()', begin);
const escBegin = source.indexOf('        function esc(s) {');
const escEnd = source.indexOf('        async function loadWalletBook()', escBegin);
assert.ok(begin > 0 && end > begin && escBegin > 0 && escEnd > escBegin);
const exact = source.slice(escBegin, escEnd) + source.slice(begin, end);
const pending = {order_id: 'synthetic-race-42', currency: 'TON', amount: 2000,
    created: '2026-09-08 00:00', status: 'pending', session_token: 'synthetic-stale'};
const sent = {...pending, status: 'sent', tx_url: 'https://explorer.invalid/synthetic-42'};
const flush = async () => {for (let i = 0; i < 8; i++) await Promise.resolve();};
function environment() {
    const elements = new Map(['history-list', 'history-summary', 'ecosystem-activity-status'].map(id => [id, {
        id, innerHTML: '', textContent: '', style: {}, querySelectorAll() {return []},
    }]));
    const requests = [];
    const ctx = vm.createContext({document: {getElementById: id => elements.get(id), querySelectorAll: () => []},
        fetch: (url, options) => new Promise((resolve, reject) => requests.push({url, options, resolve, reject})),
        tg: {initData: ''}, userId: 'synthetic-user', location: {origin: 'https://acceptance.invalid'},
    });
    vm.runInContext(exact, ctx);
    function snapshot() {
        const markup = elements.get('history-list').innerHTML;
        return {orders: JSON.parse(vm.runInContext('JSON.stringify(historyOrders)', ctx)),
            overview: elements.get('ecosystem-activity-status').textContent,
            showsPaymentAction: markup.includes('💳 Оплатить'),
            showsTransactionEvidence: markup.includes('🔍 Транзакция'),
            showsLoadFailure: markup.includes('История сейчас недоступна'),
            showsFalseEmpty: markup.includes('У вас пока нет заявок'),
            showsLoading: markup.includes('skeleton-line'),
            summaryDisplay: elements.get('history-summary').style.display || '',
            filter: vm.runInContext('historyFilter', ctx)};
    }
    const reply = (index, body) => requests[index].resolve({ok: true, json: async () => body});
    return {ctx, requests, snapshot, reply};
}
async function overlapping(mode) {
    const e = environment();
    const earlier = e.ctx.loadHistory();
    let releaseBody;
    if (mode === 'body-success' || mode === 'body-failure') {
        e.requests[0].resolve({ok: true, json: () => new Promise((resolve, reject) => {
            releaseBody = mode === 'body-success' ? () => resolve([pending]) : () => reject(Error('old body failure'));
        })});
        await flush();
        assert.equal(typeof releaseBody, 'function');
    }
    const newer = e.ctx.loadHistory();
    e.reply(1, [sent]); await newer;
    const newest = e.snapshot();
    if (mode === 'success') e.reply(0, [pending]);
    else if (mode === 'failure') e.requests[0].reject(Error('old request failed'));
    else releaseBody();
    await earlier;
    const stale = e.snapshot();
    if (mode.endsWith('failure')) assert.equal(stale.showsLoadFailure, true);
    else assert.equal(stale.showsPaymentAction, true);
    return {case: 'overlapping-history-' + mode, afterNewest: newest, afterObsolete: stale};
}
async function sharedOverview(mode) {
    const e = environment();
    const earlier = e.ctx.loadEcosystemActivity();
    const newer = e.ctx.loadHistory();
    e.reply(1, [sent]); await newer;
    const newest = e.snapshot();
    if (mode === 'success') e.reply(0, [pending]);
    else e.requests[0].reject(Error('old overview failed'));
    await earlier;
    const stale = e.snapshot();
    assert.equal(stale.showsTransactionEvidence, true);
    assert.notEqual(stale.overview, newest.overview);
    return {case: 'overview-before-history-' + mode, afterNewest: newest, afterObsolete: stale};
}
async function historyBeforeOverview() {
    const e = environment();
    const earlier = e.ctx.loadHistory();
    const newer = e.ctx.loadEcosystemActivity();
    e.reply(1, [sent]); await newer;
    const newest = e.snapshot();
    e.reply(0, [pending]); await earlier;
    const stale = e.snapshot();
    assert.equal(stale.showsPaymentAction, true);
    assert.notEqual(stale.overview, newest.overview);
    return {case: 'history-before-newer-overview', afterNewest: newest, afterObsolete: stale};
}
async function filterResurrection() {
    const e = environment();
    const initial = e.ctx.loadHistory(); e.reply(0, [pending]); await initial;
    const refresh = e.ctx.loadHistory();
    const whileLoading = e.snapshot();
    e.ctx.setHistoryFilter('pending');
    const afterFilter = e.snapshot();
    assert.equal(whileLoading.showsLoading, true);
    assert.equal(afterFilter.showsPaymentAction, true);
    e.requests[1].reject(Error('newest refresh failure')); await refresh;
    const afterFailure = e.snapshot();
    e.ctx.setHistoryFilter('all');
    const afterFailureFilter = e.snapshot();
    assert.equal(afterFailure.showsLoadFailure, true);
    assert.equal(afterFailureFilter.showsFalseEmpty, true);
    return {case: 'filter-during-pending-and-failure', whileLoading, afterFilter, afterFailure, afterFailureFilter};
}
(async()=> {
    const results=[];
    for (const mode of ['success','failure','body-success','body-failure']) results.push(await overlapping(mode));
    for (const mode of ['success','failure']) results.push(await sharedOverview(mode));
    results.push(await historyBeforeOverview()); results.push(await filterResurrection());
    const report={schemaVersion:'e4-activity-refresh-acceptance-baseline.v1', recordedAt:new Date().toISOString(),
        reviewer:'Codex independent context-aware acceptance /root/support_acceptance',
        route:'E4 / ACTIVITY_REFRESH_RESPONSE_ORDERING', sourcePath,
        sourceSha256:crypto.createHash('sha256').update(source).digest('hex'),
        method:'Exact shipped history/helper declarations, synthetic DOM and deferred read-only fetch/JSON bodies in Node VM; no real APIs, navigation, messages or money actions.',
        result:'BASELINE_DEFECTS_REPRODUCED', results,
        acceptance:[
            'Only the latest activity invocation may publish overview/counts/history/evidence/actions, including across loadHistory and loadEcosystemActivity.',
            'Ownership is checked after awaited response bodies as well as fetch; old success, network failure, HTTP failure, malformed JSON and delayed body rejection are inert.',
            'Starting a fresh activity read exposes truthful loading state; filters cannot resurrect cached actions or turn error/loading into an empty-success claim.',
            'Newest success renders with the currently selected valid filter; newest failure retains honest retry state; latest retry and empty-success recover normally.',
            'All requests retain no-store and existing owner-scoped read-only auth contract; no new request writer, automatic payment/navigation, or support message is added.',
            'Existing explicit copy/support remain usable after successful refresh; status, evidence and support semantics remain consistent at 320/390/1280px with default browser motion.'
        ],
        limitations:['Synthetic completion ordering proves UI state races only; no backend payment execution or real customer/account data was examined.','This evidence does not establish human comprehension or Telegram/iOS/WebKit acceptance.']};
    fs.writeFileSync(out+'/baseline.json',JSON.stringify(report,null,2)+'\n');
    console.log(JSON.stringify({result:report.result,sourceSha256:report.sourceSha256,cases:results.map(r=>r.case)},null,2));
})();
