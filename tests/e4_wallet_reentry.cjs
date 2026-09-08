'use strict';
// Exact shared extraction harness; only DOM, SDK, network and clock are synthetic.
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
function setup(action, outcome = 'reject') {
    const h = harness();
    h.context.loadWallets = () => {};
    h.el('w-to').value = h.walletRequest.messages[0].address;
    h.el('w-amount').value = '1.25';
    h.context.tcUI.sendTransaction = request => {
        h.signingAttempts.push(JSON.parse(JSON.stringify(request)));
        if (outcome === 'sync') throw new Error('synthetic synchronous SDK failure');
        if (outcome === 'success') return Promise.resolve({boc: 'synthetic-not-a-boc'});
        return Promise.reject(new Error('synthetic generic SDK rejection'));
    };
    h.start = () => action === 'payment'
        ? h.context.walletPay(42, h.el('sell-card-pay')) : h.context.walletTransfer();
    h.message = () => h.el(action === 'payment' ? 'sell-card-pay' : 'w-send-msg').textContent;
    return h;
}
function guidance(text, action) {
    assert.match(text, /не повторяйте/i, 'must discourage repeating an uncertain transfer');
    assert.match(text, /истори[^.]*кошельк/i, 'must direct to external wallet history');
    if (action === 'payment') assert.match(text, /статус[^.]*заявк/i, 'must also check order status');
}
async function fresh({action}) {
    // A new VM represents reloaded Mini App: no in-memory ownership survives.
    const h = setup(action);
    await h.start();
    assert.equal(h.el('exchange-review').style.display, 'flex');
    const visible = ['description', 'risk', 'summary'].map(suffix => {
        const el = h.el('exchange-review-' + suffix);
        return el.textContent + el.innerHTML;
    }).join(' ');
    guidance(visible, action);
    assert.match(visible, /предыдущ|повторн|возврат|перезагруз/i, 'must cover reentry or prior attempt');
    assert.match(visible, /неизвест|неяс|не уверены/i, 'must identify uncertain outcome');
    assert.equal(h.signingAttempts.length, 0);
    assert.equal(h.el('exchange-review-ack').checked, false);
    await h.el('exchange-review-confirm').fire('click');
    assert.equal(h.signingAttempts.length, 0, 'unacknowledged review cannot hand off');
    assert.equal(h.requests.length, 1, 'review only prepares the request');
    assert.deepEqual(h.storageWrites, [], 'copy fix must not persist wallet information');
}
async function failure({action, outcome}) {
    const h = setup(action, outcome);
    await h.start();
    await h.confirm();
    assert.equal(h.signingAttempts.length, 1);
    assert.equal(h.requests.length, 1, 'SDK failure must not send signed marker');
    assert.deepEqual(h.signingAttempts[0], h.walletRequest);
    guidance(h.message(), action);
    assert.match(h.message(), /исход[^.]*неизвест|результат[^.]*неизвест/i,
        'generic SDK error cannot establish transaction failure');
    assert.match(h.message(), /мог[^.]*отправ|возмож[^.]*отправ/i,
        'must explain that transfer may already have been sent');
    h.advance(5000);
    assert.equal(h.signingAttempts.length, 1, 'no timer-driven retry');
    await h.start();
    assert.equal(h.el('exchange-review-ack').checked, false);
    await h.el('exchange-review-confirm').fire('click');
    assert.equal(h.signingAttempts.length, 1, 'new attempt requires fresh acknowledgement');
}
async function success({action}) {
    const h = setup(action, 'success');
    await h.start();
    assert.equal(h.signingAttempts.length, 0);
    await h.confirm();
    assert.equal(h.signingAttempts.length, 1);
    assert.deepEqual(h.signingAttempts[0], h.walletRequest);
    assert.equal(h.message(), action === 'payment' ? '✅ Подписано — ждём сеть'
        : '✅ Подписано. Операция появится в списке, когда её увидит сеть.');
    assert.equal(h.requests.length, action === 'payment' ? 2 : 1);
    if (action === 'payment') assert.deepEqual(h.requests[1], {
        url: '/api/wallet/send-signed', method: 'POST', body: {sell_id: 42}});
    h.advance(5000);
    assert.equal(h.signingAttempts.length, 1);
}
const scenarios = {fresh, failure, success};
assert.ok(scenarios[scenario]);
scenarios[scenario](parameters).then(() => console.log('REENTRY_CASE_COMPLETE'))
    .catch(error => {console.error(error.stack); process.exitCode = 1;});
