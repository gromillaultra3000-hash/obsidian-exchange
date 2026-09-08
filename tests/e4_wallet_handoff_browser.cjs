'use strict';
// Exact page and review controls; native fetch, inert SDK settlement and API routes.
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), crypto = require('node:crypto');
const {chromium} = require('playwright-core');
const [sourcePath, output] = process.argv.slice(2), source = fs.readFileSync(sourcePath, 'utf8');
const hash = x => crypto.createHash('sha256').update(x).digest('hex');
const origin = 'https://wallet-handoff.invalid', address = 'EQ' + 'A'.repeat(46);
const request = {validUntil: 2000, messages: [{address, amount: '1250000000', payload: 'synthetic-not-a-boc'}]};
const report = {sourceSha256: hash(source), runnerSha256: hash(fs.readFileSync(__filename)),
    playwrightVersion: require('playwright-core/package.json').version, checks: [], unexpectedWrites: [], pageErrors: []};
fs.mkdirSync(output, {recursive: true});
async function main() {
    assert.notEqual(process.getuid(), 0);
    const browser = await chromium.launch({executablePath: '/opt/google/chrome/chrome', chromiumSandbox: true, headless: true});
    report.browserVersion = browser.version(); let page;
    try {
        for (const width of [320, 390]) {
            const context = await browser.newContext({viewport: {width, height: 844}, serviceWorkers: 'block'});
            let preparations = [], notifications = [];
            await context.addInitScript(() => {
                window.Telegram = {WebApp: {initData: '', initDataUnsafe: {}, expand() {}, ready() {}, onEvent() {}, setHeaderColor() {}, setBackgroundColor() {}, setBottomBarColor() {}}};
            });
            await context.route('**/*', async route => {
                const r = route.request(), u = new URL(r.url());
                if (u.origin !== origin) return route.abort();
                if (r.method() === 'GET' && u.pathname === '/webapp') return route.fulfill({contentType: 'text/html', body: source});
                if (r.method() === 'POST' && ['/api/wallet/transfer-request', '/api/wallet/send-request'].includes(u.pathname)) {
                    preparations.push({url: u.pathname, payload: r.postDataJSON()});
                    return route.fulfill({contentType: 'application/json', body: JSON.stringify({ok: true, sell_id: 42, address, amount: 1.25, marker: 'synthetic', request})});
                }
                if (r.method() === 'POST' && u.pathname === '/api/wallet/send-signed') {
                    notifications.push(r.postDataJSON());
                    return route.fulfill({contentType: 'application/json', body: '{"ok":true}'});
                }
                if (r.method() !== 'GET') {report.unexpectedWrites.push(u.pathname); return route.abort();}
                const fixtures = {'/api/history': [], '/api/wallet/links': {wallets: []}, '/api/wallet/dues': {dues: []},
                    '/api/rates': {BTC: 5000000, offerings: [{code: 'BTC', networks: [{code: 'MAINNET'}]}]}};
                return route.fulfill({contentType: 'application/json', body: JSON.stringify(fixtures[u.pathname] || {})});
            });
            page = await context.newPage(); page.setDefaultTimeout(5000);
            page.on('pageerror', e => report.pageErrors.push(e.message));
            const modal = page.locator('#exchange-review'), ack = page.locator('#exchange-review-ack');
            const confirm = page.locator('#exchange-review-confirm');
            async function start(action) {
                await page.evaluate(action => action === 'transfer' ? walletTransfer() : walletPay(42, document.getElementById('sell-pay-btn')), action);
            }
            for (const first of ['transfer', 'payment']) for (const second of ['transfer', 'payment']) for (const outcome of ['resolve', 'reject', 'sync-throw']) {
                preparations = []; notifications = [];
                await page.goto(origin + '/webapp', {waitUntil: 'load'}); await page.clock.install();
                await page.evaluate(({address, outcome}) => {
                    window.__signing = [];
                    tcUI = {sendTransaction(r) {
                        window.__signing.push(structuredClone(r));
                        if (outcome === 'sync-throw') throw new Error('Synthetic synchronous failure');
                        return new Promise((resolve, reject) => {window.__settle = {resolve, reject};});
                    }};
                    document.getElementById('w-to').value = address; document.getElementById('w-amount').value = '1.25';
                    document.getElementById('w-comment').value = 'synthetic';
                }, {address, outcome});
                await start(first); await modal.waitFor({state: 'visible'});
                assert.equal(await ack.isChecked(), false); assert.equal(await confirm.isDisabled(), true);
                await page.evaluate(() => {window.__staleConfirm = exchangeReviewCommit;});
                await ack.check(); await confirm.click(); await modal.waitFor({state: 'hidden'});
                await page.waitForFunction(() => window.__signing.length === 1);
                assert.deepEqual(await page.evaluate(() => window.__signing[0]), request);
                if (outcome !== 'sync-throw') {
                    for (let i = 0; i < 3; i++) await start(second);
                    await page.evaluate(() => window.__staleConfirm());
                    await page.evaluate(() => {closeExchangeReview(); invalidateExchangeReview();});
                    await page.clock.fastForward(120051);
                    await start(second);
                    assert.equal(preparations.length, 1); assert.equal(notifications.length, 0);
                    assert.equal(await page.evaluate(() => window.__signing.length), 1);
                    assert.equal(await modal.isVisible(), false);
                    const feedback = await page.locator(second === 'transfer' ? '#w-send-msg' : '#sell-pay-btn').textContent();
                    assert.ok(feedback.includes('Дождитесь ответа кошелька') && feedback.includes('Не повторяйте перевод'));
                    await page.evaluate(outcome => {
                        if (outcome === 'resolve') window.__settle.resolve({boc: 'synthetic-not-a-boc'});
                        else window.__settle.reject(new Error('Synthetic wallet failure'));
                    }, outcome);
                }
                await page.waitForFunction(() => walletHandoffPending === false);
                if (first === 'payment' && outcome === 'resolve') {
                    await page.waitForFunction(() => document.getElementById('sell-pay-btn').textContent.includes('Подписано'));
                    assert.deepEqual(notifications, [{sell_id: 42}]);
                } else assert.equal(notifications.length, 0);
                // Settlement never auto-retries. A fresh explicit action opens an
                // unchecked review and cancellation consumes no SDK invocation.
                assert.equal(preparations.length, 1); assert.equal(await page.evaluate(() => window.__signing.length), 1);
                await start(second); await modal.waitFor({state: 'visible'});
                assert.equal(await ack.isChecked(), false); assert.equal(await confirm.isDisabled(), true);
                assert.equal(preparations.length, 2);
                await page.locator('#exchange-review-cancel').click();
                await confirm.evaluate(b => b.click());
                assert.equal(await page.evaluate(() => window.__signing.length), 1);
                if (width === 320 && first === 'transfer' && second === 'payment' && outcome === 'reject')
                    await page.screenshot({path: path.join(output, '320-fresh-review-cancelled.png')});
                report.checks.push({width, first, second, outcome, result: 'PASS', sdkCalls: 1, automaticRetries: 0});
            }
            await context.close();
        }
        assert.equal(report.checks.length, 24); assert.deepEqual(report.pageErrors, []); assert.deepEqual(report.unexpectedWrites, []);
        report.result = 'PASS';
    } catch (e) {
        report.result = 'FAIL'; report.error = e.stack; process.exitCode = 1;
        if (page && !page.isClosed()) await page.screenshot({path: path.join(output, 'failure.png')}).catch(() => {});
    } finally {
        await browser.close(); fs.writeFileSync(path.join(output, 'report.json'), JSON.stringify(report, null, 2) + '\n');
        console.log(JSON.stringify({result: report.result, cases: report.checks.length, error: report.error}));
    }
}
main().catch(e => {console.error(e); process.exitCode = 1;});
