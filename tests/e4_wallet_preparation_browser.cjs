'use strict';
// Exact shipped page; native fetch/DOM; deferred intercepted preparation only.
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), crypto = require('node:crypto');
const {chromium} = require('playwright-core');
const [sourcePath, output] = process.argv.slice(2), source = fs.readFileSync(sourcePath, 'utf8');
const hash = x => crypto.createHash('sha256').update(x).digest('hex');
const origin = 'https://wallet-preparation.invalid';
const address = 'EQ' + 'A'.repeat(46);
const report = {sourceSha256: hash(source), runnerSha256: hash(fs.readFileSync(__filename)),
    playwrightVersion: require('playwright-core/package.json').version, checks: [], unexpectedWrites: [], pageErrors: []};
fs.mkdirSync(output, {recursive: true});
async function main() {
    assert.notEqual(process.getuid(), 0);
    const browser = await chromium.launch({executablePath: '/opt/google/chrome/chrome', chromiumSandbox: true, headless: true});
    report.browserVersion = browser.version();
    let page;
    try {
        for (const width of [320, 390]) {
            const context = await browser.newContext({viewport: {width, height: 844}, serviceWorkers: 'block'});
            let pending = [];
            await context.addInitScript(() => {
                window.Telegram = {WebApp: {initData: '', initDataUnsafe: {}, expand() {}, ready() {}, onEvent() {}, setHeaderColor() {}, setBackgroundColor() {}, setBottomBarColor() {}}};
            });
            await context.route('**/*', async route => {
                const r = route.request(), u = new URL(r.url());
                if (u.origin !== origin) return route.abort();
                if (r.method() === 'GET' && u.pathname === '/webapp') return route.fulfill({contentType: 'text/html', body: source});
                if (r.method() === 'POST' && ['/api/wallet/transfer-request', '/api/wallet/send-request'].includes(u.pathname)) {
                    pending.push({route, payload: r.postDataJSON(), url: u.pathname}); return;
                }
                if (r.method() !== 'GET') { report.unexpectedWrites.push(u.pathname); return route.abort(); }
                const fixtures = {'/api/history': [], '/api/wallet/links': {wallets: []}, '/api/wallet/dues': {dues: []},
                    '/api/rates': {BTC: 5000000, offerings: [{code: 'BTC', networks: [{code: 'MAINNET'}]}]}};
                return route.fulfill({contentType: 'application/json', body: JSON.stringify(fixtures[u.pathname] || {})});
            });
            page = await context.newPage(); page.setDefaultTimeout(5000);
            page.on('pageerror', e => report.pageErrors.push(e.message));
            const modal = page.locator('#exchange-review'), ack = page.locator('#exchange-review-ack');
            const confirm = page.locator('#exchange-review-confirm');
            async function start(action) {
                const index = pending.length;
                await page.evaluate(({action, index}) => {
                    const p = action === 'transfer' ? walletTransfer() : walletPay(42, document.getElementById('sell-pay-btn'));
                    window.__preparations[index] = p.then(() => {window.__settled[index] = true;});
                }, {action, index});
                for (let i = 0; pending.length <= index && i < 100; i++) await new Promise(r => setTimeout(r, 10));
                assert.equal(pending.length, index + 1); return index;
            }
            async function finish(index, error = false) {
                const item = pending[index];
                if (error) await item.route.abort('failed');
                else await item.route.fulfill({contentType: 'application/json', body: JSON.stringify({ok: true, sell_id: 42,
                    amount: index + 1, address, marker: 'synthetic ' + index,
                    request: {validUntil: 2000, messages: [{address, amount: String(index + 1), payload: 'synthetic-not-a-boc'}]}})});
                await page.waitForFunction(index => window.__settled[index] === true, index);
            }
            for (const first of ['transfer', 'payment']) for (const second of ['transfer', 'payment']) {
                for (const mode of ['cancel', 'escape', 'older-first', 'stale-error', 'other-review', 'expiry']) {
                    pending = [];
                    await page.goto(origin + '/webapp', {waitUntil: 'load'});
                    await page.clock.install();
                    await page.evaluate(address => {
                        window.__preparations = []; window.__settled = []; window.__signing = [];
                        tcUI = {async sendTransaction(r) {window.__signing.push(structuredClone(r)); throw new Error('Synthetic wallet rejection');}};
                        document.getElementById('w-to').value = address;
                        document.getElementById('w-amount').value = '1.25';
                        document.getElementById('w-comment').value = 'synthetic';
                    }, address);
                    await start(first); await start(second);
                    if (mode === 'other-review') {
                        await page.evaluate(() => openExchangeReview({title: 'Synthetic replacement review', rows: [{label: 'Test', value: 'Literal'}], risk: 'No transaction', onConfirm: () => {throw new Error('Must not confirm synthetic replacement');}}));
                        await finish(0); await finish(1);
                        assert.equal(await page.locator('#exchange-review-title').textContent(), 'Synthetic replacement review');
                        await page.locator('#exchange-review-cancel').click();
                    } else if (mode === 'older-first') {
                        await finish(0); assert.equal(await modal.isVisible(), false);
                        await finish(1); await modal.waitFor({state: 'visible'});
                        assert.equal(await ack.isChecked(), false); assert.equal(await confirm.isDisabled(), true);
                        await ack.check(); await confirm.click();
                        await page.waitForFunction(() => window.__signing.length === 1);
                        assert.equal(await page.evaluate(() => window.__signing[0].messages[0].amount), '2');
                    } else {
                        await finish(1); await modal.waitFor({state: 'visible'});
                        assert.equal(await ack.isChecked(), false); assert.equal(await confirm.isDisabled(), true);
                        await ack.check();
                        if (mode === 'escape') await page.keyboard.press('Escape');
                        else if (mode === 'expiry') await page.clock.fastForward(120051);
                        else await page.locator('#exchange-review-cancel').click();
                        const before = await page.evaluate(() => [document.getElementById('w-send-msg').textContent, document.getElementById('sell-pay-btn').textContent]);
                        await finish(0, mode === 'stale-error');
                        assert.deepEqual(await page.evaluate(() => [document.getElementById('w-send-msg').textContent, document.getElementById('sell-pay-btn').textContent]), before);
                        if (mode === 'expiry') {assert.equal(await confirm.isDisabled(), true); await page.locator('#exchange-review-cancel').click();}
                        assert.equal(await modal.isVisible(), false);
                        await confirm.evaluate(b => b.click());
                        assert.equal(await page.evaluate(() => window.__signing.length), 0);
                    }
                    assert.equal(await modal.isVisible(), false);
                    assert.equal(pending.length, 2);
                    if (width === 320 && first === 'transfer' && second === 'transfer' && mode === 'cancel')
                        await page.screenshot({path: path.join(output, '320-cancel-remains-closed.png')});
                    report.checks.push({width, first, second, mode, result: 'PASS', preparations: 2});
                }
            }
            await context.close();
        }
        assert.equal(report.checks.length, 48); assert.deepEqual(report.pageErrors, []); assert.deepEqual(report.unexpectedWrites, []);
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
