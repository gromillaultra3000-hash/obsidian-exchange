'use strict';
// Actual preparation/verification helpers, synthetic late SDK status only.
const assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
const source = fs.readFileSync('relay/webapp.html', 'utf8');
function extract(name) {
    const match = source.match(new RegExp('^        (?:async )?function ' + name + '\\([^]*?^        \\}(?=\\r?$)', 'm'));
    assert.ok(match, name); return match[0];
}
const nodes = {currency: {value: 'TON'}, network: {value: 'MAINNET'}, address: {value: 'EQ' + 'A'.repeat(46)},
    dest_tag: {value: ''}, no_tag: {checked: false}, 'tc-msg': {textContent: ''}, 'tc-connect': {disabled: false}};
let resolveModal; const calls = {modals: 0, closes: 0, verifications: 0};
const ui = {connected: false, setConnectRequestParameters() {},
    openModal() {calls.modals++; return new Promise(resolve => {resolveModal = resolve;});}, closeModal() {calls.closes++;}};
const context = vm.createContext({document: {getElementById: id => nodes[id]}, tg: {initData: ''}, AbortController, setTimeout, clearTimeout,
    window: {TON_CONNECT_UI: {}, __oeOfferings: [{code: 'TON', networks: [{code: 'MAINNET', label: 'TON'}], wallet_connect: true}]},
    validateAddress() {}, updateTagField() {}, loadWallets() {}, ui,
    async fetch(url) {
        if (url === '/api/tonconnect/payload') return {ok: true, async json() {return {payload: 'synthetic-payload'};}};
        assert.equal(url, '/api/tonconnect/verify'); calls.verifications++;
        return {ok: true, async json() {return {verified: true, address: 'EQ' + 'B'.repeat(46)};}};
    }});
vm.runInContext('let tcUI=ui,tcPending=false,tcPreparation=null,tcRecipientGeneration=0;\n' +
    ['buyRouteSignature','currentOffering','tcSay','tcInvalidateRecipient','tcRecipientState','tcAvailable','tcInit','tcHandleWallet','tcConnect'].map(extract).join('\n'), context);
async function main() {
    const opening = vm.runInContext('tcConnect()', context);
    while (!resolveModal) await new Promise(resolve => setImmediate(resolve));
    const newRecipient = 'EQ' + 'C'.repeat(46); nodes.address.value = newRecipient;
    vm.runInContext('tcInvalidateRecipient()', context);
    resolveModal(); await opening;
    assert.equal(calls.closes, 1); assert.equal(vm.runInContext('tcPreparation', context), null);
    context.lateWallet = {account: {address: 'synthetic-old-account'}, connectItems: {tonProof: {proof: {synthetic: true}}}};
    await vm.runInContext('tcHandleWallet(lateWallet)', context);
    assert.equal(calls.verifications, 1); assert.notEqual(nodes.address.value, newRecipient);
    console.log(JSON.stringify({criterion: 'TONCONNECT_CONNECTION_INTENT_LIFETIME',
        closedObsoleteOpening: calls.closes, preparationRetired: true,
        laterCallbackVerificationRequests: calls.verifications, newRecipient,
        finalRecipient: nodes.address.value, lateOldIntentOverwritesRecipient: true,
        realNetworkCalls: 0, walletSignatures: 0, moneyWrites: 0}));
}
main().catch(error => {console.error(error); process.exitCode = 1;});
