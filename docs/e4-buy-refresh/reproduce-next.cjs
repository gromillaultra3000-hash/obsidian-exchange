'use strict';
// Read-only extraction of the actual asynchronous handler. Synthetic proof and
// response only: fetch is a deferred in-process stub, no SDK/signature/network.
const assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
const source = fs.readFileSync('relay/webapp.html', 'utf8');
const start = source.indexOf('async function tcHandleWallet('), end = source.indexOf('\n        }', start);
assert.ok(start >= 0 && end > start);
const nodes = {currency: {value: 'TON'}, network: {value: 'MAINNET'}, address: {value: 'EQ' + 'A'.repeat(46)}, no_tag: {checked: false}};
let resolveFetch; const requests = [];
const context = vm.createContext({document: {getElementById: id => nodes[id]}, tg: {initData: ''},
    tcSay() {}, validateAddress() {}, updateTagField() {}, loadWallets() {},
    fetch(url, options) {requests.push({url, method: options.method}); return new Promise(resolve => {resolveFetch = resolve;});}});
vm.runInContext('let tcPending = false;\n' + source.slice(start, end + 10), context);
context.wallet = {account: {address: 'synthetic-account'}, connectItems: {tonProof: {proof: {synthetic: true}}}};
async function main() {
    const pending = vm.runInContext('tcHandleWallet(wallet)', context);
    assert.equal(requests.length, 1);
    nodes.currency.value = 'BTC'; nodes.network.value = 'MAINNET';
    const typed = 'bc1' + 'q'.repeat(87); nodes.address.value = typed;
    const lateAddress = 'EQ' + 'B'.repeat(46);
    resolveFetch({ok: true, async json() {return {verified: true, address: lateAddress};}});
    await pending;
    assert.equal(nodes.currency.value, 'BTC'); assert.equal(nodes.address.value, lateAddress);
    console.log(JSON.stringify({criterion: 'TONCONNECT_VERIFY_RESPONSE_RECIPIENT_BINDING',
        initialCurrency: 'TON', currencyAtCompletion: nodes.currency.value, typedRecipientAfterRouteChange: typed,
        lateVerifiedAddress: lateAddress, finalRecipient: nodes.address.value,
        staleResponseOverwritesNewRecipient: nodes.address.value !== typed, mockedVerificationRequests: requests,
        realNetworkCalls: 0, walletSignatures: 0, moneyWrites: 0}));
}
main().catch(error => {console.error(error); process.exitCode = 1;});
