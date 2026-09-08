'use strict';
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const crypto = require('node:crypto'), path = require('node:path');
const root = path.resolve(__dirname, '../..'), sourcePath = path.join(root, 'relay/webapp.html');
const source = fs.readFileSync(sourcePath, 'utf8');
const contractPath = path.join(__dirname, 'next-prerequisite-backend.json');
const contract = JSON.parse(fs.readFileSync(contractPath, 'utf8'));
const elements = new Map(['history-list', 'history-summary', 'history-load-status', 'ecosystem-activity-status']
    .map(id => [id, {innerHTML: '', textContent: '', style: {}, setAttribute() {}, querySelectorAll() {return [];}}]));
const ctx = vm.createContext({document: {getElementById: id => elements.get(id)},
    location: {origin: 'https://acceptance.invalid'}, fixtures: contract.apiResponse});
const start = source.indexOf('        let historyOrders =');
const end = source.indexOf('        (function wireHistoryControls()', start);
const escapeStart = source.indexOf('        function esc(s) {');
const escapeEnd = source.indexOf('        async function loadWalletBook()', escapeStart);
assert.ok([start, end, escapeStart, escapeEnd].every(index => index >= 0));
vm.runInContext(source.slice(escapeStart, escapeEnd) + source.slice(start, end), ctx);
vm.runInContext("historyOrders=fixtures;historyLoadState='ready';renderHistoryOrders();renderEcosystemActivity(historyOrders);", ctx);
const markup = elements.get('history-list').innerHTML;
const status = markup.match(/<span class="status">(.*?)<\/span>/)[1];
assert.equal(status, 'Ожидание оплаты');
assert.equal(contract.actualSessionDead, true);
assert.equal(markup.includes('class="btn-pay"'), false);
assert.equal(markup.includes('history-advice'), false);
assert.equal(markup.includes('Платёжная сессия закрыта'), false);
assert.equal(markup.includes('history-support-order'), true);
const report = {
    schemaVersion: 'e4-activity-session-lifecycle-next-prerequisite.v1',
    recordedAt: new Date().toISOString(), reviewer: 'Codex independent acceptance /root/receipt_acceptance',
    result: 'REPRODUCED_REMAINING_PREREQUISITE',
    nextCanonicalItem: 'E4 / ACTIVITY_PAYMENT_SESSION_STATE / expose closed payment-session state truthfully in activity',
    canonicalCriterion: 'E4 unified notification/evidence/support centre and understandable monetary-path status',
    sourcePath: 'relay/webapp.html', sourceSha256: crypto.createHash('sha256').update(source).digest('hex'),
    backendEvidence: {path: 'docs/e4-activity-receipt/next-prerequisite-backend.json',
        sha256: crypto.createHash('sha256').update(fs.readFileSync(contractPath)).digest('hex'), inputs: contract.inputs},
    method: 'Actual read-only SQLite repository methods over in-memory synthetic ledger and exact api_history/_session_dead, then exact shipped history/overview rendering in Node VM. No live API/database/provider or action invocation.',
    observed: {latestSessionStatus: 'failed', orderStatus: 'pending', existingSessionDeadHelper: true,
        serializedSessionToken: null, historyOmitsSessionState: true, visibleStatus: status,
        paymentActionPresent: false, closedSessionAdvicePresent: false,
        supportRemainsAvailable: true, overviewText: elements.get('ecosystem-activity-status').textContent},
    impact: 'The same backend state recognized as a closed provider session in the payment flow is still described as waiting for payment in activity. The current action is correctly absent, but the reason and next safe step are missing.',
    boundedImplementation: 'Expose an owner-scoped read-only payment-session state in the existing activity snapshot, preserve receipt/order-status precedence, and show closed-session explanation and support without reintroducing a payment action or inferring payment failure from missing metadata.',
    currentSliceDisposition: 'One separately bounded E4 status-contract slice. No session-state backend or product changes made here.',
    limitations: ['Synthetic reproduction proves a supported persisted backend shape and current UI output; it does not measure real customer incidence.',
        'No assertion that funds were lost, that a failed payment session implies a failed order, or that an absent session alone proves provider closure.',
        'This is separate from receipt history and transaction evidence. No additional next candidate or E4 closure is proposed.'],
};
fs.writeFileSync(path.join(__dirname, 'next-prerequisite.json'), JSON.stringify(report, null, 2) + '\n');
console.log(JSON.stringify({result: report.result, nextCanonicalItem: report.nextCanonicalItem, observed: report.observed}));
