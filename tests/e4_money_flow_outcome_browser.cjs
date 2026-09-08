'use strict';
// Exact shipped Mini App, native browser fetch/JSON, synthetic transport only.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const {chromium} = require('playwright-core');
const [sourcePath, outputDir] = process.argv.slice(2);
const source = fs.readFileSync(sourcePath, 'utf8');
const hash = value => crypto.createHash('sha256').update(value).digest('hex');
const origin = 'https://outcome.invalid';
const recipient = 'bc1' + 'q'.repeat(87);
const literalRejection = '<img src=x onerror="window.__injected=true"> Synthetic rejection';
const report = {schemaVersion: 'e4-money-flow-outcome-browser.v1', sourceSha256: hash(source),
    runnerSha256: hash(fs.readFileSync(__filename)), playwrightVersion: require('playwright-core/package.json').version,
    checks: [], requests: [], externalRequestsDenied: [], unexpectedWrites: [], pageErrors: []};
const modes = ['lost-response', 'truncated-json', 'null-json', 'gateway-502', 'malformed-success', 'timeout-408', 'conflict-409', 'contradictory-403', 'empty-400', 'rejection-400', 'rejection-ok-false', 'success'];
const rates = {BTC: 5000000, TON: 200, offerings: [{code: 'BTC', networks: [{code: 'MAINNET', label: 'Bitcoin'}]}]};
const sellOptions = {coins: [{code: 'BTC', label: 'Bitcoin', rate: 4900000, market: 5000000, min: .0001, network: 'MAINNET'}],
    fee_label: '2%', payout_ways: [{code: 'sbp', label: 'СБП', needs_bank: true, needs_name: true}],
    payout_banks: [{code: 'test-bank', label: 'Тестовый банк'}]};
fs.mkdirSync(outputDir, {recursive: true});

