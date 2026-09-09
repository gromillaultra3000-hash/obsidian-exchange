'use strict';

// A narrow executable harness: production functions are extracted verbatim.
// The DOM, wall clock, timers, storage and network are deterministic boundaries;
// recipient normalization, rendering, validation and review handlers are real.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const [sourcePath, scenario, serializedParameters] = process.argv.slice(2);
const source = fs.readFileSync(sourcePath, 'utf8');
const parameters = JSON.parse(serializedParameters || '{}');

function functionSource(name) {
    const pattern = new RegExp('^        (?:async )?function ' + name
        + '\\([^]*?^        \\}(?=\\r?$)', 'gm');
    const matches = Array.from(source.matchAll(pattern));
    assert.equal(matches.length, 1, `expected one production function ${name}`);
    return matches[0][0];
}

function oneRegion(pattern, label) {
    const match = source.match(pattern);
    assert.ok(match, `missing production ${label}`);
    return match[0];
}

function harness(options = {}) {
    const sessionValues = options.sessionValues || new Map();
    const sessionStorage = options.sessionStorage || {
        getItem: key => sessionValues.has(key) ? sessionValues.get(key) : null,
        setItem: (key, value) => sessionValues.set(key, String(value)),
        removeItem: key => sessionValues.delete(key),
    };
    let now = 1_000_000;
    let nextTimer = 0;
    const timers = new Map();
    const requests = [];
    const signingAttempts = [];
    const walletRequest = {validUntil: 2000, network: '-239', messages: [
        {address: 'EQ' + 'A'.repeat(46), amount: '1250000000', payload: 'synthetic-not-a-boc'}]};
    const storageWrites = [];
    const localValues = options.localValues || new Map();
    const localStorage = options.localStorage || {
        getItem: key => localValues.has(key) ? localValues.get(key) : null,
        setItem: (key, value) => { storageWrites.push([key, value]); localValues.set(key, String(value)); },
        removeItem: key => localValues.delete(key),
    };
    const locks = options.locks || {async request(name, options, callback) {return callback({name});}};
    const elements = new Map();
    let document;

    class Element {
        constructor(id) {
            this.id = id;
            this.value = '';
            this.textContent = '';
            this.innerHTML = '';
            this.checked = false;
            this.disabled = false;
            this.style = {display: ''};
            this.offsetParent = {};
            this.attributes = {};
            this.listeners = new Map();
            const classes = new Set();
            this.classList = {
                remove: (...names) => names.forEach(name => classes.delete(name)),
                toggle: (name, on) => on ? classes.add(name) : classes.delete(name),
                contains: name => classes.has(name),
            };
        }
        setAttribute(name, value) { this.attributes[name] = value; }
        focus() { document.activeElement = this; }
        addEventListener(type, callback) {
            if (!this.listeners.has(type)) this.listeners.set(type, []);
            this.listeners.get(type).push(callback);
        }
        async fire(type, event = {}) {
            // Invoke even disabled controls to exercise the handler's guard.
            for (const callback of this.listeners.get(type) || []) await callback(event);
        }
        querySelectorAll() {
            return ['exchange-review-ack', 'exchange-review-cancel', 'exchange-review-confirm']
                .map(id => elements.get(id)).filter(element => !element.disabled);
        }
        querySelector(selector) {
            return selector === '.exchange-review-surface' ? this : null;
        }
    }

    const ids = [
        'currency', 'amount', 'address', 'address-msg', 'network', 'pay-method',
        'exchange-result', 'exchange-steps', 'create-order', 'fee-value',
        'tag-group', 'dest_tag', 'no_tag', 'no-tag-label', 'tag-label', 'tag-hint',
        'exchange-review', 'exchange-review-title', 'exchange-review-description', 'exchange-review-summary',
        'exchange-review-risk', 'exchange-review-ack', 'exchange-review-confirm',
        'exchange-review-cancel', 'exchange-review-freshness',
        'sell-submit', 'sell-result', 'sell-currency', 'sell-amount', 'sell-method',
        'sell-phone', 'sell-bank', 'sell-name', 'sell-payout', 'sell-fee-note',
        'wallet-attempt-notice', 'wallet-attempt-details', 'wallet-attempt-ack', 'wallet-attempt-remove',
        'w-send-msg', 'w-to', 'w-amount', 'w-comment', 'w-send-go', 'sell-card-pay',
    ];
    for (const id of ids) elements.set(id, new Element(id));
    const el = id => {
        assert.ok(elements.has(id), `unexpected DOM dependency ${id}`);
        return elements.get(id);
    };
    document = new Element('document');
    document.activeElement = el('create-order');
    document.getElementById = el;
    document.contains = element => elements.get(element.id) === element;
    document.querySelector = selector => {
        if (selector === 'input[name="pay_method"]:checked') return el('pay-method');
        if (selector === '#sell-method option:checked') {
            return {textContent: el('sell-method').value === 'card' ? 'Карта' : 'СБП'};
        }
        if (selector === '#sell-bank option:checked') {
            return {textContent: el('sell-bank').value === 'test-bank' ? 'Тестовый банк' : 'Другой банк'};
        }
        throw new Error(`unexpected selector ${selector}`);
    };

    const context = vm.createContext({
        document,
        atob,
        navigator: {locks},
        crypto: require('node:crypto').webcrypto,
        HTMLElement: Element,
        Date: class Clock extends Date { static now() { return now; } },
        setTimeout(callback, delay) {
            const id = ++nextTimer;
            timers.set(id, {callback, at: now + delay});
            return id;
        },
        clearTimeout: id => timers.delete(id),
        tg: {initData: ''},
        tcUI: {account: {address: '0:' + 'b'.repeat(64), chain: '-239'}, async sendTransaction(request) {
            signingAttempts.push(JSON.parse(JSON.stringify(request)));
            throw new Error('Synthetic signing blocked');
        }},
        window: {addEventListener() {}, __oeOfferings: [
            ...['BTC', 'LTC', 'ETH', 'USDT', 'XMR', 'FUTURE_ASSET'].map(code => ({code,
                networks: ['MAINNET', 'ERC20', 'TRC20'].map(code => ({code, label: code}))})),
            {code: 'XRP', networks: [{code: 'MAINNET', label: 'Mainnet'}], tag_name: 'destination tag', tag_kind: 'uint32', tag_sep: ':'},
            {code: 'TON', networks: [{code: 'MAINNET', label: 'Mainnet'}], tag_name: 'memo', tag_kind: 'text', tag_sep: '#'},
        ]},
        sellPayoutWays: [
            {code: 'sbp', needs_bank: true, needs_name: true},
            {code: 'card', needs_bank: true, needs_name: true},
        ],
        sessionStorage,
        localStorage,
        async fetch(url, options) {
            requests.push({url, method: options.method, body: JSON.parse(options.body)});
            if (['/api/wallet/transfer-request', '/api/wallet/send-request'].includes(url)) {
                return {ok: true, json: async () => ({ok: true, sell_id: 42,
                    amount: 1.25, from_address: '0:' + 'b'.repeat(64), address: walletRequest.messages[0].address,
                    marker: 'invoice  42 <b>literal</b>', request: walletRequest})};
            }
            // Stop after the real writer serializes its payload; this test does
            // not simulate order tracking, payout, or successful settlement.
            return {ok: false, json: async () => ({ok: false, detail: 'Synthetic rejection'})};
        },
    });
    const functions = [
        'esc', 'currentOffering', 'currentTagName', 'addressCarriesTag', 'updateTagField',
        'selectedNetwork', 'validateAddress', 'sellPayoutWay', 'luhnOk',
        'exchangeReviewFocusable', 'clearExchangeReviewExpiry', 'updateExchangeReviewConfirm',
        'invalidateExchangeReview', 'closeExchangeReview', 'openExchangeReview',
        'beginBuyOrder', 'submitBuyOrder', 'createSellOrder', 'submitSellOrder',
        'walletTransfer', 'walletPay', 'walletShorten',
    ];
    const declarations = oneRegion(
        /^        let exchangeReviewCommit = null;[^]*?(?=^        function exchangeReviewFocusable)/m,
        'review state');
    const wiring = oneRegion(
        /^        \(function wireExchangeReview\(\) \{[^]*?^        \}\)\(\);/m,
        'review event wiring');
    const attempt = source.includes('const walletAttemptStorageKey') ? oneRegion(
        /^        const walletAttemptStorageKey[^]*?(?=^        let exchangeReviewCommit)/m,
        'wallet attempt state') : '';
    vm.runInContext('let buyRateSnapshot = null; let sellEstimateSnapshot = null; let sellOrderPending = false; let buyReviewRoute = null;\n' + functionSource('buyRouteSignature') + '\n' + functionSource('sellSnapshotInfo') + '\n' + functionSource('sellReviewEstimate') + '\n' + functionSource('buyReviewEstimate') + '\n' + declarations + '\n' + attempt + '\n' + functions.map(functionSource).join('\n') + '\n' + wiring,
        context, {filename: sourcePath, timeout: 1000});
    if (attempt) vm.runInContext(oneRegion(
        /^        \(function wireWalletAttemptNotice\(\) \{[^]*?^        \}\)\(\);/m,
        'wallet attempt event wiring'), context);

    el('currency').value = 'BTC';
    el('amount').value = '12500';
    el('address').value = 'bc1' + 'q'.repeat(87);
    el('network').value = 'MAINNET';
    el('pay-method').value = 'card';
    el('fee-value').textContent = '125 ₽';
    el('tag-group').style.display = 'none';
    el('exchange-review').style.display = 'none';
    el('sell-currency').value = 'BTC';
    el('sell-amount').value = '0.125';
    el('sell-method').value = 'sbp';
    el('sell-phone').value = '+7 900-123-45-67';
    el('sell-bank').value = 'test-bank';
    el('sell-name').value = '  Тестовый Получатель  ';
    el('sell-payout').textContent = '12 000 ₽';
    el('sell-fee-note').textContent = 'Комиссия: 1%';

    const decode = text => text.replace(/&(amp|lt|gt|quot|#39);/g,
        (_, entity) => ({amp: '&', lt: '<', gt: '>', quot: '"', '#39': "'"}[entity]));
    function rows() {
        const rendered = el('exchange-review-summary').innerHTML;
        const matches = Array.from(rendered.matchAll(
            /<div[^>]*><div[^>]*>([^]*?)<\/div><div([^>]*)>([^]*?)<\/div><\/div>/g));
        assert.ok(matches.length, 'review must render summary rows');
        return matches.map(match => ({label: decode(match[1]), value: decode(match[3]),
            attributes: match[2], rawValue: match[3]}));
    }
    function row(label) {
        const found = rows().filter(item => item.label === label);
        assert.equal(found.length, 1, `one separate row for ${label}`);
        return found[0];
    }
    async function acknowledge() {
        el('exchange-review-ack').checked = true;
        await el('exchange-review-ack').fire('change');
    }
    async function confirm() {
        await acknowledge();
        assert.equal(el('exchange-review-confirm').disabled, false);
        await el('exchange-review-confirm').fire('click');
    }
    function advance(ms, runTimers = true) {
        now += ms;
        if (!runTimers) return;
        for (const [id, timer] of Array.from(timers)) {
            if (timer.at <= now && timers.delete(id)) timer.callback();
        }
    }
    function noWrites() {
        assert.deepEqual(requests, [], 'reviewing must not create an order');
        assert.deepEqual(storageWrites, [], 'reviewing must not persist the destination');
    }
    return {context, el, document, requests, storageWrites, rows, row, acknowledge, confirm,
        advance, noWrites, signingAttempts, walletRequest, sessionValues, sessionStorage};
}

function assertBuyWrite(h, expected) {
    assert.equal(h.requests.length, 1);
    assert.equal(h.requests[0].url, '/api/create_order');
    assert.equal(h.requests[0].method, 'POST');
    assert.deepEqual(h.requests[0].body, expected);
}

async function buySnapshot({tag_mode}) {
    const h = harness();
    const isTaggedAsset = tag_mode !== 'hidden';
    const address = isTaggedAsset ? 'r' + 'p'.repeat(33) : 'bc1' + 'q'.repeat(87);
    h.el('currency').value = isTaggedAsset ? 'XRP' : 'BTC';
    h.el('address').value = '  ' + address + '  ';
    h.el('dest_tag').value = tag_mode === 'tag' ? '  987654321  ' : '';
    h.el('no_tag').checked = tag_mode === 'no_tag';
    h.context.beginBuyOrder();
    assert.equal(h.el('exchange-review').style.display, 'flex');
    assert.equal(h.row('Адрес получателя').value, address);
    assert.equal(h.row('Валюта и сеть').value, (isTaggedAsset ? 'XRP' : 'BTC') + ' · MAINNET');
    const tagRows = h.rows().filter(row => row.label === 'Тег / memo');
    if (isTaggedAsset) {
        assert.equal(tagRows.length, 1);
        const expected = tag_mode === 'tag' ? '987654321'
            : tag_mode === 'no_tag' ? 'Без тега — подтверждено в форме'
            : 'Не указан — проверьте, нужен ли тег получателю';
        assert.equal(tagRows[0].value, expected);
    } else assert.equal(tagRows.length, 0);
    h.noWrites();
    h.el('currency').value = 'ETH';
    h.el('amount').value = '300000';
    h.el('address').value = '0x' + 'f'.repeat(40);
    h.el('network').value = 'ERC20';
    h.el('pay-method').value = 'sbp';
    h.el('dest_tag').value = 'changed';
    h.el('no_tag').checked = tag_mode !== 'no_tag';
    await h.confirm();
    assertBuyWrite(h, {currency: isTaggedAsset ? 'XRP' : 'BTC', amount: 12500,
        address, network: 'MAINNET', pay_method: 'card',
        dest_tag: tag_mode === 'tag' ? '987654321' : '', no_tag: tag_mode === 'no_tag'});
}

async function literalMemo({embedded}) {
    const h = harness();
    const memo = 'invoice  <synthetic>  & "42"';
    const address = 'EQ' + 'A'.repeat(46) + (embedded ? '#' + memo : '');
    h.el('currency').value = 'TON';
    h.el('address').value = address;
    h.el('dest_tag').value = embedded ? '' : memo;
    h.context.beginBuyOrder();
    const rendered = h.row(embedded ? 'Адрес получателя' : 'Тег / memo');
    assert.equal(rendered.value, embedded ? address : memo);
    assert.ok(rendered.attributes.includes('white-space:pre-wrap'),
        'literal recipient whitespace must survive browser HTML layout');
    assert.ok(rendered.rawValue.includes('&lt;synthetic&gt;'));
    assert.ok(rendered.rawValue.includes('&amp;'));
    assert.ok(!rendered.rawValue.includes('<synthetic>'));
    h.noWrites();
    await h.confirm();
    assertBuyWrite(h, {currency: 'TON', amount: 12500, address, network: 'MAINNET',
        pay_method: 'card', dest_tag: embedded ? '' : memo, no_tag: false});
}

async function sellSnapshot({method}) {
    const h = harness();
    const normalized = method === 'card' ? '4111111111111111' : '79001234567';
    h.el('sell-method').value = method;
    h.el('sell-phone').value = method === 'card' ? '4111 1111-1111 1111' : '+7 900-123-45-67';
    await h.context.createSellOrder();
    assert.equal(h.el('exchange-review').style.display, 'flex');
    assert.equal(h.row(method === 'card' ? 'Карта получателя' : 'Телефон получателя').value, normalized);
    assert.equal(h.row('Банк получателя').value, 'Тестовый банк');
    assert.equal(h.row('Получатель').value, 'Тестовый Получатель');
    h.noWrites();
    h.el('sell-currency').value = 'ETH';
    h.el('sell-amount').value = '10';
    h.el('sell-method').value = method === 'card' ? 'sbp' : 'card';
    h.el('sell-phone').value = '79990000000';
    h.el('sell-bank').value = 'changed-bank';
    h.el('sell-name').value = 'Другой Получатель';
    await h.confirm();
    assert.deepEqual(h.requests, [{url: '/api/sell/create', method: 'POST', body: {
        currency: 'BTC', amount: 0.125, phone: normalized, method,
        bank: 'test-bank', full_name: 'Тестовый Получатель',
    }}]);
}

async function destinationCase({currency, network, address}, accepted) {
    const h = harness();
    h.el('currency').value = currency;
    h.el('network').value = network;
    h.el('address').value = address;
    h.context.beginBuyOrder();
    h.noWrites();
    assert.equal(h.el('exchange-review').style.display, accepted ? 'flex' : 'none');
    if (accepted) {
        assert.equal(h.row('Адрес получателя').value, address);
        assert.equal(h.el('address').classList.contains('valid'), true);
        await h.confirm();
        assertBuyWrite(h, {currency, amount: 12500, address, network,
            pay_method: 'card', dest_tag: '', no_tag: false});
    } else {
        assert.equal(h.el('address').classList.contains('invalid'), true);
        assert.equal(h.document.activeElement, h.el('address'));
        assert.ok(h.el('exchange-result').textContent.length > 0);
        await h.acknowledge();
        await h.el('exchange-review-confirm').fire('click');
        h.noWrites();
    }
}

async function unknownDestination() {
    const h = harness();
    h.el('currency').value = 'FUTURE_ASSET';
    h.el('address').value = 'synthetic:future/network:recipient';
    h.el('address').classList.toggle('invalid', true);
    h.el('address-msg').textContent = 'stale format error';
    assert.equal(h.context.validateAddress(), null);
    assert.equal(h.el('address').classList.contains('invalid'), false);
    assert.equal(h.el('address').classList.contains('valid'), false);
    assert.equal(h.el('address-msg').textContent, '');
    h.context.beginBuyOrder();
    h.noWrites();
    assert.equal(h.el('exchange-review').style.display, 'flex');
    await h.confirm();
    assert.equal(h.requests[0].body.address, 'synthetic:future/network:recipient');
    assert.equal(h.requests[0].body.currency, 'FUTURE_ASSET');
}

async function reviewBoundary({boundary}) {
    const h = harness();
    h.context.beginBuyOrder();
    assert.equal(h.el('exchange-review-ack').checked, false);
    assert.equal(h.el('exchange-review-confirm').disabled, true);
    h.noWrites();
    if (boundary === 'unacknowledged') {
        await h.el('exchange-review-confirm').fire('click');
        h.noWrites();
        return;
    }
    await h.acknowledge();
    assert.equal(h.el('exchange-review-confirm').disabled, false);
    if (boundary === 'fresh-once') {
        h.advance(119999, false);
        await h.el('exchange-review-confirm').fire('click');
        await h.el('exchange-review-confirm').fire('click');
        assert.equal(h.requests.length, 1, 'acknowledgement is consumed once');
        assert.equal(h.el('exchange-review').style.display, 'none');
        return;
    }
    if (boundary === 'cancel') await h.el('exchange-review-cancel').fire('click');
    else if (boundary === 'escape') await h.document.fire('keydown', {key: 'Escape'});
    else if (boundary === 'exact-expiry') h.advance(120000, false);
    else h.advance(120050);

    if (['cancel', 'escape'].includes(boundary)) {
        assert.equal(h.el('exchange-review').style.display, 'none');
        assert.equal(h.document.activeElement, h.el('create-order'));
    }
    if (['timer-expiry', 'reopen'].includes(boundary)) {
        assert.equal(h.el('exchange-review-ack').checked, false);
        assert.equal(h.el('exchange-review-confirm').disabled, true);
        assert.ok(h.el('exchange-review-freshness').textContent.includes('истекло'));
    }
    await h.acknowledge();
    await h.el('exchange-review-confirm').fire('click');
    h.noWrites();
    if (boundary === 'reopen') {
        h.el('address').value = 'bc1' + 'p'.repeat(39);
        h.context.beginBuyOrder();
        assert.equal(h.el('exchange-review-ack').checked, false);
        assert.equal(h.el('exchange-review-confirm').disabled, true);
        await h.confirm();
        assert.equal(h.requests.length, 1);
        assert.equal(h.requests[0].body.address, 'bc1' + 'p'.repeat(39));
    }
}

async function walletReview({action, boundary}) {
    const h = harness();
    const button = action === 'payment' ? h.el('sell-card-pay') : h.el('w-send-go');
    h.document.activeElement = button;
    h.el('w-to').value = h.walletRequest.messages[0].address;
    h.el('w-amount').value = '1.25';
    h.el('w-comment').value = 'invoice  42 <b>literal</b>';
    const open = () => action === 'payment'
        ? h.context.walletPay(42, button) : h.context.walletTransfer();
    await open();
    assert.equal(h.el('exchange-review').style.display, 'flex');
    assert.equal(h.el('exchange-review-confirm').textContent, 'Продолжить в кошельке');
    const description = h.el('exchange-review-description').textContent;
    assert.ok(description.includes(action === 'payment' ? 'Заявка уже создана' : 'Это перевод из вашего кошелька'));
    assert.ok(description.includes('подпись нужно подтвердить отдельно'));
    assert.ok(!description.includes('Заявка ещё не создана'));
    const fee = h.row('Сетевая комиссия').value;
    for (const text of ['отдельно в TON', 'сверх суммы перевода', 'Здесь не рассчитана', 'итоговое списание в кошельке']) {
        assert.ok(fee.includes(text));
    }
    if (action === 'payment') assert.ok(fee.includes('не комиссия обмена'));
    assert.ok(h.row('Маршрут').value.includes(action === 'payment' ? 'private lane · без KYC' : 'CEX / KYC-аккаунт не используются'));
    assert.equal(h.row('Получатель').value, h.walletRequest.messages[0].address);
    const comment = h.row(action === 'payment' ? 'Комментарий к переводу' : 'Комментарий');
    assert.equal(comment.value, 'invoice  42 <b>literal</b>');
    assert.ok(comment.rawValue.includes('&lt;b&gt;'));
    assert.equal(h.el('exchange-review-confirm').disabled, true);
    await h.el('exchange-review-confirm').fire('click');
    assert.equal(h.signingAttempts.length, 0);
    assert.equal(h.requests.length, 1, 'only synthetic preparation before acknowledgement');
    if (boundary === 'confirm') {
        // Editing the form after review must not mutate the prepared handoff.
        h.el('w-amount').value = '99';
        h.el('w-to').value = 'changed';
        await h.confirm();
        await h.el('exchange-review-confirm').fire('click');
        assert.deepEqual(h.signingAttempts, [h.walletRequest]);
        assert.equal(h.requests.length, 1, 'rejected signing must never mark payment signed');
        const feedback = action === 'payment' ? button.textContent : h.el('w-send-msg').textContent;
        assert.ok(feedback.includes('Исход перевода неизвестен'));
        assert.ok(feedback.includes('не повторяйте перевод'));
    } else {
        await h.acknowledge();
        if (boundary === 'cancel') await h.el('exchange-review-cancel').fire('click');
        if (boundary === 'escape') await h.document.fire('keydown', {key: 'Escape'});
        if (boundary === 'expiry') h.advance(120050);
        await h.el('exchange-review-confirm').fire('click');
        assert.equal(h.signingAttempts.length, 0);
        if (boundary !== 'expiry') assert.equal(h.document.activeElement, button);
    }
    h.context.closeExchangeReview();
    h.context.beginBuyOrder();
    assert.equal(h.el('exchange-review-confirm').textContent, 'Подтвердить и создать');
    assert.ok(h.el('exchange-review-description').textContent.startsWith('Заявка ещё не создана.'));
    assert.equal(h.el('exchange-review-ack').checked, false);
    assert.equal(h.el('exchange-review-confirm').disabled, true);
    h.context.closeExchangeReview();
    h.context.createSellOrder();
    assert.equal(h.el('exchange-review-confirm').textContent, 'Подтвердить и создать');
    assert.ok(h.el('exchange-review-description').textContent.startsWith('Заявка ещё не создана.'));
    assert.equal(h.requests.length, 1);
}

const scenarios = {
    wallet_review: walletReview,
    buy_snapshot: buySnapshot,
    literal_memo: literalMemo,
    sell_snapshot: sellSnapshot,
    invalid_destination: data => destinationCase(data, false),
    accepted_destination: data => destinationCase(data, true),
    unknown_destination: unknownDestination,
    review_boundary: reviewBoundary,
};
assert.ok(scenarios[scenario], `unknown scenario ${scenario}`);
scenarios[scenario](parameters).catch(error => {
    console.error(error.stack);
    process.exitCode = 1;
});
