'use strict';
const assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
const source = fs.readFileSync(process.argv[2] || 'relay/webapp.html', 'utf8');
function extract(name) {
    const start = source.indexOf('function ' + name + '('), end = source.indexOf('\n        }', start);
    assert.ok(start >= 0 && end > start, name); return source.slice(start, end + 10);
}
const context = vm.createContext({window: {}});
vm.runInContext(extract('validBuyOfferings') + '\n' + extract('buyRouteSignature'), context);
const good = () => [{code: 'TON', networks: [{code: 'MAINNET', label: 'TON'}, {code: 'ALT', label: 'Alternate'}],
    tag_name: 'memo', tag_kind: 'text', tag_sep: '#'}];
let checks = 0;
function validate(value) {context.value = value; return vm.runInContext('validBuyOfferings(value)', context);}
assert.equal(validate(good()), true); checks++;
assert.equal(validate([]), true); checks++;
for (const value of [null, {}, 'TON', [null], [true], [{code: '', networks: []}], [{code: 'TON', networks: null}],
    [{code: 'TON', networks: {}}], [{code: 'TON', networks: [null]}], [{code: 'TON', networks: [{code: ''}]}],
    [{code: 'TON', networks: [{code: 'TON', label: {}}]}], [{code: 'TON', networks: [], tag_name: {}}],
    [{code: 'TON', networks: [], tag_kind: true}], [{code: 'TON', networks: [], tag_sep: []}],
    [...good(), ...good()]]) {
    assert.equal(validate(value), false, JSON.stringify(value)); checks++;
}
const duplicate = good(); duplicate[0].networks.push({...duplicate[0].networks[0]});
assert.equal(validate(duplicate), false); checks++;
context.window.__oeOfferings = good();
const signature = () => vm.runInContext('buyRouteSignature("TON", "ALT")', context);
const initial = signature(); assert.ok(initial); checks++;
context.window.__oeOfferings[0].networks.reverse(); assert.equal(signature(), initial); checks++;
context.window.__oeOfferings[0].networks[0].label = 'Reworded label'; assert.equal(signature(), initial); checks++;
context.window.__oeOfferings[0].tag_sep = ':'; assert.notEqual(signature(), initial); checks++;
assert.equal(vm.runInContext('buyRouteSignature("TON", "")', context), null); checks++;
assert.equal(vm.runInContext('buyRouteSignature("MISSING", "ALT")', context), null); checks++;
context.window.__oeOfferings = [];
assert.equal(signature(), null); checks++;
context.window.__oeOfferings = [{code: 'TON', networks: []}];
assert.equal(vm.runInContext('buyRouteSignature("TON", "")', context), null, 'known empty networks cannot authorize implicit default'); checks++;
console.log(JSON.stringify({result: 'PASS', checks}));
