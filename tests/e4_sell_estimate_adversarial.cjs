'use strict';
const assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
const source = fs.readFileSync(process.argv[2] || 'relay/webapp.html', 'utf8');
function extract(name) {
    const start = source.indexOf('function ' + name + '(');
    assert.ok(start >= 0, 'missing ' + name);
    const end = source.indexOf('\n        }', start);
    assert.ok(end > start);
    return source.slice(start, end + 10);
}
const context = vm.createContext({console});
vm.runInContext('let sellEstimateSnapshot = null;\n' + extract('sellSnapshotInfo') + '\n' + extract('sellReviewEstimate'), context);
const now = 1800000000000;
const fresh = () => ({receivedAt: now, options: {BTC: {code: 'BTC', rate: 4550000, market: 5000000,
    fee_percent: 9, min: 0.0001, network: 'MAINNET'}}});
let checks = 0;
function run(snapshot, amount = 0.01, time = now) {
    context.snapshot = snapshot; context.amount = amount; context.time = time;
    return vm.runInContext('sellEstimateSnapshot = snapshot; sellReviewEstimate(amount, "BTC", time)', context);
}
function invalid(name, modify, amount = 0.01, time = now) {
    const snapshot = fresh(); modify(snapshot);
    assert.equal(run(snapshot, amount, time), null, name); checks++;
}
const value = run(fresh()); assert.ok(value); assert.equal(value.fee, 9);
assert.match(value.payoutText.replace(/\s/g, ''), /45500/); checks++;
for (const rate of [0, -1, null, '4550000', true, {}, NaN, Infinity, -Infinity, Number.MIN_VALUE, Number.MAX_VALUE])
    invalid('invalid rate ' + String(rate), s => {s.options.BTC.rate = rate;});
for (const fee of [-1, 100, NaN, Infinity, null, '9', true, {}])
    invalid('invalid fee ' + String(fee), s => {s.options.BTC.fee_percent = fee;});
for (const fee of [0, 99]) {const s = fresh(); s.options.BTC.fee_percent = fee; assert.equal(run(s).fee, fee); checks++;}
invalid('missing currency', s => {delete s.options.BTC;});
invalid('missing fee', s => {delete s.options.BTC.fee_percent;});
invalid('expired snapshot', s => {s.receivedAt -= 60000;});
invalid('clock rollback', s => {s.receivedAt += 1;});
invalid('string receipt', s => {s.receivedAt = String(s.receivedAt);});
for (const amount of [0, -1, NaN, Infinity, '0.01', null, Number.MIN_VALUE, Number.MAX_VALUE])
    invalid('invalid amount ' + String(amount), () => {}, amount);
for (const market of [0, null, undefined]) {
    const s = fresh(); s.options.BTC.market = market; assert.ok(run(s), 'market absent does not replace authoritative net rate'); checks++;
}
console.log(JSON.stringify({result: 'PASS', checks}));
