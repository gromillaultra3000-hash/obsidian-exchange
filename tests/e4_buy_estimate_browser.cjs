'use strict';
// Exact shipped page and native DOM, synthetic rates, all writes denied.
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), crypto = require('node:crypto');
const {chromium} = require('playwright-core');
const [sourcePath, output] = process.argv.slice(2), source = fs.readFileSync(sourcePath, 'utf8');
const hash = x => crypto.createHash('sha256').update(x).digest('hex');
const origin = 'https://buy-estimate.invalid';
const tiers = [{to_rub: 5000, percent: 27}, {to_rub: 10000, percent: 25},
    {to_rub: 20000, percent: 23}, {to_rub: null, percent: 19}];
const report = {sourceSha256: hash(source), runnerSha256: hash(fs.readFileSync(__filename)),
    playwrightVersion: require('playwright-core/package.json').version, checks: [], writes: [], expectedConfirmations: [], pageErrors: []};
fs.mkdirSync(output, {recursive: true});
async function main() {
    assert.notEqual(process.getuid(), 0);
    const browser = await chromium.launch({executablePath: '/opt/google/chrome/chrome', chromiumSandbox: true, headless: true});
    report.browserVersion = browser.version();
    let page;
    try {
        for (const width of [320, 390]) {
            for (const scenario of ['fresh', 'fresh-submit', 'unavailable-submit', 'zero-rate', 'string-rate', 'missing-rate', 'missing-fee', 'invalid-fee', 'stale-ts', 'future-ts', 'http-error']) {
                const context = await browser.newContext({viewport: {width, height: 844}, serviceWorkers: 'block'});
                await context.addInitScript(() => {
                    window.Telegram = {WebApp: {initData: '', initDataUnsafe: {}, expand() {}, ready() {}, onEvent() {}, setHeaderColor() {}, setBackgroundColor() {}, setBottomBarColor() {}}};
                });
                const fixture = {BTC: 5000000, ts: Math.floor(Date.now() / 1000), commission_tiers: tiers,
                    offerings: [{code: 'BTC', networks: [{code: 'MAINNET', label: 'Bitcoin'}]}]};
                if (scenario === 'zero-rate') fixture.BTC = 0;
                if (scenario === 'string-rate') fixture.BTC = '5000000';
                if (scenario === 'missing-rate' || scenario === 'unavailable-submit') delete fixture.BTC;
                if (scenario === 'missing-fee') delete fixture.commission_tiers;
                if (scenario === 'invalid-fee') fixture.commission_tiers = [{to_rub: null, percent: 100}];
                if (scenario === 'stale-ts') fixture.ts -= 601;
                if (scenario === 'future-ts') fixture.ts += 601;
                await context.route('**/*', async route => {
                    const r = route.request(), u = new URL(r.url());
                    if (scenario.endsWith('-submit') && u.origin === origin && u.pathname === '/api/create_order' && r.method() === 'POST') {
                        report.expectedConfirmations.push({width, scenario, body: r.postDataJSON()});
                        return route.fulfill({status: 400, contentType: 'application/json', body: JSON.stringify({ok: false, detail: 'Synthetic rejection'})});
                    }
                    if (r.method() !== 'GET') {report.writes.push(u.origin + u.pathname); return route.abort();}
                    if (u.origin !== origin) return route.abort();
                    if (u.pathname === '/webapp') return route.fulfill({contentType: 'text/html', body: source});
                    if (u.pathname === '/api/rates') return route.fulfill({status: scenario === 'http-error' ? 503 : 200,
                        contentType: 'application/json', body: JSON.stringify(fixture)});
                    const fixtures = {'/api/history': [], '/api/wallet/links': {wallets: []}, '/api/wallet/dues': {dues: []}};
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
                assert.ok(!text.includes('итоговая сумма указана выше'), 'receive calculation must be inside review');
                assert.doesNotMatch(text, /NaN|Infinity/);
                if (scenario === 'fresh' || scenario === 'fresh-submit') {
                    assert.match(text, /0[.,]001925\s*BTC/);
                    assert.match(text.replace(/[\s\u00a0\u202f]/g, ''), /5000000/);
                    assert.match(text, /23%/);
                    assert.match(text, /предварител|ориентир|приблизител/i);
                    await page.screenshot({path: path.join(output, width + '-fresh-top.png')});
                    await page.getByText('Ориентировочно к получению', {exact: true}).scrollIntoViewIfNeeded();
                    await page.screenshot({path: path.join(output, width + '-estimate-visible.png')});
                } else {
                    assert.match(text, /недоступ|не удалось|нет актуальн/i);
                    assert.doesNotMatch(text, /0[.,]001925/);
                }
                assert.equal(await page.locator('.exchange-review-surface').evaluate(el => el.scrollWidth <= el.clientWidth + 1), true);
                assert.equal(report.expectedConfirmations.filter(x => x.width === width && x.scenario === scenario).length, 0);
                await ack.check();
                if (scenario.endsWith('-submit')) {
                    assert.equal(report.expectedConfirmations.filter(x => x.width === width && x.scenario === scenario).length, 0);
                    await confirm.click();
                    await page.waitForFunction(() => document.getElementById('exchange-result').textContent.includes('Synthetic rejection'));
                    const matches = report.expectedConfirmations.filter(x => x.width === width && x.scenario === scenario);
                    assert.equal(matches.length, 1);
                    assert.deepEqual(matches[0].body, {currency: 'BTC', amount: 12500, address: 'bc1' + 'q'.repeat(87),
                        network: 'MAINNET', pay_method: 'sbp', dest_tag: '', no_tag: false});
                    assert.equal(await modal.isVisible(), false);
                    report.checks.push({width, scenario, result: 'PASS', explicitSyntheticPost: 1, unchangedBody: true});
                    await context.close(); continue;
                }
                if (scenario === 'fresh') {
                    fixture.BTC = 2500000;
                    await page.evaluate(() => loadRates());
                    assert.equal(await page.locator('#exchange-review-summary').innerText(), text, 'refresh must not rewrite acknowledged estimate');
                    await page.clock.install();
                    await page.clock.setSystemTime(Date.now() - 61000);
                    await confirm.click();
                    assert.equal(await modal.isVisible(), false);
                    assert.match(await page.locator('#exchange-result').innerText(), /Время расчёта истекло/);
                    assert.deepEqual(report.writes, []);
                    await page.clock.setSystemTime(Date.now());
                    await page.locator('#address').fill('bc1' + 'q'.repeat(87));
                    await page.locator('#create-order').click(); await ack.check();
                    await page.clock.setSystemTime(Date.now() + 61000);
                    // No timer firing is needed: confirmation validates its deadline itself.
                    await confirm.click();
                    assert.equal(await confirm.isDisabled(), true);
                    assert.equal(await ack.isChecked(), false);
                    assert.match(await page.locator('#exchange-review-freshness').innerText(), /истекло/);
                    assert.deepEqual(report.writes, []);
                } else if (scenario === 'missing-rate') {
                    await page.clock.install();
                    const opened = Date.now();
                    await page.clock.setSystemTime(opened + 61000);
                    await page.evaluate(() => updateExchangeReviewConfirm());
                    assert.equal(await confirm.isEnabled(), true, 'unavailable estimate retains ordinary two-minute review');
                    await page.clock.setSystemTime(opened + 121000);
                    await confirm.click();
                    assert.equal(await confirm.isDisabled(), true);
                    assert.deepEqual(report.writes, []);
                }
                await page.locator('#exchange-review-cancel').click();
                assert.equal(await modal.isVisible(), false); assert.deepEqual(report.writes, []);
                if (scenario === 'fresh') {
                    await page.locator('#address').fill('bc1' + 'q'.repeat(87));
                    await page.locator('#create-order').click();
                    await modal.waitFor({state: 'visible'});
                    assert.match(await page.locator('#exchange-review-summary').innerText(), /расчёт недоступен/);
                    await page.locator('#exchange-review-cancel').click();
                }
                report.checks.push({width, scenario, result: 'PASS', noWrites: true, noHorizontalOverflow: true});
                await context.close();
            }
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
