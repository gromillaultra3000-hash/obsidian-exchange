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
    writerAttempts: [], blockedRequests: [], pageErrors: []};
fs.mkdirSync(outputDir, {recursive: true});

async function main() {
    assert.notEqual(process.getuid(), 0, 'browser must run as non-root');
    const browser = await chromium.launch({executablePath: '/opt/google/chrome/chrome',
        chromiumSandbox: true, headless: true});
    report.browserVersion = browser.version();
    try {
        for (const viewport of [{width: 320, height: 568}, {width: 390, height: 844},
                                {width: 1280, height: 800}]) {
        const context = await browser.newContext({viewport,
            serviceWorkers: 'block', locale: 'ru-RU'});
        await context.addInitScript(() => {
            window.Telegram = {WebApp: {initData: '', initDataUnsafe: {},
                expand() {}, ready() {}, onEvent() {},
                setHeaderColor() {}, setBackgroundColor() {}, setBottomBarColor() {}}};
        });
        await context.route('**/*', async route => {
            const req = route.request();
            const url = new URL(req.url());
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
        await context.close();
        }
        assert.equal(report.writerAttempts.length, 9);
        assert.deepEqual(report.pageErrors, []);
        report.result = 'PASS';
    } finally {
        await browser.close();
    }
}
main().catch(error => { report.result = 'FAIL'; report.failure = error.message;
    process.exitCode = 1;
}).finally(() => fs.writeFileSync(path.join(outputDir, 'report.json'),
    JSON.stringify(report, null, 2) + '\n'));
