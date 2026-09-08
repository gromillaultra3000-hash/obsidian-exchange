'use strict';

// Real shipped HTML, synthetic API fixtures, and a deny-by-default browser.
// Run as an unprivileged user in a disconnected network namespace; never point
// this runner at a live site. The parent must reap the browser's process group.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const {chromium} = require('playwright-core');
const [sourcePath, outputDir] = process.argv.slice(2);
const source = fs.readFileSync(sourcePath, 'utf8');
const origin = 'https://e4.invalid';
const report = {schemaVersion: 'e4-review-browser.v1', sourceSha256:
    crypto.createHash('sha256').update(source).digest('hex'),
    runnerSha256: crypto.createHash('sha256').update(fs.readFileSync(__filename)).digest('hex'),
    playwrightVersion: require('playwright-core/package.json').version, checks: [], openings: [],
    writerAttempts: [], walletPreparations: [], signingAttempts: [], blockedRequests: [], pageErrors: []};
const walletAddress = 'EQ' + 'A'.repeat(46);
const walletMemo = 'invoice  42 <b>literal</b>';
// Intentionally unsigned and unusable: even a harness regression cannot turn
// this fixture into a chain transaction. No wallet SDK is loaded.
const walletRequest = {validUntil: 2000, network: '-239', messages: [
    {address: walletAddress, amount: '1250000000', payload: 'synthetic-not-a-boc'}]};
fs.mkdirSync(outputDir, {recursive: true});

