'use strict';
// Exact page and review controls; native fetch, inert SDK settlement and API routes.
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), crypto = require('node:crypto');
const {chromium} = require('playwright-core');
const [sourcePath, output] = process.argv.slice(2), source = fs.readFileSync(sourcePath, 'utf8');
const hash = x => crypto.createHash('sha256').update(x).digest('hex');
const origin = 'https://wallet-reentry.invalid', address = 'EQ' + 'A'.repeat(46);
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
                const fixtures = {'/api/history': [], '/api/wallet/links': {wallets: [{chain: 'TON', address, balance: null}]}, '/api/wallet/dues': {dues: [{sell_id: 42, amount: 1.25, currency: 'TON', marker: 'synthetic'}]},
                    '/api/rates': {BTC: 5000000, offerings: [{code: 'BTC', networks: [{code: 'MAINNET'}]}]}};
                return route.fulfill({contentType: 'application/json', body: JSON.stringify(fixtures[u.pathname] || {})});
            });
            page = await context.newPage(); page.setDefaultTimeout(5000);
            page.on('pageerror', e => report.pageErrors.push(e.message));
            const modal = page.locator('#exchange-review'), ack = page.locator('#exchange-review-ack');
            const confirm = page.locator('#exchange-review-confirm');
            async function setup(mode) {
                await page.evaluate(({address, mode}) => {
                    window.__signing = [];
                    tcUI = {sendTransaction(r) {
                        window.__signing.push(structuredClone(r));
                        if (mode === 'sync-throw') throw new Error('Synthetic synchronous failure');
                        if (mode === 'reload') return new Promise(() => {});
                        return Promise.reject(new Error('Synthetic ambiguous wallet failure'));
                    }};
                    document.getElementById('w-to').value = address;
                    document.getElementById('w-amount').value = '1.25';
                    document.getElementById('w-comment').value = 'synthetic';
                    walletRender([{chain: 'TON', address, balance: null}]);
                    walletDuesRender([{sell_id: 42, amount: 1.25, currency: 'TON', marker: 'synthetic'}]);
                }, {address, mode});
                await page.locator('#tab-wallet').click();
                await page.locator('#w-act-send').click();
            }
            async function open(action) {
                await page.locator(action === 'transfer' ? '#w-send-go' : '.wallet-pay').click();
                await modal.waitFor({state: 'visible'});
                assert.equal(await ack.isChecked(), false); assert.equal(await confirm.isDisabled(), true);
            }
            async function guidance(action) {
                const risk = await page.locator('#exchange-review-risk').innerText();
                for (const phrase of ['после перезагрузки', 'историю операций в подключённом кошельке', 'результат предыдущей попытки неясен', 'не повторяйте перевод']) assert.ok(risk.includes(phrase), phrase);
                if (action === 'payment') assert.ok(risk.includes('статус заявки'));
                await page.locator('#exchange-review-risk').scrollIntoViewIfNeeded();
                assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
            }
            for (const action of ['transfer', 'payment']) for (const mode of ['fresh', 'reload', 'reject', 'sync-throw']) {
                preparations = []; notifications = [];
                await page.goto(origin + '/webapp', {waitUntil: 'load'}); await page.clock.install(); await setup(mode);
                await open(action); await guidance(action);
                let discardedDocumentCalls = 0;
                if (mode === 'fresh') {
                    await page.locator('#exchange-review-cancel').click();
                    assert.equal(await page.evaluate(() => window.__signing.length), 0);
                } else {
                    await ack.check(); await confirm.click(); await modal.waitFor({state: 'hidden'});
                    await page.waitForFunction(() => window.__signing.length === 1);
                    assert.deepEqual(await page.evaluate(() => window.__signing[0]), request);
                    if (mode === 'reload') {
                        assert.equal(await page.evaluate(() => walletHandoffPending), true);
                        discardedDocumentCalls = 1;
                        await page.reload({waitUntil: 'load'}); await setup('reject');
                        assert.equal(await page.evaluate(() => walletHandoffPending), false, 'document lock is not durable');
                        await open(action); await guidance(action);
                        await page.screenshot({path: path.join(output, `${width}-${action}-reentry-review.png`)});
                        await page.locator('#exchange-review-cancel').click();
                        assert.equal(await page.evaluate(() => window.__signing.length), 0, 're-entry review/cancel never signs');
                    } else {
                        await page.waitForFunction(() => walletHandoffPending === false);
                        const feedback = page.locator(action === 'transfer' ? '#w-send-msg' : '.wallet-pay');
                        const text = await feedback.innerText();
                        for (const phrase of ['Исход перевода неизвестен', 'Перевод мог быть отправлен', 'историю операций в подключённом кошельке', 'не повторяйте перевод']) assert.ok(text.includes(phrase), phrase);
                        if (action === 'payment') assert.ok(text.includes('статус заявки'));
                        await feedback.scrollIntoViewIfNeeded();
                        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
                        await page.screenshot({path: path.join(output, `${width}-${action}-${mode}.png`)});
                        assert.equal(await page.evaluate(() => window.__signing.length), 1);
                    }
                }
                assert.equal(notifications.length, 0);
                assert.equal(preparations.length, mode === 'reload' ? 2 : 1);
                report.checks.push({width, action, mode, result: 'PASS', discardedDocumentCalls,
                    sdkCalls: discardedDocumentCalls + await page.evaluate(() => window.__signing.length), automaticRetries: 0});
            }
            await context.close();
        }
        assert.equal(report.checks.length, 16); assert.deepEqual(report.pageErrors, []); assert.deepEqual(report.unexpectedWrites, []);
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