async function main() {
    assert.notEqual(process.getuid(), 0, 'Chromium must run as non-root');
    const browser = await chromium.launch({executablePath: '/opt/google/chrome/chrome', chromiumSandbox: true, headless: true});
    report.browserVersion = browser.version();
    let activePage;
    try {
        for (const viewport of [{width: 320, height: 568}, {width: 390, height: 844}]) {
            const context = await browser.newContext({viewport, serviceWorkers: 'block', locale: 'ru-RU'});
            let scenario = null;
            await context.addInitScript(() => {
                window.__openedPaymentLinks = [];
                window.Telegram = {WebApp: {initData: '', initDataUnsafe: {}, expand() {}, ready() {}, onEvent() {},
                    openLink(url) { window.__openedPaymentLinks.push(url); },
                    setHeaderColor() {}, setBackgroundColor() {}, setBottomBarColor() {}}};
            });
            await context.route('**/*', async route => {
                const req = route.request(), url = new URL(req.url());
                if (url.origin === origin && req.method() === 'GET' && url.pathname === '/webapp') {
                    return route.fulfill({contentType: 'text/html', body: source});
                }
                if (url.origin === origin && req.method() === 'POST'
                        && ['/api/create_order', '/api/sell/create'].includes(url.pathname)) {
                    assert.ok(scenario, 'POST requires a declared case');
                    report.requests.push({width: viewport.width, ...scenario, path: url.pathname, method: req.method(), payload: req.postDataJSON()});
                    if (scenario.mode === 'lost-response') return route.abort('failed');
                    const rejection = {ok: false, detail: literalRejection, error: literalRejection};
                    let status = 200, response;
                    if (scenario.mode === 'truncated-json') response = '{"ok":';
                    else if (scenario.mode === 'null-json') response = 'null';
                    else if (scenario.mode === 'gateway-502') {status = 502; response = JSON.stringify({detail: 'Synthetic gateway failure'});}
                    else if (scenario.mode === 'malformed-success') response = JSON.stringify({ok: true});
                    else if (scenario.mode === 'timeout-408') {status = 408; response = JSON.stringify({detail: 'timeout'});}
                    else if (scenario.mode === 'conflict-409') {status = 409; response = JSON.stringify({detail: 'conflict'});}
                    else if (scenario.mode === 'contradictory-403') {status = 403; response = JSON.stringify({ok: true, order_id: 42, sell_id: 42});}
                    else if (scenario.mode === 'empty-400') {status = 400; response = '{}';}
                    else if (scenario.mode.startsWith('rejection')) {status = scenario.mode === 'rejection-400' ? 400 : 200; response = JSON.stringify(rejection);}
                    else response = JSON.stringify(scenario.action === 'buy'
                        ? {ok: true, order_id: 101, payment_url: '/pay/synthetic-only'}
                        : {ok: true, sell_id: 202, amount: .01, currency: 'BTC', network: 'MAINNET',
                           address: 'synthetic-deposit-only', rub: 49000, method_label: 'СБП', phone: '***0000', bank: 'Тестовый банк'});
                    return route.fulfill({status, contentType: 'application/json', body: response});
                }
                if (req.method() !== 'GET') {
                    report.unexpectedWrites.push({path: url.pathname, method: req.method()});
                    return route.abort('blockedbyclient');
                }
                if (url.origin === origin) {
                    const fixtures = {'/api/rates': rates, '/api/sell/options': sellOptions,
                        '/api/history': [], '/api/sell/pending': {items: []},
                        '/api/order/101': {order_id: 101, status: 'pending', receipt_state: 'absent'},
                        '/api/wallet/links': {wallets: []}, '/api/wallet/history': {items: []}, '/api/wallet/dues': {dues: []}};
                    return route.fulfill({contentType: 'application/json', body: JSON.stringify(fixtures[url.pathname] || {})});
                }
                report.externalRequestsDenied.push(url.origin + url.pathname);
                return route.abort('blockedbyclient');
            });
            const page = await context.newPage(); activePage = page;
            page.setDefaultTimeout(5000);
            page.on('pageerror', error => report.pageErrors.push(error.message));
            for (const action of ['buy', 'sell']) for (const mode of modes) {
                scenario = {action, mode};
                const before = report.requests.length;
                await page.goto(origin + '/webapp', {waitUntil: 'load'});
                await page.clock.install();
                await page.locator('#tab-exchange').click();
                let submit, result;
                if (action === 'buy') {
                    await page.locator('#currency').selectOption('BTC');
                    await page.locator('#amount').fill('12500');
                    await page.locator('#address').fill(recipient);
                    submit = page.locator('#create-order'); result = page.locator('#exchange-result');
                } else {
                    await page.locator('#deal-side [data-side="sell"]').click();
                    await page.locator('#sell-currency').selectOption('BTC');
                    await page.locator('#sell-amount').fill('0.01');
                    await page.locator('#sell-phone').fill('+7 000 000-00-00');
                    await page.locator('#sell-bank').selectOption('test-bank');
                    await page.locator('#sell-name').fill('Тестовый Получатель');
                    submit = page.locator('#sell-submit'); result = page.locator('#sell-result');
                }
                await submit.click();
                const modal = page.locator('#exchange-review'), ack = page.locator('#exchange-review-ack'), confirm = page.locator('#exchange-review-confirm');
                await modal.waitFor({state: 'visible'});
                assert.equal(await ack.isChecked(), false);
                assert.equal(await confirm.isDisabled(), true);
                assert.equal(report.requests.length, before);
                const summary = await modal.innerText();
                for (const item of ['ObsidianExchange', 'private lane', 'без KYC', 'Custody', 'Комиссия']) assert.ok(summary.toLowerCase().includes(item.toLowerCase()), item);
                assert.ok(summary.includes(action === 'buy' ? recipient : '70000000000'));
                await page.keyboard.press('Enter');
                assert.equal(report.requests.length, before, 'Enter at review title does not submit');
                if (mode === 'lost-response') {
                    await page.locator('#exchange-review-cancel').click();
                    assert.equal(report.requests.length, before);
                    await submit.click();
                    assert.equal(await ack.isChecked(), false);
                }
                await ack.check();
                assert.equal(await confirm.isEnabled(), true);
                await confirm.click();
                await page.waitForFunction(() => document.getElementById('exchange-review').style.display !== 'flex');
                if (mode === 'success') {
                    await page.locator(action === 'buy' ? '#pay-card' : '#sell-card').waitFor({state: 'visible'});
                    assert.ok((await page.locator(action === 'buy' ? '#pay-card-title' : '#sell-card-title').textContent()).includes(action === 'buy' ? '101' : '202'));
                    if (action === 'buy') assert.equal(await page.evaluate(() => localStorage.getItem('lastAddress_BTC_MAINNET')), recipient);
                    else assert.equal(await page.locator('#sell-pay-btn').isVisible(), false);
                    assert.deepEqual(await page.evaluate(() => window.__openedPaymentLinks),
                        action === 'buy' ? ['/pay/synthetic-only'] : []);
                } else {
                    const unknown = !mode.startsWith('rejection');
                    await page.waitForFunction(({id, unknown}) => document.getElementById(id).textContent.includes(unknown ? 'Она могла быть создана' : 'Synthetic rejection'),
                        {id: action === 'buy' ? 'exchange-result' : 'sell-result', unknown});
                    const text = await result.innerText();
                    if (unknown) {
                        for (const phrase of ['Не отправляйте заявку повторно', 'не переводите деньги повторно', '«Активность»', 'поддержку']) assert.ok(text.includes(phrase));
                        if (action === 'sell') assert.ok(text.includes('список заявок на продажу'));
                        assert.ok(!text.includes('заявка не создана') && !text.includes('Попробуйте ещё раз'));
                    } else {
                        assert.ok(text.includes(literalRejection));
                        assert.equal(await result.locator('img').count(), 0);
                        assert.equal(await page.evaluate(() => window.__injected === true), false);
                    }
                    assert.equal(await page.locator('#pay-card').isVisible(), false);
                    assert.equal(await page.locator('#sell-card').isVisible(), false);
                    assert.equal(await page.evaluate(() => localStorage.getItem('lastAddress_BTC_MAINNET')), null);
                    assert.deepEqual(await page.evaluate(() => window.__openedPaymentLinks), []);
                    assert.equal(await submit.isDisabled(), false);
                    if (viewport.width === 320 && ['lost-response', 'truncated-json'].includes(mode)) {
                        await result.scrollIntoViewIfNeeded();
                        await page.screenshot({path: path.join(outputDir, `320-${action}-${mode}.png`), fullPage: true});
                    }
                }
                // A consumed/closed review cannot submit again, including while
                // transport has failed. Product callbacks and dispatch run intact.
                await confirm.evaluate(button => button.click());
                await page.clock.fastForward(3001);
                assert.equal(report.requests.length, before + 1, 'one acknowledged POST, no automatic repeat');
                const payload = report.requests.at(-1).payload;
                assert.equal(payload[action === 'buy' ? 'address' : 'phone'], action === 'buy' ? recipient : '70000000000');
                assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
                report.checks.push({width: viewport.width, action, mode, result: 'PASS',
                    acknowledgementRequired: true, postCount: 1, automaticResubmissions: 0,
                    resultText: (await result.textContent()).trim()});
                await page.evaluate(() => localStorage.clear());
            }
            await context.close();
        }
        assert.equal(report.checks.length, 48);
        assert.deepEqual(report.unexpectedWrites, []);
        assert.deepEqual(report.pageErrors, []);
        report.result = 'PASS';
    } catch (error) {
        report.result = 'FAIL'; report.error = error.stack;
        if (activePage && !activePage.isClosed()) await activePage.screenshot({path: path.join(outputDir, 'failure.png'), fullPage: true}).catch(() => {});
        process.exitCode = 1;
    } finally {
        await browser.close();
        fs.writeFileSync(path.join(outputDir, 'report.json'), JSON.stringify(report, null, 2) + '\n');
        console.log(JSON.stringify({result: report.result, checks: report.checks.length, requests: report.requests.length}));
    }
}
main().catch(error => {console.error(error); process.exitCode = 1;});
