'use strict';

// Independent race/control scenarios over the existing deterministic DOM/VM
// utility. Production functions are extracted verbatim; no browser, wallet,
// provider, database, host service or network is contacted.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const crypto = require('node:crypto');
const ROOT = path.resolve(__dirname, '../..');
const sourcePath = path.resolve(process.argv[2] || path.join(ROOT, 'relay/webapp.html'));
const utilityPath = path.join(ROOT, 'tests/e4_recipient_review_behavior.cjs');
const utility = fs.readFileSync(utilityPath, 'utf8');
const boundary = utility.indexOf('\nconst scenarios = {');
assert.ok(boundary > 0);
const context = {require, process: {argv: ['node', utilityPath, sourcePath]}, console};
vm.runInNewContext(utility.slice(0, boundary) + '\nglobalThis.securityHarness = harness;', context,
    {filename: utilityPath, timeout: 1000});
const harness = context.securityHarness;
const sha = value => crypto.createHash('sha256').update(value).digest('hex');
const report = {
    schemaVersion: 'e4-money-flow-independent-security-probe.v1',
    source: {path: path.relative(ROOT, sourcePath), sha256: sha(fs.readFileSync(sourcePath))},
    inputs: [__filename, utilityPath].map(file => ({path: path.relative(ROOT, file), sha256: sha(fs.readFileSync(file))})),
    method: 'Independent deferred-response and unresolved-signature scenarios; reuse only the existing exact-source extraction and deterministic boundary utility.',
    productionNetworkDatabaseWalletCalls: 0,
    cases: [],
};

function deferred() {
    let resolve, reject;
    const promise = new Promise((yes, no) => {resolve = yes; reject = no;});
    return {promise, resolve, reject};
}
function setup(action) {
    const h = harness();
    h.el('w-to').value = h.walletRequest.messages[0].address;
    h.el('w-amount').value = '1.25';
    h.el('w-comment').value = 'synthetic review';
    const pending = [];
    h.context.fetch = (url, options) => {
        h.requests.push({url, method: options.method, body: JSON.parse(options.body)});
        if (url === '/api/wallet/send-signed') return Promise.resolve({ok: true, json: async () => ({ok: true})});
        const d = deferred(); pending.push(d); return d.promise;
    };
    const response = id => ({ok: true, json: async () => ({ok: true, sell_id: id,
        amount: 1.25, address: h.walletRequest.messages[0].address,
        marker: 'synthetic ' + id, request: JSON.parse(JSON.stringify(h.walletRequest))})});
    const open = () => action === 'payment'
        ? h.context.walletPay(42, h.el('sell-card-pay')) : h.context.walletTransfer();
    return {h, pending, response, open};
}
async function test(name, fn) {
    try { const observation = await fn(); report.cases.push({name, result: 'PASS', ...observation}); }
    catch (error) { report.cases.push({name, result: 'FAIL', error: String(error.message)}); }
}

async function main() {
    for (const action of ['transfer', 'payment']) {
        await test(action + ':cancelled-review-not-reopened-by-older-response', async () => {
            const {h, pending, response, open} = setup(action);
            const first = open(); const second = open();
            assert.equal(pending.length, 2, 'scenario needs two in-flight preparations');
            pending[1].resolve(response(42)); await second;
            assert.equal(h.el('exchange-review').style.display, 'flex');
            await h.el('exchange-review-cancel').fire('click');
            assert.equal(h.el('exchange-review').style.display, 'none');
            pending[0].resolve(response(42)); await first;
            assert.equal(h.signingAttempts.length, 0, 'late preparation alone cannot sign');
            assert.equal(h.el('exchange-review').style.display, 'none', 'older preparation reopens a review after the newer review was explicitly cancelled');
        });
        await test(action + ':no-second-wallet-handoff-while-first-unresolved', async () => {
            const {h, pending, response, open} = setup(action);
            const signing = [];
            h.context.tcUI.sendTransaction = request => {h.signingAttempts.push(JSON.parse(JSON.stringify(request)));
                const d = deferred(); signing.push(d); return d.promise;};
            const first = open(); pending[0].resolve(response(42)); await first;
            const confirmFirst = h.confirm();
            await Promise.resolve(); await Promise.resolve(); await Promise.resolve();
            assert.equal(h.signingAttempts.length, 1);
            const second = open(); pending[1].resolve(response(42)); await second;
            const confirmSecond = h.confirm();
            await Promise.resolve(); await Promise.resolve(); await Promise.resolve();
            const attempts = h.signingAttempts.length;
            signing.forEach(d => d.reject(new Error('Synthetic wallet rejection')));
            await Promise.all([confirmFirst, confirmSecond]);
            assert.equal(h.requests.filter(r => r.url === '/api/wallet/send-signed').length, 0);
            assert.equal(attempts, 1, 'second sendTransaction was called before the first wallet result settled');
        });
        await test(action + ':unacknowledged-and-cancelled-never-sign', async () => {
            const {h, pending, response, open} = setup(action);
            const first = open(); pending[0].resolve(response(42)); await first;
            await h.el('exchange-review-confirm').fire('click');
            assert.equal(h.signingAttempts.length, 0);
            await h.acknowledge();
            await h.el('exchange-review-cancel').fire('click');
            await h.el('exchange-review-confirm').fire('click');
            assert.equal(h.signingAttempts.length, 0);
        });
        await test(action + ':double-confirm-consumes-one-acknowledgement', async () => {
            const {h, pending, response, open} = setup(action);
            const first = open(); pending[0].resolve(response(42)); await first;
            const signature = deferred();
            h.context.tcUI.sendTransaction = request => {h.signingAttempts.push(JSON.parse(JSON.stringify(request))); return signature.promise;};
            await h.acknowledge();
            const firstConfirm = h.el('exchange-review-confirm').fire('click');
            const secondConfirm = h.el('exchange-review-confirm').fire('click');
            assert.equal(h.signingAttempts.length, 1);
            signature.reject(new Error('Synthetic wallet rejection'));
            await Promise.all([firstConfirm, secondConfirm]);
            assert.equal(h.requests.filter(r => r.url === '/api/wallet/send-signed').length, 0);
        });
    }
    report.passed = report.cases.filter(c => c.result === 'PASS').length;
    report.failed = report.cases.length - report.passed;
    report.result = report.failed ? 'REPRODUCED_FINDINGS' : 'PASS';
    process.stdout.write(JSON.stringify(report, null, 2) + '\n');
}
main().catch(error => {console.error(error.stack); process.exitCode = 1;});
