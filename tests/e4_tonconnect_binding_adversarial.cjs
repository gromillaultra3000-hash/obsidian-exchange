'use strict';
const assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
const source = fs.readFileSync(process.argv[2] || 'relay/webapp.html', 'utf8');
function extract(name) {
    const match = source.match(new RegExp('^        (?:async )?function ' + name + '\\([^]*?^        \\}(?=\\r?$)', 'm'));
    assert.ok(match, name); return match[0];
}
const initial = 'EQ' + 'A'.repeat(46), verified = 'EQ' + 'B'.repeat(46);
function setup() {
    const nodes = {currency: {value: 'TON'}, network: {value: 'MAINNET'}, address: {value: initial}, dest_tag: {value: 'old memo'},
        no_tag: {checked: false}, 'tc-msg': {textContent: '', className: ''}};
    const pending = [], counts = {profiles: 0, validations: 0};
    const context = vm.createContext({document: {getElementById: id => nodes[id]}, tg: {initData: ''},
        window: {__oeOfferings: [{code: 'TON', networks: [{code: 'MAINNET', label: 'TON'}], wallet_connect: true, tag_name: 'memo'}]},
        validateAddress() {counts.validations++;}, updateTagField() {}, loadWallets() {counts.profiles++;},
        fetch(url, options) {assert.equal(url, '/api/tonconnect/verify'); assert.equal(options.method, 'POST');
            return new Promise((resolve, reject) => pending.push({resolve, reject}));}});
    vm.runInContext('let tcPending=false,tcRecipientGeneration=0,tcPreparation=null;\n' + ['buyRouteSignature','currentOffering','tcSay','tcInvalidateRecipient','tcRecipientState','tcHandleWallet'].map(extract).join('\n'), context);
    context.wallet = {account: {address: 'synthetic'}, connectItems: {tonProof: {proof: {synthetic: true}}}};
    return {nodes, pending, counts, context, call: () => vm.runInContext('tcHandleWallet(wallet)', context)};
}
let checks = 0;
async function main() {
    for (const address of [undefined, null, {}, [], '', ' ', 'x'.repeat(257), 1, false]) {
        const h = setup(), p = h.call(); h.pending[0].resolve({ok: true, async json() {return {verified: true, address};}}); await p;
        assert.equal(h.nodes.address.value, initial); assert.equal(h.nodes.dest_tag.value, 'old memo'); assert.equal(h.counts.profiles, 0); checks++;
    }
    for (const value of [1, 'true', false, null]) {
        const h = setup(), p = h.call(); h.pending[0].resolve({ok: true, async json() {return {verified: value, address: verified};}}); await p;
        assert.equal(h.nodes.address.value, initial); assert.equal(h.counts.profiles, 0); checks++;
    }
    for (const change of ['address', 'memo', 'no-tag', 'route', 'wallet-disabled', 'away-back', 'disconnect', 'second-sdk']) {
        for (const outcome of ['success', 'error']) {
            const h = setup(), p = h.call();
            if (change === 'address') h.nodes.address.value = 'new recipient';
            if (change === 'memo') h.nodes.dest_tag.value = 'new memo';
            if (change === 'no-tag') h.nodes.no_tag.checked = true;
            if (change === 'route') h.nodes.currency.value = 'BTC';
            if (change === 'wallet-disabled') h.context.window.__oeOfferings[0].wallet_connect = false;
            if (change === 'away-back') {
                h.nodes.address.value = 'other'; vm.runInContext('tcInvalidateRecipient()', h.context);
                h.nodes.address.value = initial; vm.runInContext('tcInvalidateRecipient()', h.context);
            }
            if (change === 'disconnect') await vm.runInContext('tcHandleWallet(null)', h.context);
            if (change === 'second-sdk') await h.call();
            const before = JSON.stringify(h.nodes);
            if (outcome === 'error') h.pending[0].reject(new Error('synthetic failure'));
            else h.pending[0].resolve({ok: true, async json() {return {verified: true, address: verified};}});
            await p; assert.equal(JSON.stringify(h.nodes), before, change + ' ' + outcome);
            assert.equal(h.counts.profiles, 0); assert.equal(h.counts.validations, 0); assert.equal(h.pending.length, 1); checks++;
        }
    }
    for (const kind of ['non-ton', 'not-wallet-enabled', 'unknown-network']) {
        const h = setup();
        if (kind === 'non-ton') h.nodes.currency.value = 'BTC';
        if (kind === 'not-wallet-enabled') h.context.window.__oeOfferings[0].wallet_connect = 'true';
        if (kind === 'unknown-network') h.nodes.network.value = 'UNLISTED';
        await h.call(); assert.equal(h.pending.length, 0); checks++;
    }
    const h = setup(), p = h.call(); h.pending[0].resolve({ok: false, async json() {return {verified: true, address: verified};}}); await p;
    assert.equal(h.nodes.address.value, initial); assert.equal(h.counts.profiles, 0); checks++;
    const success = setup(), good = success.call(); success.pending[0].resolve({ok: true, async json() {return {verified: true, address: verified};}}); await good;
    assert.equal(success.nodes.address.value, verified); assert.equal(success.nodes.dest_tag.value, ''); assert.equal(success.nodes.no_tag.checked, true);
    assert.equal(success.counts.profiles, 1); checks++;
    console.log(JSON.stringify({result: 'PASS', checks}));
}
main().catch(error => {console.error(error); process.exitCode = 1;});
