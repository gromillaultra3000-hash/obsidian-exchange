'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const source = fs.readFileSync(input.path, 'utf8');
const elements = new Map(), requests = [], tracking = [], storage = [], haptics = [];
const el = id => {
    if (!elements.has(id)) elements.set(id, {textContent: '', innerHTML: '', style: {}, disabled: false, value: ''});
    return elements.get(id);
};
const extract = name => {
    const matches = [...source.matchAll(new RegExp('^        (?:async )?function '+name+'\\([^]*?^        \\}(?=\\r?$)', 'gm'))];
    assert.equal(matches.length, 1, name); return matches[0][0];
};
const context = vm.createContext({document: {getElementById: el},
    tg: {initData: 'synthetic', HapticFeedback: {notificationOccurred: kind => haptics.push(kind)}},
    localStorage: {setItem: (...args) => storage.push(args)}, setTimeout: () => 1,
    startOrderTracking: (...args) => tracking.push(args), showSellCard: data => tracking.push(data),
    loadSellPending: () => {}, sellCalc: () => {},
    fetch: async (url, options) => {
        requests.push({url, method: options.method, body: JSON.parse(options.body)});
        // The fixture records acceptance before simulating response loss. No
        // production service/database/provider is called by this transport.
        if (input.mode === 'lost-response') throw new TypeError('Failed to fetch');
        return {ok: input.status ? input.status >= 200 && input.status < 300 : true,
            status: input.status || 200, json: async () => {
                if (input.mode === 'truncated-json') throw new SyntaxError('Unexpected end of JSON');
                return input.response;
            }};
    },
});
vm.runInContext(extract(input.action === 'sell' ? 'submitSellOrder' : 'submitBuyOrder'), context);
const parameters = input.action === 'sell'
    ? {cur: 'TON', amt: 2, way: {code: 'sbp'}, phone: '79000000000', bank: 'synthetic', fullName: 'Synthetic User'}
    : {currency: 'TON', amount: 2000, address: 'synthetic', payMethod: 'sbp', destTag: '', noTag: false, network: 'MAINNET'};
context.parameters = parameters;
vm.runInContext((input.action === 'sell' ? 'submitSellOrder' : 'submitBuyOrder')+'(parameters)', context)
    .then(() => {
        const result = el(input.action === 'sell' ? 'sell-result' : 'exchange-result');
        process.stdout.write(JSON.stringify({result, requests, tracking, storage, haptics,
            button: el(input.action === 'sell' ? 'sell-submit' : 'create-order')}));
    }).catch(error => {process.stderr.write(error.stack);process.exitCode = 1;});
