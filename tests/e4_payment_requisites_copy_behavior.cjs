'use strict';
// Execute shipped tracking/copy listeners. DOM, clipboard, timers and GETs are
// synthetic; this harness cannot contact a provider or create a transaction.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const [sourcePath, scenario] = process.argv.slice(2);
const source = fs.readFileSync(sourcePath, 'utf8');
const elements = new Map();
const decode = value => value.replace(/&quot;/g, '"').replace(/&#39;/g, "'")
    .replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&');
function element(id) {
    let contents = '';
    const children = [];
    const listeners = {};
    const node = {id, style: {}, disabled: false, isConnected: true, attributes: {},
        get textContent() {return contents;},
        set textContent(value) {clear(); contents = value;},
        get innerHTML() {return contents;},
        set innerHTML(value) {
            clear(); contents = value;
            for (const match of value.matchAll(/<([a-z]+)\b([^>]*\bid="([^"]+)"[^>]*)>([^]*?)<\/\1>/g)) {
                const child = element(match[3]);
                child.textContent = decode(match[4].replace(/<[^>]+>/g, ''));
                for (const attr of match[2].matchAll(/([\w-]+)="([^"]*)"/g)) child.attributes[attr[1]] = decode(attr[2]);
                elements.set(child.id, child); children.push(child);
            }
        },
        addEventListener(type, listener) {listeners[type] = listener;},
        fire() {return listeners.click?.call(node);},
        removeAttribute(name) {delete this[name]; delete this.attributes[name];},
        getAttribute(name) {return this.attributes[name] ?? null;},
        setAttribute(name, value) {this.attributes[name] = String(value);},
    };
    function clear() {
        for (const child of children.splice(0)) {
            child.isConnected = false;
            if (elements.get(child.id) === child) elements.delete(child.id);
        }
    }
    return node;
}
for (const id of ['pay-card', 'pay-card-title', 'pay-card-status', 'pay-timer',
    'pay-open-btn', 'pay-check-btn', 'exchange-steps', 'pay-qr-wrap', 'pay-qr',
    'pay-amount-line', 'pay-req']) elements.set(id, element(id));
const el = id => elements.get(id);
const pending = [], writes = [], haptics = [], requests = [], intervals = new Map();
let timer = 0;
let clipboardContents = 'previous clipboard value';
const clipboard = {writeText(value) {
    writes.push(value);
    let task;
    const promise = new Promise((resolve, reject) => {
        task = {resolve: () => {clipboardContents = value; resolve();}, reject};
    });
    pending.push({...task, promise}); return promise;
}};
const ctx = vm.createContext({document: {getElementById: el}, navigator: {clipboard},
    tg: {initData: '', HapticFeedback: {impactOccurred: kind => haptics.push(kind), notificationOccurred() {}}},
    window: {location: {}}, loadHistory() {}, AbortController,
    setTimeout: () => ++timer, clearTimeout() {},
    setInterval: (fn, delay) => {intervals.set(++timer, {fn, delay}); return timer;},
    clearInterval: id => intervals.delete(id),
    fetch: (url, options) => new Promise((resolve, reject) => requests.push({url, options, resolve, reject})),
});
const begin = source.indexOf('        let _orderPoll =');
const end = source.indexOf('        let historyOrders =', begin);
assert.ok(begin > 0 && end > begin);
vm.runInContext(source.slice(begin, end), ctx);
const value = '+7 000 000-00-01';
function start(id = 'synthetic-a', detail = value, kind = 'phone') {
    ctx.startOrderTracking(id, 'https://payment.invalid/' + id, 'TON', null, 2000,
        detail === null ? null : {[kind]: detail, bank_name: 'Synthetic bank', recipient: 'Synthetic recipient'});
}
const flush = async () => {for (let n = 0; n < 8; n++) await Promise.resolve();};
const finish = async (index, ok = true) => {
    pending[index][ok ? 'resolve' : 'reject'](ok ? undefined : new Error('private diagnostic'));
    await flush();
};
const reply = async (index, body) => {
    requests[index].resolve({ok: true, json: async () => body}); await flush();
};
const button = () => el('pay-req-copy');
const feedback = () => el('pay-req-copy-status');
function preserved(expected = value) {
    assert.equal(el('pay-req-value').textContent, expected);
    assert.equal(button().textContent, 'Копировать');
    assert.ok(el('pay-req').innerHTML.includes('Synthetic bank'));
    assert.ok(el('pay-req').innerHTML.includes('Synthetic recipient'));
}
async function main() {
    start();
    if (scenario === 'baseline_observed') {
        const observations = [];
        for (const reject of [false, true]) {
            start();
            const inline = decode(el('pay-req').innerHTML.match(/<button onclick="([^"]*)"/)[1]);
            const target = {textContent: '📋'};
            const index = pending.length;
            vm.runInContext('(function () {' + inline + '})', ctx).call(target);
            // Legacy handler drops the promise; attach a harness rejection
            // observer so the factual probe does not crash on unhandled rejection.
            pending[index].promise.catch(() => {});
            assert.equal(target.textContent, '✓');
            observations.push({case: reject ? 'rejected' : 'pending', prematureSuccess: true});
            if (reject) pending[index].reject(new Error('synthetic clipboard rejection'));
            else pending[index].resolve();
            await flush(); assert.equal(target.textContent, '✓');
        }
        start('synthetic-quotes', "O'Brien 42");
        const inline = decode(el('pay-req').innerHTML.match(/<button onclick="([^"]*)"/)[1]);
        assert.throws(() => vm.runInContext('(function () {' + inline + '})', ctx), /Unexpected identifier|missing \)/);
        observations.push({case: 'literal_apostrophe', handlerSyntaxError: true});
        return {scenario, result: 'BASELINE_DEFECT_REPRODUCED', observations};
    }
    assert.ok(button(), 'payment copy must have a stable accessible button');
    assert.ok(feedback(), 'copy feedback must be separate from payment requisites');
    if (scenario === 'pending_success') {
        button().fire(); preserved();
        assert.equal(feedback().textContent, 'Копируем…'); assert.equal(button().disabled, true);
        assert.deepEqual(haptics, []);
        await finish(0);
        assert.equal(feedback().textContent, '✓ Реквизиты скопированы');
        assert.equal(button().disabled, false); preserved();
        assert.deepEqual(writes, [value]);
    } else if (scenario === 'duplicate') {
        button().fire(); button().fire(); button().fire();
        assert.deepEqual(writes, [value]);
        await finish(0); button().fire(); await finish(1);
        assert.deepEqual(writes, [value, value]); preserved();
    } else if (['reject_retry', 'unavailable', 'throw'].includes(scenario)) {
        if (scenario === 'unavailable') ctx.navigator.clipboard = undefined;
        if (scenario === 'throw') clipboard.writeText = () => {throw new Error('private diagnostic');};
        button().fire();
        if (scenario === 'reject_retry') await finish(0, false); else await flush();
        assert.match(feedback().textContent, /Не удалось скопировать/);
        assert.match(feedback().textContent, /вручную/);
        assert.ok(!feedback().textContent.includes('private diagnostic'));
        assert.deepEqual(haptics, []); assert.equal(button().disabled, false); preserved();
        if (scenario === 'reject_retry') {
            button().fire(); await finish(1);
            assert.equal(feedback().textContent, '✓ Реквизиты скопированы'); preserved();
        }
    } else if (scenario === 'accessible') {
        assert.equal(button().getAttribute('type'), 'button');
        assert.equal(button().getAttribute('aria-describedby'), 'pay-req-copy-status');
        assert.equal(feedback().getAttribute('role'), 'status');
        assert.equal(feedback().getAttribute('aria-live'), 'polite');
        assert.equal(feedback().getAttribute('aria-atomic'), 'true');
        assert.equal(button().getAttribute('onclick'), null);
    } else if (scenario === 'literal_phone' || scenario === 'literal_card') {
        const literal = ' O\'Brien "double" `tick` ${literal} <script>window.__bad = 1</script> & 42 ';
        start('synthetic-literal', literal, scenario === 'literal_phone' ? 'phone' : 'card_number');
        preserved(literal); button().fire(); await finish(0);
        assert.deepEqual(writes, [literal]); preserved(literal);
        assert.equal(button().getAttribute('onclick'), null);
        assert.ok(!el('pay-req').innerHTML.includes('<script>'));
    } else if (scenario.startsWith('cross_order_')) {
        const oldButton = button(); oldButton.fire();
        start(scenario === 'cross_order_same_id' ? 'synthetic-a' : 'synthetic-b', 'value-B');
        assert.equal(button().disabled, true, 'new view must wait for the previous native write');
        assert.equal(feedback().textContent, 'Завершается предыдущее копирование…');
        button().fire(); oldButton.fire();
        assert.deepEqual(writes, [value], 'only one native clipboard operation may be in flight');
        await finish(0, scenario !== 'cross_order_reject');
        assert.equal(clipboardContents, scenario === 'cross_order_reject' ? 'previous clipboard value' : value);
        assert.equal(button().disabled, false); assert.equal(feedback().textContent, ''); preserved('value-B');
        assert.equal(writes.length, 1, 'settling old write must not auto-copy without a fresh user action');
        button().fire(); assert.equal(feedback().textContent, 'Копируем…');
        await finish(1); oldButton.fire();
        assert.deepEqual(writes, [value, 'value-B']); assert.equal(clipboardContents, 'value-B');
        assert.equal(feedback().textContent, '✓ Реквизиты скопированы'); preserved('value-B');
    } else if (['waiting_reset', 'waiting_terminal', 'waiting_newer'].includes(scenario)) {
        button().fire(); start('synthetic-b', 'value-B');
        const waitingButton = button(), waitingStatus = feedback();
        assert.equal(waitingButton.disabled, true);
        if (scenario === 'waiting_terminal') await reply(1, {status: 'paid'});
        else start('synthetic-c', scenario === 'waiting_reset' ? null : 'value-C');
        const waitingFeedback = waitingStatus.textContent;
        await finish(0); waitingButton.fire();
        assert.equal(writes.length, 1); assert.equal(waitingButton.disabled, true);
        assert.equal(waitingStatus.textContent, waitingFeedback, 'settlement must not revive an invalidated waiting view');
        if (scenario === 'waiting_newer') {
            assert.equal(button().disabled, false); assert.equal(feedback().textContent, '');
            button().fire(); await finish(1); assert.equal(clipboardContents, 'value-C'); preserved('value-C');
        } else {assert.equal(el('pay-req').textContent, ''); assert.equal(button(), undefined);}
    } else if (['new_order', 'same_id', 'empty_reset'].includes(scenario)) {
        const oldButton = button(), oldStatus = feedback(); oldButton.fire();
        start(scenario === 'same_id' ? 'synthetic-a' : 'synthetic-b', scenario === 'empty_reset' ? null : 'new detail');
        const before = el('pay-req').innerHTML;
        oldButton.fire(); assert.equal(writes.length, 1, 'detached old handler must be inert');
        await finish(0, scenario !== 'same_id');
        assert.equal(el('pay-req').innerHTML, before);
        if (scenario !== 'empty_reset') {assert.equal(feedback().textContent, ''); preserved('new detail');}
        assert.equal(oldStatus.textContent, 'Копируем…', 'stale completion must not update old feedback');
        assert.deepEqual(haptics, []);
    } else if (scenario.startsWith('terminal_')) {
        const status = scenario.slice('terminal_'.length);
        const oldButton = button(), oldStatus = feedback(); oldButton.fire();
        if (status === 'timer') {
            const tick = [...intervals.values()].find(item => item.delay === 1000).fn;
            for (let i = 0; i < 900; i++) tick();
        } else await reply(0, {status: ['receipt', 'dead'].includes(status) ? 'pending' : status,
            receipt: status === 'receipt' ? 'sent' : '', dead: status === 'dead'});
        assert.equal(el('pay-req').textContent, ''); assert.equal(el('pay-req').style.display, 'none');
        const hiddenFeedback = oldStatus.textContent;
        oldButton.fire(); assert.equal(writes.length, 1);
        await finish(0);
        assert.equal(el('pay-req').textContent, '');
        assert.equal(oldStatus.textContent, hiddenFeedback); assert.deepEqual(haptics, []);
    } else if (scenario === 'detached_same_ids') {
        const oldButton = button(), oldStatus = feedback(); oldButton.fire();
        const markup = el('pay-req').innerHTML; el('pay-req').innerHTML = markup;
        await finish(0); oldButton.fire();
        assert.equal(feedback().textContent, ''); assert.equal(oldStatus.textContent, 'Копируем…');
        assert.equal(writes.length, 1); assert.deepEqual(haptics, []);
    } else throw new Error('unknown scenario');
    return {scenario, result: 'PASS'};
}
main().then(result => console.log(JSON.stringify(result)))
    .catch(error => {console.error(error.stack); process.exitCode = 1;});
