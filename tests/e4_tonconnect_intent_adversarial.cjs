'use strict';
const assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
const source = fs.readFileSync(process.argv[2] || 'relay/webapp.html', 'utf8');
function extract(name) {
    const match = source.match(new RegExp('^        (?:async )?function ' + name + '\\([^]*?^        \\}(?=\\r?$)', 'm'));
    assert.ok(match, name); return match[0];
}
function setup() {
    const nodes = {currency: {value: 'TON'}, network: {value: 'MAINNET'}, address: {value: 'EQ' + 'A'.repeat(46)}, dest_tag: {value: ''},
        no_tag: {checked: false}, 'tc-msg': {textContent: ''}, 'tc-connect': {disabled: false}};
    const calls = {payloads: [], verifications: [], params: [], modals: 0}; let repeat = false;
    const ui = {connected: false, setConnectRequestParameters(value) {calls.params.push(value);}, async openModal() {calls.modals++;}, closeModal() {}};
    const context = vm.createContext({document: {getElementById: id => nodes[id]}, tg: {initData: ''}, AbortController,
        window: {TON_CONNECT_UI: {}, __oeOfferings: [{code: 'TON', networks: [{code: 'MAINNET', label: 'TON'}], wallet_connect: true}]},
        setTimeout() {return 1;}, clearTimeout() {}, validateAddress() {}, updateTagField() {}, loadWallets() {}, ui,
        fetch(url, options) {
            if (url === '/api/tonconnect/payload') {
                assert.equal(options.cache, 'no-store');
                const payload = repeat ? 'nonce-1' : 'nonce-' + (calls.payloads.length + 1); calls.payloads.push(payload);
                return Promise.resolve({ok: true, async json() {return {payload};}});
            }
            assert.equal(url, '/api/tonconnect/verify');
            return new Promise(resolve => calls.verifications.push({resolve, body: JSON.parse(options.body)}));
        }});
    vm.runInContext('let tcUI=ui,tcPending=false,tcPreparation=null,tcConnectionIntent=null,tcConnectionPayloads=new Set(),tcRecipientGeneration=0;\n' +
        ['buyRouteSignature','currentOffering','tcSay','tcInvalidateRecipient','tcRecipientState','tcAvailable','tcInit','tcHandleWallet','tcConnect'].map(extract).join('\n'), context);
    return {context, nodes, calls, ui, repeat() {repeat = true;}, prepare: () => vm.runInContext('tcConnect()', context),
        callback(payload) {context.wallet = {account: {address: 'synthetic'}, connectItems: {tonProof: {proof: {payload}}}};
            return vm.runInContext('tcHandleWallet(wallet)', context);}};
}
let checks = 0;
async function main() {
    for (const payload of [undefined, null, true, 1, {}, [], '', 'nonce-1 ', ' nonce-1', 'nonce-2']) {
        const h = setup(); await h.prepare(); const before = vm.runInContext('tcConnectionIntent', h.context);
        const generation = vm.runInContext('tcRecipientGeneration', h.context);
        await h.callback(payload); assert.equal(h.calls.verifications.length, 0);
        assert.equal(vm.runInContext('tcConnectionIntent', h.context), before);
        assert.equal(vm.runInContext('tcRecipientGeneration', h.context), generation); checks++;
    }
    {
        const h = setup(); await h.callback('unsolicited'); assert.equal(h.calls.verifications.length, 0); checks++;
    }
    {
        const h = setup(); await h.prepare(); assert.equal(vm.runInContext('tcPreparation', h.context), null);
        assert.equal(vm.runInContext('tcConnectionIntent.payload', h.context), 'nonce-1'); checks++;
        const first = h.callback('nonce-1'); assert.equal(vm.runInContext('tcConnectionIntent', h.context), null);
        await h.callback('nonce-1'); assert.equal(h.calls.verifications.length, 1);
        h.calls.verifications[0].resolve({ok: true, async json() {return {verified: true, address: 'EQ' + 'B'.repeat(46)};}}); await first;
        assert.equal(h.nodes.address.value, 'EQ' + 'B'.repeat(46)); checks++;
    }
    {
        const h = setup(); await h.prepare(); h.repeat(); await h.prepare();
        assert.equal(h.calls.modals, 1); assert.equal(vm.runInContext('tcConnectionIntent', h.context), null);
        await h.callback('nonce-1'); assert.equal(h.calls.verifications.length, 0); checks++;
    }
    {
        const h = setup(); await h.prepare(); h.nodes.address.value = 'changed'; vm.runInContext('tcInvalidateRecipient()', h.context);
        await h.prepare(); const second = vm.runInContext('tcConnectionIntent', h.context);
        await h.callback('nonce-1'); assert.equal(vm.runInContext('tcConnectionIntent', h.context), second); assert.equal(h.calls.verifications.length, 0); checks++;
    }
    {
        const h = setup(); h.ui.openModal = async () => {throw new Error('failed modal');}; await h.prepare();
        assert.equal(vm.runInContext('tcConnectionIntent', h.context), null); await h.callback('nonce-1'); assert.equal(h.calls.verifications.length, 0); checks++;
    }
    for (const edit of ['currency', 'network', 'memo', 'no-tag', 'tag-contract', 'away-back']) {
        const h = setup(); await h.prepare();
        if (edit === 'currency') h.nodes.currency.value = 'BTC';
        if (edit === 'network') h.nodes.network.value = 'OTHER';
        if (edit === 'memo') h.nodes.dest_tag.value = 'new memo';
        if (edit === 'no-tag') h.nodes.no_tag.checked = true;
        if (edit === 'tag-contract') h.context.window.__oeOfferings[0].tag_sep = '#';
        if (edit === 'away-back') {
            const value = h.nodes.address.value; h.nodes.address.value = 'other'; vm.runInContext('tcInvalidateRecipient()', h.context);
            h.nodes.address.value = value; vm.runInContext('tcInvalidateRecipient()', h.context);
        }
        const before = JSON.stringify(h.nodes); await h.callback('nonce-1');
        assert.equal(h.calls.verifications.length, 0, edit); assert.equal(JSON.stringify(h.nodes), before);
        assert.equal(vm.runInContext('tcConnectionIntent', h.context), null); checks++;
    }
    console.log(JSON.stringify({result: 'PASS', checks}));
}
main().catch(error => {console.error(error); process.exitCode = 1;});
