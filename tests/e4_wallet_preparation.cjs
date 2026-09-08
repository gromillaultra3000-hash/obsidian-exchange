'use strict';

// Reuse the existing production-extraction harness unchanged. Only the network
// boundary is replaced with deferred promises; every review handler is shipped JS.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const [sourcePath, scenario, serializedParameters] = process.argv.slice(2);
const parameters = JSON.parse(serializedParameters || '{}');
const harnessSource = fs.readFileSync(path.join(__dirname, 'e4_recipient_review_behavior.cjs'), 'utf8');
const split = harnessSource.indexOf('\nfunction assertBuyWrite(');
assert.ok(split > 0, 'existing extraction harness boundary must remain explicit');
const factory = vm.runInThisContext('(function(require, process) {\n' + harnessSource.slice(0, split)
    + '\nreturn harness;\n})', {filename: 'shared-recipient-harness.cjs'});
const harness = factory(require, {argv: ['', '', sourcePath, '', '{}']});

function deferred() {
    let resolve, reject;
    const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
    return {promise, resolve, reject};
}
function setup() {
    const h = harness();
    const pending = [];
    h.context.fetch = (url, options) => {
        assert.ok(['/api/wallet/transfer-request', '/api/wallet/send-request'].includes(url),
            'no order writer or signed marker may be reached');
        h.requests.push({url, body: JSON.parse(options.body)});
        const fetch = deferred(), json = deferred();
        pending.push({fetch, json});
        return fetch.promise;
    };
    h.el('w-to').value = h.walletRequest.messages[0].address;
    h.el('w-amount').value = '1.25';
    h.start = action => action === 'payment'
        ? h.context.walletPay(42, h.el('sell-card-pay')) : h.context.walletTransfer();
    h.response = async (index, outcome = 'success') => {
        const p = pending[index];
        if (outcome === 'fetch-reject') p.fetch.reject(new Error('synthetic fetch rejection'));
        else {
            p.fetch.resolve({ok: outcome !== 'http-error', json: () => p.json.promise});
            if (outcome === 'json-reject') p.json.reject(new Error('synthetic json rejection'));
            else p.json.resolve({ok: outcome !== 'api-error', message: 'synthetic stale failure',
                sell_id: 42 + index, address: 'EQ' + String(index).repeat(46), amount: index + 1,
                marker: 'synthetic ' + index,
                request: {...h.walletRequest, messages: [{...h.walletRequest.messages[0], amount: String(index + 1)}]}});
        }
    };
    h.headers = index => pending[index].fetch.resolve({ok: true, json: () => pending[index].json.promise});
    h.snapshot = () => JSON.stringify(['exchange-review', 'exchange-review-title',
        'exchange-review-summary', 'exchange-review-freshness', 'exchange-review-ack',
        'exchange-review-confirm', 'w-send-msg', 'sell-card-pay'].map(id => {
        const e = h.el(id);
        return [id, e.textContent, e.innerHTML, e.style.display, e.checked, e.disabled];
    }));
    h.noEffects = () => {
        assert.equal(h.signingAttempts.length, 0);
        assert.deepEqual(h.storageWrites, []);
        assert.ok(h.requests.every(r => r.url.endsWith('-request')));
    };
    return h;
}
async function cancel(h, boundary) {
    if (boundary === 'cancel') await h.el('exchange-review-cancel').fire('click');
    else if (boundary === 'close') h.context.closeExchangeReview();
    else if (boundary === 'escape') await h.document.fire('keydown', {key: 'Escape'});
    else if (boundary === 'expiry') h.advance(120001);
    else throw new Error(boundary);
}
async function cancelled({action, boundary, stage}) {
    const h = setup();
    const pending = h.start(action);
    if (stage === 'json') { h.headers(0); await Promise.resolve(); }
    await cancel(h, boundary);
    const state = h.snapshot();
    await h.response(0);
    await pending;
    assert.equal(h.el('exchange-review').style.display, 'none', 'cancelled preparation cannot reopen review');
    assert.equal(h.snapshot(), state, 'late response cannot change cancelled UI');
    h.noEffects();
}
async function superseded({action, replacement, order, outcome, stage}) {
    const h = setup();
    const old = h.start(action);
    if (stage === 'json') { h.headers(0); await Promise.resolve(); }
    const fresh = h.start(replacement);
    if (order === 'old-first') {
        const state = h.snapshot();
        await h.response(0, outcome); await old;
        assert.equal(h.snapshot(), state, 'superseded response cannot alter pending newer UI');
    }
    await h.response(1); await fresh;
    assert.equal(h.el('exchange-review').style.display, 'flex');
    assert.equal(h.row('Получатель').value, 'EQ' + '1'.repeat(46));
    await h.acknowledge();
    if (order === 'old-last') {
        const state = h.snapshot();
        await h.response(0, outcome); await old;
        assert.equal(h.snapshot(), state, 'stale completion cannot replace fresh review or its acknowledgement');
    }
    await h.el('exchange-review-confirm').fire('click');
    await h.el('exchange-review-confirm').fire('click');
    assert.equal(h.signingAttempts.length, 1, 'current acknowledged handoff works exactly once');
    assert.equal(h.signingAttempts[0].messages[0].amount, '2');
    assert.equal(h.requests.length, 2, 'inert signing rejection cannot mark payment signed');
}
async function exchangeSupersedes({action, replacement, boundary}) {
    const h = setup();
    const pending = h.start(action);
    if (replacement === 'buy') h.context.beginBuyOrder();
    else await h.context.createSellOrder();
    assert.equal(h.el('exchange-review').style.display, 'flex');
    if (boundary !== 'open') await cancel(h, boundary);
    const state = h.snapshot();
    await h.response(0); await pending;
    assert.equal(h.snapshot(), state, 'wallet preparation cannot replace later exchange review state');
    h.noEffects();
}
async function preparingReplacesReview({action, replacement}) {
    const h = setup();
    const first = h.start(action);
    await h.response(0); await first;
    await h.acknowledge();
    const next = h.start(replacement);
    assert.equal(h.el('exchange-review').style.display, 'none', 'new preparation closes previous review');
    h.noEffects();
    await h.response(1); await next;
    assert.equal(h.el('exchange-review-ack').checked, false, 'new request requires new acknowledgement');
    assert.equal(h.el('exchange-review-confirm').disabled, true);
    await h.confirm();
    assert.equal(h.signingAttempts.length, 1);
    assert.equal(h.signingAttempts[0].messages[0].amount, '2');
}
async function fresh({action, boundary}) {
    const h = setup();
    const pending = h.start(action);
    await h.response(0); await pending;
    assert.equal(h.el('exchange-review-ack').checked, false);
    assert.equal(h.el('exchange-review-confirm').disabled, true);
    await h.el('exchange-review-confirm').fire('click');
    h.noEffects();
    await h.acknowledge();
    if (boundary !== 'confirm') await cancel(h, boundary);
    await h.el('exchange-review-confirm').fire('click');
    await h.el('exchange-review-confirm').fire('click');
    assert.equal(h.signingAttempts.length, boundary === 'confirm' ? 1 : 0);
    assert.equal(h.requests.length, 1);
}
const scenarios = {preparing_replaces_review: preparingReplacesReview, cancelled, superseded, exchange_supersedes: exchangeSupersedes, fresh};
assert.ok(scenarios[scenario]);
scenarios[scenario](parameters).catch(error => { console.error(error.stack); process.exitCode = 1; });
