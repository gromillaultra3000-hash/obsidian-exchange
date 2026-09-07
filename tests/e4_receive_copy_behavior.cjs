'use strict';
// Execute shipped clipboard code and the actual receive button listener.
// Only DOM, clipboard, haptic and timer boundaries are synthetic.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const [sourcePath, scenario] = process.argv.slice(2);
const source = fs.readFileSync(sourcePath, 'utf8');
const address = 'EQ' + 'A'.repeat(46);
const els = new Map();
for (const id of ['w-recv-addr', 'w-copy', 'w-copy-status', 'w-address', 'w-proof-copy', 'w-recv', 'w-send', 'w-qr']) {
    els.set(id, {textContent: '', style: {display: 'none'}, removeAttribute(name) {delete this[name];}});
}
els.get('w-recv-addr').textContent = address;
els.get('w-copy').textContent = 'Скопировать адрес';
const status = els.get('w-copy-status');
const pending = [], writes = [], timers = new Map(), haptics = [];
const receives = [];
let timerId = 0;
const clipboard = {writeText(text) {
    writes.push(text);
    return new Promise((resolve, reject) => pending.push({resolve, reject}));
}};
const context = vm.createContext({document: {getElementById: id => els.get(id)},
    navigator: {clipboard}, tg: {HapticFeedback: {impactOccurred: value => haptics.push(value)}},
    setTimeout: fn => {timers.set(++timerId, fn); return timerId;},
    clearTimeout: id => timers.delete(id),
    fetch: () => new Promise((resolve, reject) => receives.push({resolve, reject})),
    on: (id, fn) => {els.get(id).click = fn;},
});
function extract(name) {
    const matches = [...source.matchAll(new RegExp('^        (?:async )?function ' + name + '\\([^]*?^        \\}(?=\\r?$)', 'gm'))];
    assert.equal(matches.length, 1);
    return matches[0][0];
}
vm.runInContext((source.match(/^        const walletCopyStates = .*$/m)?.[0] || '') + '\n' +
    (source.match(/^        let walletReceiveGeneration = .*$/m)?.[0] || '') + '\n' +
    (source.includes('function resetWalletReceive(') ? extract('resetWalletReceive') : '') + '\n' +
    (source.includes('function resetWalletCopy(') ? extract('resetWalletCopy') : '') + '\n' +
    extract('walletCopy') + '\n' + extract('walletReceive') + '\n' +
    source.match(/            on\('w-copy', \(\) => \{[^]*?^            \}\);/m)[0], context);
