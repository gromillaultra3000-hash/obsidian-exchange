'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs'), vm = require('node:vm');
const source = fs.readFileSync(process.argv[2] || 'relay/webapp.html', 'utf8');
const start = source.indexOf('let cachedRates = {}');
const end = source.indexOf('async function loadRates()', start);
assert.ok(start >= 0 && end > start);
const context = vm.createContext({console});
vm.runInContext(source.slice(start, end), context);
const now = 1800000000000;
const fresh = () => ({receivedAt: now, data: {ts: now / 1000, BTC: 5000000,
    commission_tiers: [{to_rub: 5000, percent: 27}, {to_rub: 10000, percent: 25},
        {to_rub: 20000, percent: 23}, {to_rub: null, percent: 19}]}});
let checks = 0;
function run(snapshot, amount = 12500, time = now) {
    context.snapshot = snapshot; context.amount = amount; context.time = time;
    return vm.runInContext('buyRateSnapshot = snapshot; buyReviewEstimate(amount, "BTC", time)', context);
}
function invalid(name, modify, amount = 12500, time = now) {
    const snapshot = fresh(); modify(snapshot);
    assert.equal(run(snapshot, amount, time), null, name); checks++;
}
let result = run(fresh());
assert.ok(result); assert.equal(result.fee, 23); assert.match(result.receiveText, /0[.,]001925/); checks++;
for (const [amount, fee] of [[4999, 27], [5000, 25], [9999, 25], [10000, 23], [20000, 19]]) {
    assert.equal(run(fresh(), amount).fee, fee); checks++;
}
for (const value of [0, -1, NaN, Infinity, -Infinity, null, '5000000', {}, true, Number.MIN_VALUE, Number.MAX_VALUE])
    invalid('invalid rate ' + String(value), s => {s.data.BTC = value;});
for (const value of [-1, 100, 101, NaN, Infinity, null, '23', {}, true])
    invalid('invalid fee ' + String(value), s => {s.data.commission_tiers[2].percent = value;});
for (const value of [null, [], {}, [null], [{to_rub: null, percent: 23}, {to_rub: null, percent: 23}],
    [{to_rub: 10000, percent: 23}], [{to_rub: 10000, percent: 23}, {to_rub: 5000, percent: 25}, {to_rub: null, percent: 19}],
    [{to_rub: '20000', percent: 23}, {to_rub: null, percent: 19}]])
    invalid('invalid tiers ' + JSON.stringify(value), s => {s.data.commission_tiers = value;});
invalid('missing tiers', s => {delete s.data.commission_tiers;});
invalid('missing currency', s => {delete s.data.BTC;});
invalid('receipt expired', s => {s.receivedAt -= 60000;});
invalid('receipt future', s => {s.receivedAt += 1;});
invalid('response expired', s => {s.data.ts -= 120;});
invalid('response future', s => {s.data.ts += 1;});
invalid('string timestamp', s => {s.data.ts = String(s.data.ts);});
invalid('no timestamp', s => {delete s.data.ts;});
for (const amount of [0, -1, NaN, Infinity, '12500', null, Number.MAX_VALUE])
    invalid('invalid amount ' + String(amount), () => {}, amount);
async function asyncChecks() {
    const loadEnd = source.indexOf('\n        loadRates();', end);
    const pending = [];
    const timers = [];
    let accepted = 0;
    Object.assign(context, {
        AbortController, Date, window: {},
        setTimeout(fn) {timers.push(fn); return timers.length;}, clearTimeout() {},
        applyOfferings() {}, renderFeeFaq() {}, calculateFee() {accepted++;},
        fetch(url, options) {assert.equal(options.cache, 'no-store'); assert.ok(options.signal);
            return new Promise((resolve, reject) => pending.push({resolve, reject, options}));},
    });
    vm.runInContext(source.slice(end, loadEnd), context);
    const invoke = () => vm.runInContext('loadRates()', context);
    const deliver = (index, data, ok = true) => pending[index].resolve({ok, async json() {return data;}});
    const read = () => vm.runInContext('buyRateSnapshot', context);
    let first = invoke(), second = invoke();
    deliver(1, {...fresh().data, BTC: 10}); await second;
    deliver(0, {...fresh().data, BTC: 20}); await first;
    assert.equal(read().data.BTC, 10); assert.equal(accepted, 1); checks++;
    first = invoke(); second = invoke();
    deliver(3, {...fresh().data, BTC: 30}); await second;
    pending[2].reject(new Error('old failure')); await first;
    assert.equal(read().data.BTC, 30); checks++;
    first = invoke(); deliver(4, fresh().data, false); await first;
    assert.equal(read(), null); checks++;
    first = invoke(); deliver(5, []); await first;
    assert.equal(read(), null); checks++;
    first = invoke(); deliver(6, fresh().data); await first;
    assert.ok(read());
    first = invoke(); pending[7].reject(new Error('latest failure')); await first;
    assert.equal(read(), null); checks++;
    first = invoke();
    timers.at(-1)(); assert.equal(pending[8].options.signal.aborted, true);
    pending[8].reject(new Error('aborted')); await first;
    assert.equal(read(), null); checks++;
    console.log(JSON.stringify({result: 'PASS', checks}));
}
asyncChecks().catch(e => {console.error(e); process.exitCode = 1;});
