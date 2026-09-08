'use strict';

// Synthetic acknowledgement/response boundaries only: successful delivery to
// the stub does not represent any production persistence or payment outcome.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const crypto = require('node:crypto');
const ROOT = path.resolve(__dirname, '../..');
const sourcePath = path.resolve(process.argv[2] || path.join(ROOT, 'relay/webapp.html'));
const utilityPath = path.join(ROOT, 'tests/e4_recipient_review_behavior.cjs');
const utility = fs.readFileSync(utilityPath, 'utf8');
const end = utility.indexOf('\nconst scenarios = {');
assert.ok(end > 0);
const context = {require, process: {argv: ['node', utilityPath, sourcePath]}, console};
vm.runInNewContext(utility.slice(0, end) + '\nglobalThis.securityHarness = harness;', context,
    {filename: utilityPath, timeout: 1000});
const sha = file => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const report = {
    schemaVersion: 'e4-money-order-outcome-independent-security-probe.v1',
    source: {path: path.relative(ROOT, sourcePath), sha256: sha(sourcePath)},
    inputs: [__filename, utilityPath].map(file => ({path: path.relative(ROOT, file), sha256: sha(file)})),
    scenarioBoundary: 'The request stub records accepted delivery, then rejects transport or body decoding. No backend, database, customer, provider or real money outcome is inferred.',
    productionNetworkDatabaseWalletCalls: 0,
    cases: [],
};

async function main() {
    for (const action of ['buy', 'sell']) {
        for (const failure of ['transport-after-accepted-request', 'unreadable-response', 'null-response', 'gateway-error']) {
            const h = context.securityHarness();
            h.context.fetch = async (url, options) => {
                h.requests.push({url, method: options.method, body: JSON.parse(options.body), syntheticRequestAccepted: true});
                if (failure === 'transport-after-accepted-request') throw new TypeError('Synthetic response lost');
                if (failure === 'unreadable-response') return {ok: true, status: 200, json: async () => {throw new SyntaxError('Synthetic truncated body');}};
                if (failure === 'null-response') return {ok: true, status: 200, json: async () => null};
                return {ok: false, status: 502, json: async () => ({detail: 'Synthetic upstream connection lost'})};
            };
            if (action === 'buy') h.context.beginBuyOrder(); else await h.context.createSellOrder();
            assert.equal(h.requests.length, 0, 'opening review cannot submit');
            await h.confirm();
            const el = h.el(action === 'buy' ? 'exchange-result' : 'sell-result');
            const text = el.textContent || el.innerHTML;
            const failures = [];
            const check = (condition, message) => {if (!condition) failures.push(message);};
            check(h.requests.length === 1, 'one acknowledged operation must produce one request without automatic retry');
            check(!/заявка не создана|Заявку создать не удалось/.test(text), 'uncertain response is incorrectly presented as definitive noncreation');
            check(/провер|уточн|подтвержд|неизвест|не удалось получить|не удалось узнать/i.test(text), 'response lacks explicit uncertainty/check-existing-status guidance');
            check(!/попробуйте ещё раз|попробуйте позже/i.test(text), 'response suggests retrying before determining whether an order already exists');
            check(h.storageWrites.length === 0, 'uncertain response must not persist success destination');
            report.cases.push({name: action + ':' + failure, result: failures.length ? 'FAIL' : 'PASS',
                visibleText: text, requests: h.requests.length, failures});
        }
        for (const mode of ['explicit-rejection-remains-literal', 'confirmed-result-once']) {
            const h = context.securityHarness();
            const handedOff = [];
            const result = h.el(action === 'buy' ? 'exchange-result' : 'sell-result');
            const assignments = [];
            Object.defineProperty(result, 'innerHTML', {get: () => assignments.at(-1) || '',
                set: value => assignments.push(String(value))});
            const hostile = '<img src=x onerror="synthetic()"> Параметры отклонены';
            h.context.startOrderTracking = (...values) => handedOff.push(values);
            h.context.showSellCard = value => handedOff.push(value);
            h.context.loadSellPending = () => {};
            h.context.sellCalc = () => {};
            h.context.fetch = async (url, options) => {
                h.requests.push({url, method: options.method, body: JSON.parse(options.body)});
                return mode === 'explicit-rejection-remains-literal'
                    ? {ok: false, status: 400, json: async () => ({ok: false, error: hostile, detail: hostile})}
                    : {ok: true, status: 200, json: async () => ({ok: true, order_id: 42, sell_id: 42, payment_url: '/synthetic-payment'})};
            };
            if (action === 'buy') h.context.beginBuyOrder(); else await h.context.createSellOrder();
            await h.confirm();
            await h.el('exchange-review-confirm').fire('click');
            const failures = [];
            if (h.requests.length !== 1) failures.push('one acknowledgement caused more than one request');
            if (mode === 'explicit-rejection-remains-literal') {
                if (!result.textContent.includes(hostile)) failures.push('explicit rejection reason is not rendered as literal text');
                if (assignments.some(value => value.includes('<img'))) failures.push('server rejection text reaches an HTML sink');
                if (handedOff.length || h.storageWrites.length) failures.push('rejected response performed success effects');
            } else {
                if (handedOff.length !== 1) failures.push('confirmed response must keep exactly one success handoff');
                if (h.storageWrites.length !== (action === 'buy' ? 1 : 0)) failures.push('success destination storage behavior changed');
            }
            report.cases.push({name: action + ':' + mode, result: failures.length ? 'FAIL' : 'PASS',
                requests: h.requests.length, successHandoffs: handedOff.length, storageWrites: h.storageWrites.length, failures});
        }
    }
    report.passed = report.cases.filter(c => c.result === 'PASS').length;
    report.failed = report.cases.length - report.passed;
    report.result = report.failed ? 'REPRODUCED_FINDINGS' : 'PASS';
    process.stdout.write(JSON.stringify(report, null, 2) + '\n');
}
main().catch(error => {console.error(error.stack); process.exitCode = 1;});
