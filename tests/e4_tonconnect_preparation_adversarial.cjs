'use strict';
const assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
const source = fs.readFileSync(process.argv[2] || 'relay/webapp.html', 'utf8');
function extract(name) {
    const match = source.match(new RegExp('^        (?:async )?function ' + name + '\\([^]*?^        \\}(?=\\r?$)', 'm'));
    assert.ok(match, name); return match[0];
}
function setup() {
    const nodes = {currency: {value: 'TON'}, network: {value: 'MAINNET'}, address: {value: 'EQ' + 'A'.repeat(46)}, dest_tag: {value: ''},
        no_tag: {checked: false}, 'tc-msg': {textContent: '', className: ''}, 'tc-connect': {disabled: false}};
    const pending = [], timers = [], calls = {params: [], modals: 0};
    const ui = {connected: false, setConnectRequestParameters(value) {calls.params.push(value);}, async openModal() {calls.modals++;}};
    const context = vm.createContext({document: {getElementById: id => nodes[id]}, tg: {initData: ''}, AbortController,
        window: {TON_CONNECT_UI: {}, __oeOfferings: [{code: 'TON', networks: [{code: 'MAINNET', label: 'TON'}], wallet_connect: true}]},
        validateAddress() {}, updateTagField() {}, loadWallets() {},
        setTimeout(fn) {timers.push(fn); return timers.length;}, clearTimeout() {},
        fetch(url, options) {assert.equal(url, '/api/tonconnect/payload');
            return new Promise((resolve, reject) => pending.push({resolve, reject, signal: options.signal}));}, ui});
    vm.runInContext('let tcUI=ui,tcPending=false,tcPreparation=null,tcRecipientGeneration=0,tcConnectionIntent=null; const tcConnectionPayloads=new Set();\n' +
        ['buyRouteSignature','currentOffering','tcSay','tcInvalidateRecipient','tcRecipientState','tcAvailable','tcInit','tcHandleWallet','tcConnect'].map(extract).join('\n'), context);
    ui.disconnect = async () => {await vm.runInContext('tcHandleWallet(null)', context); ui.connected = false;};
    return {nodes, pending, timers, calls, ui, context, call: () => vm.runInContext('tcConnect()', context)};
}
let checks = 0;
const deliver = (h, payload, ok = true) => h.pending[0].resolve({ok, async json() {return {payload};}});
async function main() {
    for (const payload of [undefined, null, {}, [], '', ' ', 'x'.repeat(4097), 1, false]) {
        const h = setup(), p = h.call(); deliver(h, payload); await p;
        assert.equal(h.calls.modals, 0); assert.equal(h.calls.params.at(-1), null); assert.equal(h.nodes['tc-connect'].disabled, false); checks++;
    }
    for (const mode of ['success', 'unchanged-refresh', 'own-disconnect', 'disconnect-remains-connected', 'disconnect-reject', 'bad-http', 'late-after-abort', 'duplicate', 'pending-verification', 'stale-error']) {
        const h = setup();
        if (mode === 'pending-verification') vm.runInContext('tcPending=true', h.context);
        if (mode.startsWith('disconnect') || mode === 'own-disconnect') h.ui.connected = true;
        if (mode === 'disconnect-remains-connected') h.ui.disconnect = async () => {};
        if (mode === 'disconnect-reject') h.ui.disconnect = async () => {throw new Error('disconnect rejected');};
        const p = h.call();
        if (mode === 'pending-verification') {await p; assert.equal(h.pending.length, 0); checks++; continue;}
        if (mode === 'duplicate') {await h.call(); assert.equal(h.pending.length, 1);}
        if (mode === 'unchanged-refresh') h.context.window.__oeOfferings = JSON.parse(JSON.stringify(h.context.window.__oeOfferings));
        if (mode === 'late-after-abort') {h.timers[0](); assert.equal(h.pending[0].signal.aborted, true);}
        if (mode === 'stale-error') {
            h.nodes.address.value = 'new'; vm.runInContext('tcInvalidateRecipient()', h.context);
            const message = h.nodes['tc-msg'].textContent; h.pending[0].reject(new Error('synthetic failure')); await p;
            assert.equal(h.nodes['tc-msg'].textContent, message); assert.equal(h.calls.modals, 0); checks++; continue;
        }
        deliver(h, 'synthetic-payload', mode !== 'bad-http'); await p;
        const succeeded = ['success', 'unchanged-refresh', 'own-disconnect', 'duplicate'].includes(mode);
        assert.equal(h.calls.modals, succeeded ? 1 : 0, mode);
        if (!succeeded) assert.equal(h.calls.params.at(-1), null);
        else assert.equal(h.calls.params.at(-1).state, 'ready');
        assert.equal(vm.runInContext('tcPreparation', h.context), null); checks++;
    }
    console.log(JSON.stringify({result: 'PASS', checks}));
}
main().catch(error => {console.error(error); process.exitCode = 1;});