const settle = async () => { await Promise.resolve(); await Promise.resolve(); };
const click = () => els.get('w-copy').click();
function unchanged() {
    assert.equal(els.get('w-recv-addr').textContent, address, 'receive address must never become feedback');
    assert.equal(els.get('w-copy').textContent, 'Скопировать адрес');
}
async function main() {
    if (scenario === 'pending') {
        click(); unchanged();
        assert.equal(status.textContent, 'Копируем…');
        assert.deepEqual(haptics, []);
        assert.equal(timers.size, 0);
        pending[0].resolve(); await settle();
        assert.equal(status.textContent, '✓ скопировано');
        assert.equal(haptics.length, 1);
    } else if (scenario === 'repeat') {
        click(); click(); unchanged();
        pending[0].resolve(); await settle();
        assert.equal(status.textContent, 'Копируем…', 'old completion cannot replace latest pending feedback');
        pending[1].resolve(); await settle();
        click(); pending[2].resolve(); await settle();
        assert.deepEqual(writes, [address, address, address]); unchanged();
        assert.equal(timers.size, 1);
        for (const fn of [...timers.values()]) fn();
        assert.equal(status.textContent, ''); unchanged();
    } else if (scenario === 'reject' || scenario === 'unavailable' || scenario === 'throw' || scenario === 'empty') {
        if (scenario === 'unavailable') context.navigator.clipboard = undefined;
        if (scenario === 'throw') clipboard.writeText = () => {throw new Error('private diagnostic');};
        if (scenario === 'empty') els.get('w-recv-addr').textContent = '';
        click();
        if (scenario === 'reject') pending[0].reject(new Error('private diagnostic'));
        await settle();
        assert.match(status.textContent, /Не удалось скопировать/);
        assert.ok(!status.textContent.includes('private diagnostic'));
        assert.deepEqual(haptics, []);
        if (scenario === 'empty') assert.equal(writes.length, 0);
        else unchanged();
        if (scenario === 'reject') {
            click(); pending[1].resolve(); await settle();
            assert.equal(status.textContent, '✓ скопировано'); unchanged();
        }
    } else if (scenario === 'out_of_order') {
        click(); click();
        pending[1].resolve(); await settle();
        pending[0].reject(new Error('old failure')); await settle();
        assert.equal(status.textContent, '✓ скопировано');
        assert.equal(haptics.length, 1); unchanged();
    } else if (scenario === 'close') {
        els.get('w-recv').style.display = 'block';
        click(); await context.walletReceive();
        assert.equal(status.textContent, '');
        pending[0].resolve(); await settle();
        assert.equal(status.textContent, '');
        assert.equal(haptics.length, 0);
        assert.equal(els.get('w-recv-addr').textContent, '');
        assert.equal(els.get('w-copy').disabled, true);
    } else if (scenario === 'receive_reorder' || scenario === 'receive_failure' || scenario === 'receive_reset') {
        els.get('w-qr').src = 'old synthetic QR';
        const first = context.walletReceive();
        assert.equal(els.get('w-copy').disabled, true);
        assert.equal(els.get('w-recv-addr').textContent, '');
        assert.equal(els.get('w-qr').src, undefined);
        if (scenario === 'receive_reset') {
            context.resetWalletReceive();
            receives[0].resolve({ok: true, json: async () => ({ok: true, address})});
            await first;
            assert.equal(els.get('w-recv').style.display, 'none');
            assert.equal(els.get('w-recv-addr').textContent, '');
            assert.equal(els.get('w-copy').disabled, true);
        } else if (scenario === 'receive_failure') {
            receives[0].reject(new Error('synthetic receive failure')); await first;
            assert.equal(els.get('w-copy').disabled, true);
            assert.equal(els.get('w-recv-addr').textContent, '');
        } else {
            await context.walletReceive(); // close, then open a newer request
            const second = context.walletReceive();
            const newerAddress = 'EQ' + 'B'.repeat(46);
            receives[1].resolve({ok: true, json: async () => ({ok: true, address: newerAddress, qr_image: 'new QR'})});
            await second;
            receives[0].resolve({ok: true, json: async () => ({ok: true, address, qr_image: 'old QR'})});
            await first;
            assert.equal(els.get('w-recv-addr').textContent, newerAddress);
            assert.equal(els.get('w-qr').src, 'new QR');
            assert.equal(els.get('w-copy').disabled, false);
            click(); pending[0].resolve(); await settle();
            assert.deepEqual(writes, [newerAddress]);
        }
    } else if (scenario === 'shared_labels') {
        for (const id of ['w-address', 'w-proof-copy']) {
            const el = els.get(id);
            const original = id === 'w-address' ? 'EQA…AAA' : 'Копировать';
            el.textContent = original;
            const first = context.walletCopy(address, el);
            pending.at(-1).resolve(); await first;
            const second = context.walletCopy(address, el);
            pending.at(-1).resolve(); await second;
            for (const fn of [...timers.values()]) fn();
            assert.equal(el.textContent, original);
        }
    } else if (scenario === 'rerender') {
        const el = els.get('w-address'); el.textContent = 'old address';
        const task = context.walletCopy(address, el);
        context.resetWalletCopy(el); el.textContent = 'new address';
        pending[0].resolve(); await task;
        assert.equal(el.textContent, 'new address');
        assert.equal(haptics.length, 0);
    } else if (scenario === 'haptic_throw') {
        context.tg.HapticFeedback.impactOccurred = () => {throw new Error('haptic unavailable');};
        const task = context.walletCopy(address, status);
        pending[0].resolve();
        assert.equal(await task, true);
        assert.equal(status.textContent, '✓ скопировано');
    } else throw new Error('unknown scenario');
}
main().then(() => console.log(JSON.stringify({scenario, result: 'PASS'})))
    .catch(error => {console.error(error.stack); process.exitCode = 1;});
