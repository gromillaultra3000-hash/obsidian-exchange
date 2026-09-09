'use strict';
// Actual preparation helper, deferred in-process payload; no SDK/network/signature.
const assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
const source = fs.readFileSync('relay/webapp.html', 'utf8');
const start = source.indexOf('async function tcConnect('), end = source.indexOf('\n        }', start);
assert.ok(start >= 0 && end > start);
const nodes = {currency: {value: 'TON'}, address: {value: 'original-TON'}, 'tc-connect': {disabled: false}};
let resolveFetch; const calls = [];
const ui = {connected: false, setConnectRequestParameters() {}, async openModal() {calls.push({currency: nodes.currency.value, address: nodes.address.value});}};
const context = vm.createContext({document: {getElementById: id => nodes[id]}, tg: {initData: ''},
    tcAvailable: () => nodes.currency.value === 'TON', tcInit: () => ui, tcSay() {},
    fetch() {return new Promise(resolve => {resolveFetch = resolve;});}});
vm.runInContext(source.slice(start, end + 10), context);
async function main() {
    const pending = vm.runInContext('tcConnect()', context);
    nodes.currency.value = 'BTC'; nodes.address.value = 'new-manual-BTC';
    resolveFetch({ok: true, async json() {return {payload: 'synthetic-payload'};}});
    await pending;
    assert.equal(calls.length, 1); assert.equal(calls[0].currency, 'BTC');
    console.log(JSON.stringify({criterion: 'TONCONNECT_PREPARATION_ROUTE_BINDING',
        stalePreparationOpensModal: true, modalCalls: calls, realNetworkCalls: 0, walletSignatures: 0, moneyWrites: 0}));
}
main().catch(error => {console.error(error); process.exitCode = 1;});
