'use strict';
// Actual Mini App DOM, isolated synthetic read fixtures, no wallet SDK or writes.
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), crypto = require('node:crypto');
const {chromium} = require('playwright-core');
const [sourcePath, output] = process.argv.slice(2), source = fs.readFileSync(sourcePath, 'utf8');
const hash = x => crypto.createHash('sha256').update(x).digest('hex');
const origin = 'https://buy-custody.invalid';
const report = {sourceSha256: hash(source), runnerSha256: hash(fs.readFileSync(__filename)),
    playwrightVersion: require('playwright-core/package.json').version, checks: [], writes: [], confirmations: [], pageErrors: []};
fs.mkdirSync(output, {recursive: true});
async function main() {
    assert.notEqual(process.getuid(), 0);
    const browser = await chromium.launch({executablePath: '/opt/google/chrome/chrome', chromiumSandbox: true, headless: true});
    report.browserVersion = browser.version();
    let page;
    try {
        for (const width of [320, 390, 1280]) {
            const beforeConfirmations = report.confirmations.length;
            const context = await browser.newContext({viewport: {width, height: 844}, serviceWorkers: 'block'});
            await context.addInitScript(() => {
                window.Telegram = {WebApp: {initData: '', initDataUnsafe: {}, expand() {}, ready() {}, onEvent() {}, setHeaderColor() {}, setBackgroundColor() {}, setBottomBarColor() {}}};
            });
            await context.route('**/*', async route => {
                const r = route.request(), u = new URL(r.url());
                if (u.origin === origin && u.pathname === '/api/create_order' && r.method() === 'POST') {
                    report.confirmations.push(r.postDataJSON());
                    return route.fulfill({status: 400, contentType: 'application/json', body: JSON.stringify({ok: false, detail: 'Synthetic rejection; no order created'})});
                }
                if (r.method() !== 'GET') {report.writes.push(u.origin + u.pathname); return route.abort();}
                if (u.origin !== origin) return route.abort();
                if (u.pathname === '/webapp') return route.fulfill({contentType: 'text/html', body: source});
                const fixtures = {'/api/history': [], '/api/wallet/links': {wallets: []}, '/api/wallet/dues': {dues: []},
                    '/api/rates': {BTC: 5000000, offerings: [{code: 'BTC', networks: [{code: 'MAINNET', label: 'Bitcoin'}]}]}};
                return route.fulfill({contentType: 'application/json', body: JSON.stringify(fixtures[u.pathname] || {})});
            });
            page = await context.newPage(); page.setDefaultTimeout(5000);
            page.on('pageerror', e => report.pageErrors.push(e.message));
            await page.goto(origin + '/webapp', {waitUntil: 'load'});
            await page.locator('#tab-exchange').click();
            await page.locator('#currency').selectOption('BTC');
            await page.locator('#amount').fill('12500');
            await page.locator('#address').fill('bc1' + 'q'.repeat(87));
            await page.locator('#create-order').click();
            const modal = page.locator('#exchange-review'), ack = page.locator('#exchange-review-ack');
            const confirm = page.locator('#exchange-review-confirm');
            await modal.waitFor({state: 'visible'});
            assert.equal(await ack.isChecked(), false); assert.equal(await confirm.isDisabled(), true);
            const text = await page.locator('#exchange-review-summary').innerText();
            assert.ok(!text.includes('Ключи и адрес получателя остаются под вашим контролем'), 'must not infer recipient self-custody from a pasted address');
            assert.match(text, /В личном кошельке ключами управляете вы/);
            assert.match(text, /адрес биржи или другого сервиса/);
            assert.match(text, /средства хранит этот сервис/);
            assert.match(text, /KYC действуют отдельно/);
            assert.match(text, /ObsidianExchange не получает ключи/);
            assert.match(text, /ObsidianExchange · private lane · без KYC/);
            assert.match(text, /Комиссия и расчёт/i);
            assert.match(await page.locator('#exchange-review-risk').innerText(), /после отправки выплаты в блокчейн отменить перевод нельзя/);
            assert.equal(await page.evaluate(() => document.activeElement.id), 'exchange-review-title');
            assert.equal(await page.locator('.exchange-review-surface').evaluate(el => el.scrollWidth <= el.clientWidth + 1), true);
            await page.screenshot({path: path.join(output, width + '-review-top.png')});
            await ack.check(); assert.equal(await confirm.isEnabled(), true);
            await page.locator('#exchange-review-cancel').click();
            assert.equal(await modal.isVisible(), false);
            assert.deepEqual(report.writes, []);
            await page.locator('#create-order').click();
            assert.equal(await ack.isChecked(), false); assert.equal(await confirm.isDisabled(), true);
            await page.keyboard.press('Escape'); assert.equal(await modal.isVisible(), false);
            assert.deepEqual(report.writes, []);
            assert.equal(report.confirmations.length, beforeConfirmations);
            await page.locator('#create-order').click();
            await ack.check(); await confirm.click();
            await page.waitForFunction(() => document.getElementById('exchange-result').textContent.includes('Synthetic rejection'));
            assert.equal(report.confirmations.length, beforeConfirmations + 1);
            assert.deepEqual(report.confirmations.at(-1), {currency: 'BTC', amount: 12500, address: 'bc1' + 'q'.repeat(87),
                network: 'MAINNET', pay_method: 'sbp', dest_tag: '', no_tag: false});
            report.checks.push({explicitConfirmationRequests: 1, unchangedBody: true, width, result: 'PASS', custody: 'conditional-own-wallet-or-provider', irreversiblePayout: true,
                initiallyDisabled: true, acknowledgementOnlyEnables: true, cancelAndEscapeNoWrites: true, noHorizontalOverflow: true});
            await context.close();
        }
        assert.deepEqual(report.pageErrors, []); assert.deepEqual(report.writes, []);
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