async function main() {
    assert.notEqual(process.getuid(), 0, 'browser must run as non-root');
    const browser = await chromium.launch({executablePath: '/opt/google/chrome/chrome',
        chromiumSandbox: true, headless: true});
    report.browserVersion = browser.version();
    let activePage;
    try {
        for (const viewport of [{width: 320, height: 568}, {width: 390, height: 844},
                                {width: 1280, height: 800}]) {
        const context = await browser.newContext({viewport,
            serviceWorkers: 'block', locale: 'ru-RU'});
        let holdReceive = false;
        let receiveRequested;
        const pendingReceiveRoutes = [];
        let orderRequested;
        const pendingOrderRoutes = [];
        await context.addInitScript(() => {
            window.Telegram = {WebApp: {initData: '', initDataUnsafe: {},
                expand() {}, ready() {}, onEvent() {},
                setHeaderColor() {}, setBackgroundColor() {}, setBottomBarColor() {}}};
        });
        await context.route('**/*', async route => {
            const req = route.request();
            const url = new URL(req.url());
            if (url.origin === origin && req.method() === 'GET' && url.pathname.startsWith('/api/order/synthetic-')) {
                pendingOrderRoutes.push(route);
                if (orderRequested) orderRequested();
                return;
            }
            if (holdReceive && url.origin === origin && req.method() === 'GET'
                    && url.pathname === '/api/wallet/receive') {
                pendingReceiveRoutes.push(route);
                receiveRequested();
                return;
            }
            if (url.origin === origin && req.method() === 'POST'
                    && ['/api/wallet/transfer-request', '/api/wallet/send-request'].includes(url.pathname)) {
                report.walletPreparations.push({path: url.pathname, payload: req.postDataJSON()});
                return route.fulfill({contentType: 'application/json', body: JSON.stringify({
                    ok: true, sell_id: 42, amount: 1.25, address: walletAddress,
                    marker: walletMemo, request: walletRequest})});
            }
            if (req.method() !== 'GET') {
                report.writerAttempts.push({path: url.pathname, method: req.method(),
                    payload: req.postDataJSON()});
                return route.fulfill({status: 409, contentType: 'application/json',
                    body: JSON.stringify({ok: false, detail: 'Synthetic writer blocked'})});
            }
            if (url.origin === origin && url.pathname === '/webapp') {
                return route.fulfill({contentType: 'text/html', body: source});
            }
            const fixtures = {
                '/api/wallet/links': {wallets: [{chain: 'TON', address: walletAddress, balance: null}]},
                '/api/wallet/history': {status: 'OK', items: []},
                '/api/wallet/receive': {ok: true, address: walletAddress,
                    qr_image: 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII='},
                '/api/wallet/dues': {dues: [{sell_id: 42, amount: 1.25, currency: 'TON', marker: 'invoice-42'}]},
                '/api/rates': {BTC: 5000000, TON: 200, offerings: [
                    {code: 'BTC', networks: [{code: 'MAINNET', label: 'Bitcoin'}]},
                    {code: 'TON', networks: [{code: 'MAINNET', label: 'TON'}],
                        tag_name: 'memo', tag_kind: 'text', tag_sep: '#'}]},
                '/api/sell/options': {coins: [{code: 'BTC', label: 'Bitcoin',
                    rate: 4900000, market: 5000000, min: 0.0001, network: 'MAINNET'}],
                    fee_label: '2%', payout_ways: [
                        {code: 'sbp', label: 'СБП', needs_bank: true, needs_name: true},
                        {code: 'card', label: 'Карта', needs_bank: true, needs_name: true}],
                    payout_banks: [{code: 'test-bank', label: 'Тестовый банк'}]},
            };
            if (url.origin === origin && fixtures[url.pathname]) {
                return route.fulfill({contentType: 'application/json',
                    body: JSON.stringify(fixtures[url.pathname])});
            }
            // No route.continue/fallback: SDKs, analytics, all other APIs denied.
            report.blockedRequests.push(url.origin + url.pathname);
            return route.abort('blockedbyclient');
        });
        const page = await context.newPage();
        activePage = page;
        page.on('pageerror', error => report.pageErrors.push(error.message));
        page.setDefaultTimeout(5000);
        await page.clock.install();
        await page.goto(origin + '/webapp', {waitUntil: 'load'});
        await page.locator('#tab-exchange').click();
        await page.locator('#currency').selectOption('BTC');
        await page.locator('#amount').fill('12500');
        await page.locator('#address').fill('bc1' + 'q'.repeat(87));
        await page.locator('#create-order').click();
        const modal = page.locator('#exchange-review');
        const ack = page.locator('#exchange-review-ack');
        const confirm = page.locator('#exchange-review-confirm');
        const cancel = page.locator('#exchange-review-cancel');
        const writerCount = report.writerAttempts.length;
        async function openingCheck(label) {
            await modal.waitFor({state: 'visible'});
            assert.equal(await modal.isVisible(), true);
            const opening = await page.evaluate(() => {
                const surface = document.querySelector('.exchange-review-surface');
                const bounds = surface.getBoundingClientRect();
                const title = document.getElementById('exchange-review-title').getBoundingClientRect();
                return {scrollTop: surface.scrollTop, focused: document.activeElement.id,
                    titleVisible: title.top >= bounds.top && title.bottom <= bounds.bottom,
                    clientWidth: surface.clientWidth, scrollWidth: surface.scrollWidth};
            });
            report.openings.push({viewport, label, ...opening});
            await page.screenshot({path: path.join(outputDir, `${viewport.width}-${label}.png`)});
            assert.equal(opening.scrollTop, 0, 'review must open at its conditions, not at acknowledgement');
            assert.equal(opening.titleVisible, true);
            assert.equal(opening.focused, 'exchange-review-title');
            assert.ok(opening.scrollWidth <= opening.clientWidth, 'recipient must wrap without clipping');
            assert.equal(await ack.isChecked(), false);
            assert.equal(await confirm.isDisabled(), true);
            report.checks.push(`${viewport.width}: ${label} opens at conditions without overflow`);
        }
        async function focusIs(id) {
            assert.equal(await page.evaluate(() => document.activeElement.id), id);
        }
        await openingCheck('buy');
        assert.ok((await page.locator('#exchange-review-summary').textContent()).includes('bc1' + 'q'.repeat(87)));
        for (const text of ['ObsidianExchange', 'private lane', 'без KYC', 'Custody', 'Комиссия']) {
            assert.ok((await modal.textContent()).includes(text));
        }
        await page.keyboard.press('Enter');
        assert.equal(report.writerAttempts.length, writerCount);
        await page.keyboard.press('Shift+Tab');
        await focusIs('exchange-review-cancel');
        await page.keyboard.press('Tab');
        await focusIs('exchange-review-ack');
        await page.keyboard.press('Shift+Tab');
        await focusIs('exchange-review-cancel');
        await page.keyboard.press('Escape');
        await focusIs('create-order');
        assert.equal(await modal.isVisible(), false);
        await page.locator('#create-order').click();
        await openingCheck('reopen');
        await page.keyboard.press('Tab');
        await focusIs('exchange-review-ack');
        await page.keyboard.press('Space');
        assert.equal(await confirm.isEnabled(), true);
        await page.keyboard.press('Tab');
        await focusIs('exchange-review-cancel');
        await page.keyboard.press('Tab');
        await focusIs('exchange-review-confirm');
        await page.keyboard.press('Tab');
        await focusIs('exchange-review-ack');
        await page.keyboard.press('Shift+Tab');
        await focusIs('exchange-review-confirm');
        await cancel.click();
        await focusIs('create-order');
        assert.equal(report.writerAttempts.length, writerCount);
        report.checks.push(`${viewport.width}: keyboard containment, Enter inert, Escape/cancel restore focus`);

        await page.locator('#create-order').click();
        await ack.check();
        await page.clock.fastForward(120051);
        assert.equal(await confirm.isDisabled(), true);
        assert.equal(await ack.isChecked(), false);
        assert.ok((await page.locator('#exchange-review-freshness').innerText()).includes('истекло'));
        await ack.check();
        assert.equal(await confirm.isDisabled(), true, 'checking again cannot revive expired review');
        assert.equal(report.writerAttempts.length, writerCount);
        await cancel.click();
        // Rates refresh while time advances can reset the form's saved-address
        // field. Re-enter the synthetic recipient before a fresh review.
        await page.locator('#address').fill('bc1' + 'q'.repeat(87));
        await page.locator('#create-order').click();
        await openingCheck('after-expiry');
        report.checks.push(`${viewport.width}: expiry blocks confirmation and reopening resets acknowledgement`);
        await ack.check();
        const buyResponse = page.waitForResponse(r => r.url().endsWith('/api/create_order'));
        await confirm.click();
        assert.equal((await buyResponse).status(), 409);
        assert.equal(report.writerAttempts.length, writerCount + 1);
        assert.equal(report.writerAttempts.at(-1).payload.address, 'bc1' + 'q'.repeat(87));
        assert.equal(await modal.isVisible(), false);
        assert.equal(await page.evaluate(() => localStorage.getItem('lastAddress_BTC_MAINNET')), null);
        report.checks.push(`${viewport.width}: acknowledged buy reaches only blocked synthetic writer`);

        await page.locator('#currency').selectOption('TON');
        const memo = 'invoice  42 <b>literal</b>';
        await page.locator('#address').fill('EQ' + 'A'.repeat(46));
        await page.locator('#dest_tag').fill(memo);
        await page.locator('#create-order').click();
        assert.ok((await page.locator('#exchange-review-summary').textContent()).includes(memo));
        assert.equal(await page.locator('#exchange-review-summary b').count(), 0);
        await cancel.click();
        report.checks.push(`${viewport.width}: memo spaces/markup remain literal text`);

        await page.locator('#deal-side [data-side="sell"]').click();
        for (const method of ['sbp', 'card']) {
            await page.locator('#sell-currency').selectOption('BTC');
            await page.locator('#sell-amount').fill('0.01');
            await page.locator('#sell-method').selectOption(method);
            // Deliberately synthetic fixtures, never customer records.
            const recipient = method === 'sbp' ? '+7 000 000-00-00' : '4111 1111 1111 1111';
            const normalized = method === 'sbp' ? '70000000000' : '4111111111111111';
            await page.locator('#sell-phone').fill(recipient);
            await page.locator('#sell-bank').selectOption('test-bank');
            await page.locator('#sell-name').fill('Тестовый Получатель');
            await page.locator('#sell-submit').click();
            await openingCheck('sell-' + method);
            const summary = await page.locator('#exchange-review-summary').textContent();
            for (const text of [normalized, 'Тестовый банк', 'Тестовый Получатель', 'Комиссия', 'без KYC']) {
                assert.ok(summary.includes(text));
            }
            assert.ok((await page.locator('#exchange-review-risk').innerText()).includes('отменить операцию блокчейна нельзя'));
            const before = report.writerAttempts.length;
            await cancel.click();
            await focusIs('sell-submit');
            assert.equal(report.writerAttempts.length, before);
            await page.locator('#sell-submit').click();
            await ack.check();
            const sellResponse = page.waitForResponse(r => r.url().endsWith('/api/sell/create'));
            await confirm.click();
            assert.equal((await sellResponse).status(), 409);
            assert.equal(report.writerAttempts.length, before + 1);
            assert.equal(report.writerAttempts.at(-1).payload.phone, normalized);
            assert.equal(report.writerAttempts.at(-1).payload.method, method);
            report.checks.push(`${viewport.width}: ${method} recipient review/cancel and one blocked confirmed writer`);
        }
        // Replace only the SDK boundary with a rejecting synthetic stub. The
        // shipped wallet buttons, prepare calls, review and handlers run intact.
        await page.evaluate(() => {
            window.__syntheticSigningAttempts = [];
            tcUI = {async sendTransaction(request) {
                window.__syntheticSigningAttempts.push(structuredClone(request));
                throw new Error('Synthetic signing blocked');
            }};
        });
        await page.locator('#tab-wallet').click();
        await page.locator('#w-act-send').click();
        await page.locator('#w-to').fill(walletAddress);
        await page.locator('#w-amount').fill('1.25');
        await page.locator('#w-comment').fill(walletMemo);
        const walletWritersBefore = report.writerAttempts.length;
        for (const action of ['transfer', 'payment']) {
            const opener = action === 'transfer' ? page.locator('#w-send-go') : page.locator('.wallet-pay');
            async function openWalletReview() {
                await opener.click();
                // check() can return immediately for the still-checked input
                // in a closed modal; wait for the async prepare/open/reset.
                await modal.waitFor({state: 'visible'});
                assert.equal(await ack.isChecked(), false);
            }
            const signingCount = (await page.evaluate(() => window.__syntheticSigningAttempts)).length;
            await openWalletReview();
            await openingCheck('wallet-' + action);
            const description = await page.locator('#exchange-review-description').textContent();
            assert.ok(description.includes(action === 'payment' ? 'Заявка уже создана' : 'Это перевод из вашего кошелька'));
            assert.ok(description.includes('подпись нужно подтвердить отдельно'));
            assert.ok(!description.includes('Заявка ещё не создана'));
            assert.equal(await confirm.textContent(), 'Продолжить в кошельке');
            const summary = await page.locator('#exchange-review-summary').textContent();
            for (const text of [walletAddress, walletMemo, '1.25 TON', 'Ваш подключённый TON-кошелёк',
                    'Ключи остаются только в вашем кошельке', 'Сетевая комиссия', 'отдельно в TON',
                    'сверх суммы перевода', 'Здесь не рассчитана', 'итоговое списание в кошельке']) {
                assert.ok(summary.includes(text), `${action}: ${text}`);
            }
            assert.ok(summary.includes(action === 'payment' ? 'private lane · без KYC' : 'CEX / KYC-аккаунт не используются'));
            if (action === 'payment') assert.ok(summary.includes('не комиссия обмена'));
            assert.equal(await page.locator('#exchange-review-summary b').count(), 0);
            const risk = await page.locator('#exchange-review-risk').textContent();
            assert.ok(risk.includes('нельзя отменить'));
            if (action === 'payment') assert.ok(risk.includes('только после подтверждения в сети'));
            const feeCard = page.locator('#exchange-review-summary > div').filter({hasText: 'Сетевая комиссия'});
            await feeCard.scrollIntoViewIfNeeded();
            assert.equal(await feeCard.evaluate(el => {
                const row = el.getBoundingClientRect();
                const surface = el.closest('.exchange-review-surface').getBoundingClientRect();
                return row.top >= surface.top && row.bottom <= surface.bottom
                    && el.scrollWidth <= el.clientWidth;
            }), true, 'network-fee disclosure must be scrollable into view without clipping');
            await page.screenshot({path: path.join(outputDir, `${viewport.width}-wallet-${action}-fee.png`)});
            report.checks.push(`${viewport.width}: wallet ${action} network fee visible without clipping`);
            await page.keyboard.press('Enter');
            assert.equal((await page.evaluate(() => window.__syntheticSigningAttempts)).length, signingCount);
            await page.keyboard.press('Escape');
            assert.equal(await opener.evaluate(el => document.activeElement === el), true);
            await openWalletReview();
            await ack.check();
            await cancel.click();
            assert.equal(await opener.evaluate(el => document.activeElement === el), true);
            assert.equal((await page.evaluate(() => window.__syntheticSigningAttempts)).length, signingCount);
            await openWalletReview();
            await ack.check();
            await page.clock.fastForward(120051);
            assert.equal(await confirm.isDisabled(), true);
            assert.equal(await ack.isChecked(), false);
            assert.ok((await page.locator('#exchange-review-freshness').textContent()).includes('истекло'));
            await ack.check();
            assert.equal(await confirm.isDisabled(), true);
            await cancel.click();
            await openWalletReview();
            await openingCheck('wallet-' + action + '-fresh');
            await ack.check();
            await confirm.click();
            const attempts = await page.evaluate(() => window.__syntheticSigningAttempts);
            assert.equal(attempts.length, signingCount + 1);
            assert.deepEqual(attempts.at(-1), walletRequest, 'handoff preserves the prepared request');
            assert.equal(await modal.isVisible(), false);
            const feedback = action === 'transfer' ? page.locator('#w-send-msg') : opener;
            assert.equal(await feedback.textContent(), 'Перевод не подтверждён');
            assert.equal(report.writerAttempts.length, walletWritersBefore, 'no send-signed call after rejected signing');
            report.checks.push(`${viewport.width}: wallet ${action} copy/fees/literal recipient and memo verified`);
            report.checks.push(`${viewport.width}: wallet ${action} cancel/Escape/expiry block handoff; fresh acknowledgement reaches rejecting stub once`);
        }
        report.signingAttempts.push(...(await page.evaluate(() => window.__syntheticSigningAttempts)));
        await page.locator('#tab-exchange').click();
        for (const side of ['buy', 'sell']) {
            await page.locator(`#deal-side [data-side="${side}"]`).click();
            if (side === 'buy') {
                await page.locator('#currency').selectOption('BTC');
                await page.locator('#address').fill('bc1' + 'q'.repeat(87));
            }
            await page.locator(side === 'buy' ? '#create-order' : '#sell-submit').click();
            assert.equal(await modal.isVisible(), true);
            assert.ok((await page.locator('#exchange-review-description').textContent()).startsWith('Заявка ещё не создана.'));
            assert.equal(await confirm.textContent(), 'Подтвердить и создать');
            assert.equal(await ack.isChecked(), false);
            assert.equal(await confirm.isDisabled(), true);
            await cancel.click();
        }
        report.checks.push(`${viewport.width}: wallet-to-buy/sell restores order description, label and unchecked acknowledgement`);

        await page.locator('#tab-wallet').click();
        await page.locator('#w-act-recv').click();
        const receiveAddress = page.locator('#w-recv-addr');
        const copyButton = page.locator('#w-copy');
        const copyStatus = page.locator('#w-copy-status');
        await page.waitForFunction(expected => document.getElementById('w-recv-addr').textContent === expected, walletAddress);
        const qrSource = await page.locator('#w-qr').getAttribute('src');
        await page.evaluate(() => {
            window.__clipboardWrites = [];
            window.__clipboardPending = [];
            window.__copyHaptics = [];
            Telegram.WebApp.HapticFeedback = {impactOccurred: kind => window.__copyHaptics.push(kind)};
            Object.defineProperty(navigator, 'clipboard', {configurable: true, value: {
                writeText(value) {
                    window.__clipboardWrites.push(value);
                    return new Promise((resolve, reject) => window.__clipboardPending.push({resolve, reject}));
                },
            }});
        });
        const finishCopy = async (index, success = true) => page.evaluate(({index, success}) => {
            const task = window.__clipboardPending[index];
            if (success) task.resolve(); else task.reject(new Error('synthetic clipboard denial'));
        }, {index, success});
        async function receiveUnchanged() {
            assert.equal(await receiveAddress.textContent(), walletAddress);
            assert.equal((await copyButton.textContent()).trim(), 'Скопировать адрес');
            assert.equal(await page.locator('#w-qr').getAttribute('src'), qrSource);
        }
        assert.equal(await copyStatus.getAttribute('role'), 'status');
        // Native button semantics: keyboard activation uses the actual listener.
        await copyButton.focus();
        await page.keyboard.press('Enter');
        await receiveUnchanged();
        assert.equal(await copyStatus.textContent(), 'Копируем…');
        assert.deepEqual(await page.evaluate(() => window.__copyHaptics), []);
        await copyButton.click();
        await finishCopy(0);
        assert.equal(await copyStatus.textContent(), 'Копируем…');
        await finishCopy(1);
        assert.equal(await copyStatus.textContent(), '✓ скопировано');
        await copyButton.click();
        await finishCopy(2);
        await receiveUnchanged();
        assert.deepEqual(await page.evaluate(() => window.__clipboardWrites), Array(3).fill(walletAddress));
        await page.clock.fastForward(1300);
        assert.equal(await copyStatus.textContent(), '');
        report.checks.push(`${viewport.width}: receive address/QR survive pending, repeated and completed copies; truthful delayed success`);

        await copyButton.click();
        const hapticsBeforeFailure = await page.evaluate(() => window.__copyHaptics.length);
        await finishCopy(3, false);
        assert.ok((await copyStatus.textContent()).includes('Не удалось скопировать'));
        assert.equal(await page.evaluate(() => window.__copyHaptics.length), hapticsBeforeFailure);
        await receiveUnchanged();
        await copyButton.scrollIntoViewIfNeeded();
        await page.screenshot({path: path.join(outputDir, `${viewport.width}-receive-copy-failure.png`)});
        await copyButton.click();
        await finishCopy(4);
        assert.equal(await copyStatus.textContent(), '✓ скопировано');
        await receiveUnchanged();
        report.checks.push(`${viewport.width}: clipboard rejection shows retry feedback without haptic; explicit retry succeeds`);

        await copyButton.click();
        await page.locator('#w-act-recv').click();
        assert.equal(await copyStatus.textContent(), '');
        const hapticsBeforeClose = await page.evaluate(() => window.__copyHaptics.length);
        await finishCopy(5);
        assert.equal(await copyStatus.textContent(), '');
        assert.equal(await page.evaluate(() => window.__copyHaptics.length), hapticsBeforeClose);
        await page.locator('#w-act-recv').click();
        await page.waitForFunction(() => !document.getElementById('w-copy').disabled);
        await receiveUnchanged();
        await page.evaluate(() => Object.defineProperty(navigator, 'clipboard', {configurable: true, value: undefined}));
        await copyButton.click();
        assert.ok((await copyStatus.textContent()).includes('Не удалось скопировать'));
        await receiveUnchanged();
        report.checks.push(`${viewport.width}: closed receive view ignores late completion; missing clipboard reports failure`);

        // Exercise actual headless Chrome clipboard, isolated to this fresh
        // unprivileged context, in addition to deterministic async fault cases.
        await page.evaluate(() => {delete navigator.clipboard;});
        await context.grantPermissions(['clipboard-read', 'clipboard-write']);
        await copyButton.click();
        await page.waitForFunction(() => document.getElementById('w-copy-status').textContent === '✓ скопировано');
        assert.equal(await page.evaluate(() => navigator.clipboard.readText()), walletAddress);
        await copyButton.click();
        assert.equal(await page.evaluate(() => navigator.clipboard.readText()), walletAddress);
        await receiveUnchanged();
        assert.equal(await receiveAddress.evaluate(el => el.scrollWidth <= el.clientWidth), true);
        await page.screenshot({path: path.join(outputDir, `${viewport.width}-receive-copy-success.png`)});
        report.checks.push(`${viewport.width}: real Chrome clipboard contains exact address after two taps; address wraps without clipping`);

        holdReceive = true;
        async function openHeldReceive() {
            const requested = new Promise(resolve => {receiveRequested = resolve;});
            await page.locator('#w-act-recv').click();
            await requested;
            assert.equal(await copyButton.isDisabled(), true);
            assert.equal(await receiveAddress.textContent(), '');
            assert.equal(await page.locator('#w-qr').getAttribute('src'), null);
        }
        async function fulfillReceive(index, address) {
            const response = page.waitForResponse(r => r.url().endsWith('/api/wallet/receive'));
            await pendingReceiveRoutes[index].fulfill({contentType: 'application/json',
                body: JSON.stringify({ok: true, address})});
            await (await response).finished();
            // Let the fetch JSON continuation settle before inspecting the DOM.
            await page.evaluate(() => new Promise(resolve => requestAnimationFrame(resolve)));
        }
        await page.locator('#w-act-recv').click(); // close populated panel
        await openHeldReceive();
        await page.locator('#w-act-send').click();
        await fulfillReceive(0, walletAddress);
        assert.equal(await page.locator('#w-recv').isVisible(), false);
        assert.equal(await receiveAddress.textContent(), '');
        assert.equal(await copyButton.isDisabled(), true);
        report.checks.push(`${viewport.width}: receive loading clears prior address/QR and disables copy; send ignores late response`);
        await openHeldReceive();
        await page.locator('#w-act-recv').click();
        await openHeldReceive();
        const newAddress = 'EQ' + 'B'.repeat(46);
        await fulfillReceive(2, newAddress);
        await fulfillReceive(1, walletAddress);
        assert.equal(await receiveAddress.textContent(), newAddress);
        assert.equal(await copyButton.isEnabled(), true);
        await copyButton.click();
        assert.equal(await page.evaluate(() => navigator.clipboard.readText()), newAddress);
        await page.locator('#w-act-recv').click();
        await openHeldReceive();
        await page.evaluate(address => walletRender([{chain: 'TON', address, balance: null}]), newAddress);
        await fulfillReceive(3, walletAddress);
        assert.equal(await page.locator('#w-recv').isVisible(), false);
        assert.equal(await receiveAddress.textContent(), '');
        assert.equal(await copyButton.isDisabled(), true);
        report.checks.push(`${viewport.width}: reordered receive response cannot replace new address; wallet change invalidates pending receive`);

        // Fresh payment instructions must never inherit another order's data.
        await page.clock.pauseAt(new Date((await page.evaluate(() => Date.now())) + 1000));
        await page.locator('#tab-exchange').click();
        await page.locator('#deal-side [data-side="buy"]').click();
        await page.evaluate(() => {
            window.__paymentLinks = [];
            Telegram.WebApp.openLink = url => window.__paymentLinks.push(url);
            window.__paymentJsonDone = 0;
            window.__paymentAborted = 0;
            const originalFetch = window.fetch;
            window.fetch = async (...args) => {
                let response;
                try { response = await originalFetch(...args); }
                catch (error) {
                    if (String(args[0]).startsWith('/api/order/synthetic-') && error.name === 'AbortError') window.__paymentAborted++;
                    throw error;
                }
                if (String(args[0]).startsWith('/api/order/synthetic-')) {
                    const originalJson = response.json.bind(response);
                    response.json = async () => {
                        const data = await originalJson();
                        window.__paymentJsonDone++;
                        return data;
                    };
                }
                return response;
            };
        });
        const paymentQr = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=';
        async function startPayment(id, image, amount, requisites, url = 'https://payment.invalid/' + id) {
            const requested = new Promise(resolve => {orderRequested = resolve;});
            await page.evaluate(args => startOrderTracking(...args), [id, url, 'TON', image, amount, requisites]);
            await requested;
            orderRequested = null;
            return pendingOrderRoutes.length - 1;
        }
        async function paymentReply(index, data) {
            const before = await page.evaluate(() => window.__paymentJsonDone);
            await pendingOrderRoutes[index].fulfill({contentType: 'application/json', body: JSON.stringify(data)});
            await page.waitForFunction(count => window.__paymentJsonDone > count, before);
        }
        async function freshPayment(id) {
            assert.equal(await page.locator('#pay-card-title').textContent(), 'Заявка #' + id);
            assert.equal(await page.locator('#pay-qr-wrap').isVisible(), false);
            assert.equal(await page.locator('#pay-qr').getAttribute('src'), null);
            assert.equal(await page.locator('#pay-amount-line').textContent(), '');
            assert.equal(await page.locator('#pay-timer').textContent(), '15:00');
            assert.equal(await page.locator('#pay-open-btn').isEnabled(), true);
            assert.equal(await page.locator('#pay-open-btn').isVisible(), true);
            assert.equal(await page.locator('#pay-open-btn').textContent(), '💳 Оплатить');
            assert.equal(await page.locator('#pay-check-btn').textContent(), '🔄 Проверить статус');
            assert.equal(await page.locator('#exchange-steps').isVisible(), true);
            assert.ok((await page.locator('#exchange-steps').textContent()).includes('Ожидание оплаты'));
            assert.ok((await page.locator('#pay-req').textContent()).includes('+70000000002'));
            assert.ok(!(await page.locator('#pay-req').textContent()).includes('+70000000001'));
            assert.match(await page.locator('#pay-req').textContent(), /2\s000/);
        }
        const firstOrder = await startPayment('synthetic-qr-a', paymentQr, 1000, {phone: '+70000000001'});
        await page.evaluate(() => {
            window.__oldPaymentOpen = document.getElementById('pay-open-btn').onclick;
            window.__oldPaymentCheck = document.getElementById('pay-check-btn').onclick;
        });
        assert.equal(await page.locator('#pay-qr-wrap').isVisible(), true);
        const secondOrder = await startPayment('synthetic-text-b', null, 2000, {phone: '+70000000002'});
        await freshPayment('synthetic-text-b');
        await page.locator('#pay-card').scrollIntoViewIfNeeded();
        assert.equal(await page.locator('#pay-card').evaluate(el => el.scrollWidth <= el.clientWidth), true);
        await page.screenshot({path: path.join(outputDir, `${viewport.width}-payment-text-fresh.png`)});
        await paymentReply(firstOrder, {status: 'sent', tx_url: 'https://explorer.invalid/old'});
        await freshPayment('synthetic-text-b');
        const requestsBefore = pendingOrderRoutes.length;
        await page.evaluate(() => {window.__oldPaymentOpen(); window.__oldPaymentCheck();});
        assert.equal(pendingOrderRoutes.length, requestsBefore);
        assert.deepEqual(await page.evaluate(() => window.__paymentLinks), []);
        await page.locator('#pay-open-btn').click();
        assert.deepEqual(await page.evaluate(() => window.__paymentLinks), ['https://payment.invalid/synthetic-text-b']);
        await paymentReply(secondOrder, {status: 'paid'});
        assert.equal(await page.locator('#pay-open-btn').isVisible(), false);
        const thirdOrder = await startPayment('synthetic-text-c', null, 2000, {phone: '+70000000002'});
        await freshPayment('synthetic-text-c');
        report.checks.push(`${viewport.width}: QR-to-text clears QR/amount; obsolete status and captured actions ignored; paid-to-new restores controls`);

        await paymentReply(thirdOrder, {status: 'cancelled'});
        const fourthOrder = await startPayment('synthetic-link-d', null, 2000, {payment_link: 'https://payment.invalid/link-d'});
        assert.equal(await page.locator('#pay-open-btn').isVisible(), true);
        assert.ok((await page.locator('#pay-open-btn').textContent()).includes('страницу'));
        await paymentReply(fourthOrder, {status: 'pending', receipt: 'sent'});
        const fifthOrder = await startPayment('synthetic-qr-e', paymentQr, null, null);
        assert.equal(await page.locator('#pay-qr-wrap').isVisible(), true);
        assert.equal(await page.locator('#pay-amount-line').textContent(), '');
        assert.equal(await page.locator('#pay-req').textContent(), '');
        assert.ok((await page.locator('#pay-open-btn').textContent()).includes('банка'));
        await paymentReply(fifthOrder, {status: 'expired'});
        assert.equal(await page.locator('#pay-open-btn').isVisible(), false);
        const sixthOrder = await startPayment('synthetic-text-f', null, 2000, {phone: '+70000000002'});
        await freshPayment('synthetic-text-f');
        await paymentReply(sixthOrder, {status: 'pending'});
        report.checks.push(`${viewport.width}: cancelled/receipt/expired-to-new restores instructions; link/QR labels and missing amount are isolated`);
        const emptyOrder = await startPayment('synthetic-empty-g', null, null, null, null);
        assert.equal(await page.locator('#pay-open-btn').isVisible(), false);
        assert.equal(await page.locator('#pay-open-btn').isDisabled(), true);
        assert.equal(await page.locator('#pay-req').textContent(), '');
        assert.equal(await page.locator('#pay-qr').getAttribute('src'), null);
        await paymentReply(emptyOrder, {status: 'cancelled'});
        report.checks.push(`${viewport.width}: absent payment destination clears prior data and exposes no payment action`);
        const abortsBefore = await page.evaluate(() => window.__paymentAborted);
        const timeoutOrder = await startPayment('synthetic-timeout-h', null, 2000, {phone: '+70000000002'});
        await page.clock.runFor(10001);
        await page.waitForFunction(count => window.__paymentAborted > count, abortsBefore);
        // The interval may start a fresh read at the same 10 s boundary.
        if (pendingOrderRoutes.length > timeoutOrder + 1) {
            await paymentReply(pendingOrderRoutes.length - 1, {status: 'pending'});
        }
        const requestedAgain = new Promise(resolve => {orderRequested = resolve;});
        await page.locator('#pay-check-btn').click();
        await requestedAgain;
        orderRequested = null;
        await paymentReply(pendingOrderRoutes.length - 1, {status: 'paid'});
        assert.ok((await page.locator('#pay-card-title').textContent()).includes('оплачена'));
        report.checks.push(`${viewport.width}: native fetch aborts stalled status request; manual check recovers to paid`);

        // Payment copy has its own lifetime and feedback. Exercise the actual
        // listener with delayed/rejected clipboard writes and literal data.
        const literalRequisites = ' O\'Brien "double" `tick` ${literal} <script>window.__requisitesInjected = 1</script> & 42 ';
        const requisitesButton = page.locator('#pay-req-copy');
        const requisitesFeedback = page.locator('#pay-req-copy-status');
        const requisitesValue = page.locator('#pay-req-value');
        async function installRequisitesClipboard() {
            await page.evaluate(() => {
                window.__requisitesWrites = [];
                window.__requisitesPending = [];
                window.__requisitesContents = 'previous clipboard value';
                window.__requisitesClipboard = {writeText(value) {
                    window.__requisitesWrites.push(value);
                    return new Promise((resolve, reject) => window.__requisitesPending.push({
                        resolve: () => {window.__requisitesContents = value; resolve();}, reject}));
                }};
                Object.defineProperty(navigator, 'clipboard', {configurable: true, value: window.__requisitesClipboard});
            });
        }
        async function finishRequisitesCopy(index, success = true) {
            await page.evaluate(({index, success}) => {
                const pending = window.__requisitesPending[index];
                if (success) pending.resolve(); else pending.reject(new Error('synthetic clipboard denial'));
            }, {index, success});
        }
        async function requisitesPreserved(value) {
            assert.equal(await requisitesValue.textContent(), value);
            assert.equal(await requisitesButton.textContent(), 'Копировать');
            assert.equal(await page.locator('#pay-req script').count(), 0);
            assert.equal(await page.evaluate(() => window.__requisitesInjected), undefined);
            assert.equal(await page.locator('#pay-card').evaluate(el => el.scrollWidth <= el.clientWidth), true);
        }
        await startPayment('synthetic-copy-literal', null, 2000, {phone: literalRequisites,
            bank_name: 'Synthetic bank', recipient: 'Synthetic recipient'});
        assert.equal(await requisitesButton.getAttribute('type'), 'button');
        assert.equal(await requisitesButton.getAttribute('onclick'), null);
        assert.equal(await requisitesButton.getAttribute('aria-describedby'), 'pay-req-copy-status');
        assert.equal(await requisitesFeedback.getAttribute('role'), 'status');
        assert.equal(await requisitesFeedback.getAttribute('aria-live'), 'polite');
        assert.equal(await requisitesFeedback.getAttribute('aria-atomic'), 'true');
        await installRequisitesClipboard();
        await requisitesButton.focus();
        await page.keyboard.press('Enter');
        assert.equal(await requisitesFeedback.textContent(), 'Копируем…');
        assert.equal(await requisitesButton.isDisabled(), true);
        await requisitesButton.evaluate(el => el.dispatchEvent(new Event('click')));
        assert.deepEqual(await page.evaluate(() => window.__requisitesWrites), [literalRequisites]);
        await requisitesPreserved(literalRequisites);
        await finishRequisitesCopy(0);
        assert.equal(await requisitesFeedback.textContent(), '✓ Реквизиты скопированы');
        assert.equal(await requisitesButton.isEnabled(), true);
        await requisitesPreserved(literalRequisites);
        await page.screenshot({path: path.join(outputDir, `${viewport.width}-payment-copy-success.png`)});
        report.checks.push(`${viewport.width}: literal requisites remain text; keyboard copy awaits completion; duplicate dispatch is inert; accessible separate status fits viewport`);

        await requisitesButton.click();
        const copyHapticsBeforeFailure = await page.evaluate(() => window.__copyHaptics.length);
        await finishRequisitesCopy(1, false);
        assert.ok((await requisitesFeedback.textContent()).includes('Не удалось скопировать'));
        assert.ok((await requisitesFeedback.textContent()).includes('вручную'));
        assert.equal(await page.evaluate(() => window.__copyHaptics.length), copyHapticsBeforeFailure);
        await requisitesPreserved(literalRequisites);
        await page.screenshot({path: path.join(outputDir, `${viewport.width}-payment-copy-failure.png`)});
        await requisitesButton.click(); await finishRequisitesCopy(2);
        assert.equal(await requisitesFeedback.textContent(), '✓ Реквизиты скопированы');
        await page.evaluate(() => Object.defineProperty(navigator, 'clipboard', {configurable: true, value: undefined}));
        await requisitesButton.click();
        assert.ok((await requisitesFeedback.textContent()).includes('Не удалось скопировать'));
        assert.equal(await requisitesButton.isEnabled(), true);
        await requisitesPreserved(literalRequisites);
        report.checks.push(`${viewport.width}: rejected and unavailable clipboard give manual-copy feedback; retry recovers with exact preserved requisites`);

        await installRequisitesClipboard();
        for (const mode of ['new-order', 'same-id', 'empty-reset']) {
            const id = 'synthetic-copy-' + mode;
            await startPayment(id, null, 2000, {phone: '+70000000003'});
            await requisitesButton.click();
            const pendingIndex = await page.evaluate(() => window.__requisitesPending.length - 1);
            await page.evaluate(() => {window.__oldRequisitesButton = document.getElementById('pay-req-copy');});
            await startPayment(mode === 'same-id' ? id : id + '-next', null, 3000,
                mode === 'empty-reset' ? null : {card_number: '4111 1111 1111 1111'});
            const writesBefore = await page.evaluate(() => window.__requisitesWrites.length);
            await page.evaluate(() => window.__oldRequisitesButton.dispatchEvent(new Event('click')));
            assert.equal(await page.evaluate(() => window.__requisitesWrites.length), writesBefore);
            if (mode !== 'empty-reset') {
                assert.equal(await requisitesButton.isDisabled(), true);
                assert.equal(await requisitesFeedback.textContent(), 'Завершается предыдущее копирование…');
                await requisitesButton.evaluate(el => el.dispatchEvent(new Event('click')));
                assert.equal(await page.evaluate(() => window.__requisitesWrites.length), writesBefore,
                    'current view must not overlap a previous native clipboard write');
                await requisitesPreserved('4111 1111 1111 1111');
                if (viewport.width === 320 && mode === 'new-order') {
                    await requisitesButton.scrollIntoViewIfNeeded();
                    await page.screenshot({path: path.join(outputDir, '320-payment-copy-waiting.png')});
                }
            }
            await finishRequisitesCopy(pendingIndex, mode !== 'same-id');
            if (mode === 'empty-reset') {
                assert.equal(await requisitesFeedback.count(), 0);
                assert.equal(await page.locator('#pay-req').textContent(), '');
            } else {
                assert.equal(await requisitesFeedback.textContent(), '');
                await requisitesPreserved('4111 1111 1111 1111');
                assert.equal(await requisitesButton.isEnabled(), true);
                assert.equal(await page.evaluate(() => window.__requisitesWrites.length), writesBefore,
                    'old completion must not enqueue an automatic new copy');
                await requisitesButton.click();
                await finishRequisitesCopy(pendingIndex + 1);
                assert.equal(await page.evaluate(() => window.__requisitesContents), '4111 1111 1111 1111');
                assert.equal(await requisitesFeedback.textContent(), '✓ Реквизиты скопированы');
            }
            report.checks.push(`${viewport.width}: ${mode} invalidates stale feedback and serializes native writes until explicit current-view copy`);
        }
        await startPayment('synthetic-copy-waiting-a', null, 2000, {phone: 'value-A'});
        await requisitesButton.click();
        const waitingIndex = await page.evaluate(() => window.__requisitesPending.length - 1);
        const waitingOrder = await startPayment('synthetic-copy-waiting-b', null, 2000, {phone: 'value-B'});
        assert.equal(await requisitesButton.isDisabled(), true);
        await paymentReply(waitingOrder, {status: 'paid'});
        await finishRequisitesCopy(waitingIndex);
        assert.equal(await requisitesFeedback.count(), 0);
        assert.equal(await page.locator('#pay-req').textContent(), '');
        report.checks.push(`${viewport.width}: terminal state during prior clipboard wait cannot revive the new view's copy controls`);
        for (const terminal of ['paid', 'sent', 'cancelled', 'expired', 'failed', 'receipt', 'dead']) {
            const order = await startPayment('synthetic-copy-terminal-' + terminal, null, 2000, {phone: '+70000000004'});
            await requisitesButton.click();
            const pendingIndex = await page.evaluate(() => window.__requisitesPending.length - 1);
            await page.evaluate(() => {window.__oldRequisitesButton = document.getElementById('pay-req-copy');});
            await paymentReply(order, {status: ['receipt', 'dead'].includes(terminal) ? 'pending' : terminal,
                receipt: terminal === 'receipt' ? 'sent' : '', dead: terminal === 'dead'});
            const writesBefore = await page.evaluate(() => window.__requisitesWrites.length);
            await page.evaluate(() => window.__oldRequisitesButton.dispatchEvent(new Event('click')));
            await finishRequisitesCopy(pendingIndex);
            assert.equal(await page.evaluate(() => window.__requisitesWrites.length), writesBefore);
            assert.equal(await requisitesFeedback.count(), 0);
            assert.equal(await page.locator('#pay-req').textContent(), '');
            assert.equal(await page.locator('#pay-req').isVisible(), false);
        }
        report.checks.push(`${viewport.width}: paid/sent/cancelled/expired/failed/receipt/dead transitions discard pending copy and stale controls`);

        // Restore the isolated browser's real clipboard to verify byte-for-byte
        // values across both supported text-requisites paths after repeated taps.
        await page.evaluate(() => {delete navigator.clipboard;});
        for (const kind of ['phone', 'card_number']) {
            await startPayment('synthetic-copy-native-' + kind, null, 2000, {[kind]: literalRequisites});
            for (let attempt = 0; attempt < 2; attempt++) {
                await requisitesButton.click();
                await page.waitForFunction(() => document.getElementById('pay-req-copy-status').textContent === '✓ Реквизиты скопированы');
                assert.equal(await page.evaluate(() => navigator.clipboard.readText()), literalRequisites);
                await requisitesPreserved(literalRequisites);
            }
        }
        report.checks.push(`${viewport.width}: real Chrome clipboard preserves spaces, quotes, backticks and script-shaped text for phone/card repeated copies`);
        await context.close();
        }
        assert.equal(report.writerAttempts.length, 9);
        assert.equal(report.walletPreparations.length, 24);
        assert.equal(report.signingAttempts.length, 6);
        assert.deepEqual(report.pageErrors, []);
        report.result = 'PASS';
    } catch (error) {
        // Keep evidence from real actionability failures before closing Chrome;
        // never compensate for a failed interaction with force or longer waits.
        if (activePage && !activePage.isClosed()) {
            report.failureDom = await activePage.evaluate(() => ({
                focused: document.activeElement?.id,
                elements: ['exchange-review', 'exchange-review-ack', 'exchange-review-confirm', 'pay-req-copy']
                    .map(id => {
                        const el = document.getElementById(id);
                        if (!el) return {id, absent: true};
                        const rect = el.getBoundingClientRect();
                        const style = getComputedStyle(el);
                        return {id, text: el.textContent, disabled: el.disabled, checked: el.checked,
                            display: style.display, visibility: style.visibility,
                            bounds: {x: rect.x, y: rect.y, width: rect.width, height: rect.height}};
                    }),
            })).catch(() => ({unavailable: true}));
            await activePage.screenshot({path: path.join(outputDir, 'failure.png')}).catch(() => {});
        }
        throw error;
    } finally {
        await browser.close();
    }
}
main().catch(error => { report.result = 'FAIL'; report.failure = error.message; report.failureStack = error.stack;
    process.exitCode = 1;
}).finally(() => fs.writeFileSync(path.join(outputDir, 'report.json'),
    JSON.stringify(report, null, 2) + '\n'));
