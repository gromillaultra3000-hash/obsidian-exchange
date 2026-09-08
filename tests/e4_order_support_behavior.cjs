'use strict';
// Exact shipped helpers, synthetic clipboard and connected/detached order cards.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const [sourcePath, scenario] = process.argv.slice(2);
const source = fs.readFileSync(sourcePath, 'utf8');
const cards = new Set(), pending = [], writes = [], openings = [];
let clipboardValue = '', legacyCalls = 0;
const list = {contains: b => cards.has(b), querySelectorAll: () =>
    [...cards].map(b => b.parentElement.querySelector()).filter(s => s.dataset.copyWaiting)};
function card() {
    const status = {textContent: 'initial', isConnected: true, dataset: {}};
    const button = {textContent: 'Копировать №', disabled: false,
        parentElement: {querySelector: () => status}};
    cards.add(button);
    return {button, status};
}
const a = card(), b = card();
const ctx = vm.createContext({
    navigator: {clipboard: {writeText(value) {
        writes.push(value);
        return new Promise((resolve, reject) => pending.push({resolve() {
            clipboardValue = value; resolve();
        }, reject}));
    }}},
    window: {isSecureContext: true, open: (...args) => openings.push(args)},
    document: {getElementById: () => list, execCommand() {legacyCalls++; throw Error('legacy forbidden');}},
    tg: {openTelegramLink: (...args) => openings.push(args)},
});
const start = source.includes('let orderIdCopyPending') ? source.indexOf('let orderIdCopyPending')
    : source.indexOf('async function copyOrderId');
vm.runInContext(source.slice(start, source.indexOf('function renderHistoryOrders', start)), ctx);
const openStart = source.indexOf('function openSupport()');
vm.runInContext(source.slice(openStart, source.indexOf('function openBotSwap()', openStart)), ctx);
const copy = (c = a, id = 'synthetic-A') => ctx.copyOrderId(id, c.button);
const support = () => {
    const before = openings.length, writeCount = writes.length;
    ctx.openOrderSupport('do-not-send', {disabled: false});
    assert.equal(openings.length, before + 1, 'support must open synchronously');
    assert.equal(openings.at(-1)[0], 'https://t.me/ObsidianSupBot');
    assert.equal(writes.length, writeCount, 'support must not copy automatically');
};
async function main() {
    switch (scenario) {
    case 'support_stalled': {
        const p = copy();
        support(); support();
        assert.equal(a.button.disabled, true);
        assert.match(a.status.textContent, /Копируем/);
        pending[0].resolve(); await p;
        assert.match(a.status.textContent, /Номер скопирован/);
        support(); break;
    }
    case 'support_only':
        ctx.navigator.clipboard = {get writeText() {throw Error('must not access');}};
        support(); support(); assert.equal(writes.length, 0); break;
    case 'support_browser':
        delete ctx.tg.openTelegramLink; support();
        assert.deepEqual(openings[0], ['https://t.me/ObsidianSupBot', '_blank', 'noopener']); break;
    case 'rejection': {
        const p = copy(); support(); pending[0].reject(Error('private error'));
        assert.equal(await p, false); assert.match(a.status.textContent, /Не удалось/);
        assert.equal(a.button.disabled, false); assert.equal(legacyCalls, 0);
        support(); const retry = copy(); pending[1].resolve(); assert.equal(await retry, true); break;
    }
    case 'unavailable': case 'insecure': case 'throw': case 'getter_throw': case 'malformed': {
        if (scenario === 'unavailable') delete ctx.navigator.clipboard;
        if (scenario === 'insecure') ctx.window.isSecureContext = false;
        if (scenario === 'throw') ctx.navigator.clipboard.writeText = () => {throw Error('private error');};
        if (scenario === 'getter_throw') Object.defineProperty(ctx.navigator, 'clipboard', {get() {throw Error('private error');}});
        if (scenario === 'malformed') ctx.navigator.clipboard = {writeText: 'unavailable'};
        assert.equal(await copy(), false); assert.match(a.status.textContent, /Не удалось/);
        assert.equal(a.button.disabled, false); assert.equal(legacyCalls, 0); support(); break;
    }
    case 'haptic_throw': {
        ctx.tg.HapticFeedback = {notificationOccurred() {throw Error('haptic failed');}};
        const p = copy(); pending[0].resolve(); assert.equal(await p, true);
        assert.match(a.status.textContent, /Номер скопирован/);
        assert.equal(writes.length, 1); support(); break;
    }
    case 'literal': {
        const literal = 'synthetic-\' " & <tag> ` ${literal}';
        const p = copy(a, literal); assert.equal(writes[0], literal);
        assert.doesNotMatch(a.status.textContent, /Номер скопирован/);
        pending[0].resolve(); assert.equal(await p, true); assert.equal(clipboardValue, literal);
        assert.equal(a.button.textContent, 'Копировать №'); break;
    }
    case 'duplicate': {
        const p = copy(); assert.equal(await copy(), false); assert.equal(writes.length, 1);
        pending[0].resolve(); await p; break;
    }
    case 'cross_order_success': case 'cross_order_rejection': {
        const p = copy(); assert.equal(await copy(b, 'synthetic-B'), false);
        assert.equal(writes.length, 1); assert.match(b.status.textContent, /Предыдущее/);
        support();
        if (scenario.endsWith('rejection')) pending[0].reject(Error('denied')); else pending[0].resolve();
        await p; assert.equal(writes.length, 1, 'no automatic queue');
        assert.match(b.status.textContent, /Теперь можно/);
        assert.equal(b.status.dataset.copyWaiting, undefined);
        const q = copy(b, 'synthetic-B'); pending[1].resolve(); await q;
        assert.equal(clipboardValue, 'synthetic-B'); break;
    }
    case 'stale_success': case 'stale_rejection': {
        const p = copy(); cards.delete(a.button); a.status.isConnected = false;
        const before = a.status.textContent;
        assert.equal(await copy(b, 'synthetic-B'), false);
        if (scenario.endsWith('rejection')) pending[0].reject(Error('denied')); else pending[0].resolve();
        await p; assert.equal(a.status.textContent, before);
        assert.doesNotMatch(b.status.textContent, /Номер скопирован/);
        assert.equal(await copy(a), false);
        const q = copy(b, 'synthetic-B'); pending[1].resolve(); await q;
        assert.match(b.status.textContent, /Номер скопирован/); break;
    }
    case 'detached':
        cards.delete(a.button); a.button.parentElement = null;
        assert.equal(await copy(), false); assert.equal(writes.length, 0); break;
    case 'empty':
        assert.equal(await copy(a, ''), false); assert.equal(writes.length, 0); support(); break;
    default: throw Error('unknown scenario');
    }
    assert.equal(legacyCalls, 0);
    console.log(JSON.stringify({scenario, result: 'PASS'}));
}
main().catch(error => {console.error(error); process.exitCode = 1;});
