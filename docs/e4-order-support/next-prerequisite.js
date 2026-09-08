const fs = require('fs');
const vm = require('vm');
const crypto = require('crypto');
const sourcePath = process.argv[2] || '/root/relay/webapp.html';
const source = fs.readFileSync(sourcePath, 'utf8');
const begin = source.indexOf('        let historyOrders =');
const end = source.indexOf('        (function wireHistoryControls()', begin);
const escBegin = source.indexOf('        function esc(s) {');
const escEnd = source.indexOf('        async function loadWalletBook()', escBegin);
if ([begin, end, escBegin, escEnd].some(x => x < 0)) throw Error('source boundaries absent');
const exact = source.slice(escBegin, escEnd) + source.slice(begin, end);
function environment() {
    const elements = new Map(['history-list', 'history-summary', 'ecosystem-activity-status'].map(id => [id, {
        id, innerHTML: '', textContent: '', style: {}, querySelectorAll() {return []},
    }]));
    const requests = [];
    const ctx = vm.createContext({document: {getElementById: id => elements.get(id)},
        fetch: (url, options) => new Promise((resolve, reject) => requests.push({url, options, resolve, reject})),
        tg: {initData: ''}, userId: 'synthetic-user', location: {origin: 'https://acceptance.invalid'},
    });
    vm.runInContext(exact, ctx);
    function snapshot() {
        const markup = elements.get('history-list').innerHTML;
        return {orders: JSON.parse(vm.runInContext('JSON.stringify(historyOrders)', ctx)),
            activitySummary: elements.get('ecosystem-activity-status').textContent,
            showsPaymentAction: markup.includes('💳 Оплатить'),
            showsTransactionEvidence: markup.includes('🔍 Транзакция'),
            showsLoadFailure: markup.includes('История сейчас недоступна'),
            summaryDisplay: elements.get('history-summary').style.display};
    }
    return {ctx, requests, snapshot};
}
const order = {order_id: 'synthetic-race-42', currency: 'TON', amount: 2000, created: '2026-09-08 00:00'};
const sent = {...order, status: 'sent', tx_url: 'https://explorer.invalid/synthetic-42'};
const pending = {...order, status: 'pending', session_token: 'synthetic-stale-session'};
async function run(mode) {
    const e = environment();
    const earlier = e.ctx.loadHistory();
    const newer = e.ctx.loadHistory();
    if (e.requests.length !== 2) throw Error('overlapping requests not created');
    e.requests[1].resolve({ok: true, json: async () => [sent]});
    await newer;
    const afterNewer = e.snapshot();
    if (mode === 'older-success') e.requests[0].resolve({ok: true, json: async () => [pending]});
    else e.requests[0].reject(Error('synthetic stale request failure'));
    await earlier;
    const afterOlder = e.snapshot();
    return {mode, afterNewer, afterOlder, requestCount: e.requests.length,
        allRequestsReadOnlyNoStore: e.requests.every(r => r.options.cache === 'no-store' && !r.options.method)};
}
(async () => {
    const results = [await run('older-success'), await run('older-failure')];
    if (!results[0].afterOlder.showsPaymentAction || results[0].afterOlder.showsTransactionEvidence)
        throw Error('stale-success defect not reproduced');
    if (!results[1].afterOlder.showsLoadFailure || results[1].afterOlder.orders.length)
        throw Error('stale-failure defect not reproduced');
    const report = {schemaVersion: 'e4-activity-refresh-next-prerequisite.v1', recordedAt: new Date().toISOString(),
        reviewer: 'Codex independent context-aware acceptance /root/support_acceptance',
        nextCanonicalItem: 'E4 / ACTIVITY_REFRESH_RESPONSE_ORDERING / preserve the newest activity request against obsolete success and failure',
        canonicalCriterion: 'E4 unified notification/evidence/support centre and accessibility/usability of monetary paths',
        status: 'REPRODUCED_REMAINING_PREREQUISITE', sourcePath,
        sourceSha256: crypto.createHash('sha256').update(source).digest('hex'),
        location: ['loadHistory', 'renderHistoryOrders', 'renderEcosystemActivity'],
        method: 'Exact shipped history/helper declarations in Node VM; synthetic deferred read-only fetch and DOM. No real navigation, account/customer reads or money actions.',
        observedBehavior: 'Two overlapping loadHistory calls apply in completion order. An earlier pending snapshot finishing after the newer sent snapshot restores payment action and removes transaction evidence; an earlier failure instead erases the fresh completed history and shows unavailable state.',
        reproduction: results,
        boundedImplementation: 'Give history refresh ownership to its latest invocation; obsolete success/failure must not replace current history, summary, evidence or actions. Verify retry/filter behavior and use only synthetic reads/navigation spies.',
        currentSliceDisposition: 'Reproduced only; not implemented by ORDER_SUPPORT_CLIPBOARD_INDEPENDENCE.',
        limitations: ['Node VM uses synthetic DOM/requests and cannot establish human comprehension or Telegram/iOS/WebKit behavior.', 'Does not prove payment execution or a backend status-contract failure. Existing backend authorization is not exercised.', 'Does not close E4 or advance earlier gates.'],
    };
    fs.writeFileSync(process.argv[3] || '/root/output/playwright/e4-order-support-20260908/acceptance/next-prerequisite.json', JSON.stringify(report, null, 2)+'\n');
    console.log(JSON.stringify(report, null, 2));
})();
