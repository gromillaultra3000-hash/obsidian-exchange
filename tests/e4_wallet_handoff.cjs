'use strict';
// Exact shared production-extraction harness prefix; only external boundaries are stubbed.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const [sourcePath, scenario, serializedParameters] = process.argv.slice(2);
const parameters = JSON.parse(serializedParameters || '{}');
const harnessSource = fs.readFileSync(path.join(__dirname, 'e4_recipient_review_behavior.cjs'), 'utf8');
const split = harnessSource.indexOf('\nfunction assertBuyWrite(');
assert.ok(split > 0);
const factory = vm.runInThisContext('(function(require, process) {\n' + harnessSource.slice(0, split)
    + '\nreturn harness;\n})', {filename: 'shared-recipient-harness.cjs'});
const harness = factory(require, {argv: ['', '', sourcePath, '', '{}']});
function deferred() {
    let resolve, reject;
    const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
    return {promise, resolve, reject};
}
async function flush() { for (let i = 0; i < 8; i++) await Promise.resolve(); }
function setup() {
    const h = harness();
    h.context.loadWallets = () => {};
    h.el('w-to').value = h.walletRequest.messages[0].address;
    h.el('w-amount').value = '1.25';
    h.reviews = [];
    const open = h.context.openExchangeReview;
    h.context.openExchangeReview = config => { h.reviews.push(config); return open(config); };
    h.sdk = [];
    h.throwSync = false;
    h.context.tcUI.sendTransaction = request => {
        h.signingAttempts.push(JSON.parse(JSON.stringify(request)));
        if (h.throwSync) throw new Error('synthetic synchronous SDK throw');
        const d = deferred(); h.sdk.push(d); return d.promise;
    };
    h.followup = deferred();
    h.preparation = null;
    h.context.fetch = async (url, options) => {
        h.requests.push({url, method: options.method, body: JSON.parse(options.body)});
        if (url === '/api/wallet/send-signed') return h.followup.promise;
        assert.ok(['/api/wallet/transfer-request', '/api/wallet/send-request'].includes(url));
        const data = {ok: true, from_address: '0:' + 'b'.repeat(64), sell_id: 42, amount: 1.25, address: h.walletRequest.messages[0].address,
            marker: 'synthetic invoice', request: h.walletRequest};
        return {ok: true, json: () => h.preparation ? h.preparation.promise : Promise.resolve(data)};
    };
    h.start = action => action === 'payment'
        ? h.context.walletPay(42, h.el('sell-card-pay')) : h.context.walletTransfer();
    h.prepCount = () => h.requests.filter(r => r.url.endsWith('-request')).length;
    h.signedCount = () => h.requests.filter(r => r.url.endsWith('send-signed')).length;
    return h;
}
async function reconcile(h, replacement) {
    const before = h.prepCount();
    await h.start(replacement);
    assert.equal(h.prepCount(), before, 'settled SDK retains unresolved-attempt block');
    h.el('wallet-attempt-ack').checked = true;
    await h.el('wallet-attempt-ack').fire('change');
    await h.el('wallet-attempt-remove').fire('click');
}
async function boundary(h, name) {
    if (name === 'cancel') await h.el('exchange-review-cancel').fire('click');
    if (name === 'close') h.context.closeExchangeReview();
    if (name === 'escape') await h.document.fire('keydown', {key: 'Escape'});
    if (name === 'expiry') h.advance(120001);
}
async function pending({action, replacement, boundary: name, outcome}) {
    const h = setup();
    await h.start(action);
    const confirm = h.confirm();
    await flush();
    assert.equal(h.signingAttempts.length, 1);
    await boundary(h, name);
    await h.start(replacement);
    assert.equal(h.prepCount(), 1, 'unresolved SDK must block every second preparation');
    assert.equal(h.reviews.length, 1, 'unresolved SDK must block second review');
    await h.reviews[0].onConfirm();
    assert.equal(h.signingAttempts.length, 1, 'forced stale callback must not reenter SDK');
    assert.equal(h.signedCount(), 0);
    if (outcome === 'reject') h.sdk[0].reject(new Error('synthetic reject'));
    else h.sdk[0].resolve({boc: 'synthetic-not-a-boc'});
    h.followup.resolve({ok: true});
    await confirm;
    assert.equal(h.signingAttempts.length, 1, 'settlement must not automatically retry');
    assert.equal(h.signedCount(), action === 'payment' && outcome === 'resolve' ? 1 : 0);
    assert.deepEqual(h.signingAttempts[0], h.walletRequest, 'SDK receives exact reviewed server request');
    await reconcile(h, replacement);
    await h.start(replacement);
    assert.equal(h.prepCount(), 2, 'explicit reconciliation permits fresh preparation');
    assert.equal(h.el('exchange-review-ack').checked, false);
    await h.el('exchange-review-confirm').fire('click');
    assert.equal(h.signingAttempts.length, 1, 'fresh action requires fresh acknowledgement');
    const second = h.confirm(); await flush();
    assert.equal(h.signingAttempts.length, 2);
    h.sdk[1].reject(new Error('synthetic cleanup reject')); await second;
}
async function syncThrow({action, replacement}) {
    const h = setup(); h.throwSync = true;
    await h.start(action); await h.confirm();
    assert.equal(h.signingAttempts.length, 1); assert.equal(h.signedCount(), 0);
    h.throwSync = false;
    await reconcile(h, replacement);
    await h.start(replacement);
    assert.equal(h.prepCount(), 2);
    const second = h.confirm(); await flush();
    assert.equal(h.signingAttempts.length, 2);
    h.sdk[0].reject(new Error('synthetic cleanup')); await second;
}
async function followup({replacement}) {
    const h = setup(); await h.start('payment');
    const first = h.confirm(); await flush();
    h.sdk[0].resolve({boc: 'synthetic-not-a-boc'}); await flush();
    assert.equal(h.signedCount(), 1);
    assert.deepEqual(h.requests.find(r => r.url.endsWith('send-signed')),
        {url: '/api/wallet/send-signed', method: 'POST', body: {sell_id: 42}});
    await reconcile(h, replacement);
    await h.start(replacement);
    assert.equal(h.prepCount(), 2, 'explicit reconciliation works outside SDK ownership');
    assert.equal(h.el('exchange-review-ack').checked, false);
    const second = h.confirm(); await flush();
    assert.equal(h.signingAttempts.length, 2);
    h.sdk[1].reject(new Error('synthetic cleanup')); await second;
    h.followup.reject(new Error('synthetic marker failure')); await first;
    assert.equal(h.signingAttempts.length, 2, 'failed marker does not retry SDK');
    assert.equal(h.signedCount(), 1, 'failed marker is not automatically retried');
}
async function lateJson({action, replacement}) {
    const h = setup(); await h.start(action);
    const stale = h.reviews[0].onConfirm;
    h.preparation = deferred();
    const next = h.start(replacement); await flush();
    const first = stale(); await flush();
    assert.equal(h.signingAttempts.length, 1);
    h.preparation.resolve({ok: true, from_address: '0:' + 'b'.repeat(64), sell_id: 42, amount: 1.25,
        address: h.walletRequest.messages[0].address, request: h.walletRequest});
    await next;
    assert.equal(h.reviews.length, 1, 'JSON completion while SDK pending cannot open another review');
    h.sdk[0].reject(new Error('synthetic cleanup')); await first;
}
const scenarios = {pending, sync_throw: syncThrow, followup, late_json: lateJson};
assert.ok(scenarios[scenario]);
scenarios[scenario](parameters).then(() => console.log('HANDOFF_CASE_COMPLETE'))
    .catch(error => {console.error(error.stack); process.exitCode = 1;});
