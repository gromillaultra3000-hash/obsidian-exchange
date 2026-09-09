'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), crypto = require('node:crypto');
const {chromium} = require('playwright-core');
const [sourcePath, output] = process.argv.slice(2), source = fs.readFileSync(sourcePath, 'utf8');
const hash = x => crypto.createHash('sha256').update(x).digest('hex');
const origin = 'https://sell-estimate.invalid';
const report = {sourceSha256: hash(source), runnerSha256: hash(fs.readFileSync(__filename)),
    playwrightVersion: require('playwright-core/package.json').version, checks: [], unexpectedWrites: [], confirmations: [], pageErrors: []};
fs.mkdirSync(output, {recursive: true});
async function main() {
    assert.notEqual(process.getuid(), 0);
    const browser = await chromium.launch({executablePath: '/opt/google/chrome/chrome', chromiumSandbox: true, headless: true});
    report.browserVersion = browser.version();
    let page;
    try {
        for (const width of [320, 390]) for (const scenario of ['stale', 'fresh', 'malformed-rate', 'malformed-fee', 'refresh-preserve', 'refresh-race', 'removed-selection', 'refresh-failure', 'fresh-submit', 'stale-submit', 'pending-submit']) {
            const context = await browser.newContext({viewport: {width, height: 844}, serviceWorkers: 'block'});
            await context.addInitScript(() => {
                window.Telegram = {WebApp: {initData: '', initDataUnsafe: {}, expand() {}, ready() {}, onEvent() {}, setHeaderColor() {}, setBackgroundColor() {}, setBottomBarColor() {}}};
            });
            const fixture = {coins: [{code: 'BTC', label: 'Bitcoin', rate: 4550000, market: 5000000, fee_percent: 9, min: 0.0001, network: 'MAINNET'},
                {code: 'TON', label: 'TON', rate: 182, market: 200, fee_percent: 9, min: 1}],
                payout_ways: [{code: 'sbp', label: 'СБП', needs_bank: true, needs_name: true}, {code: 'card', label: 'Карта', needs_bank: true, needs_name: true}],
                payout_banks: [{code: 'bank-a', label: 'Банк A'}, {code: 'bank-b', label: 'Банк B'}], fee_label: '9%'};
            let failure = false;
            let defer = false; const pending = [];
            let pendingPost;
            await context.route('**/*', async route => {
                const r = route.request(), u = new URL(r.url());
                if (scenario.endsWith('-submit') && u.origin === origin && u.pathname === '/api/sell/create' && r.method() === 'POST') {
                    report.confirmations.push({width, scenario, body: r.postDataJSON()});
                    if (scenario === 'pending-submit') {pendingPost = route; return;}
                    return route.fulfill({status: 400, contentType: 'application/json', body: JSON.stringify({ok: false, detail: 'Synthetic rejection'})});
                }
                if (r.method() !== 'GET') {report.unexpectedWrites.push(u.origin + u.pathname); return route.abort();}
                if (u.origin !== origin) return route.abort();
                if (u.pathname === '/webapp') return route.fulfill({contentType: 'text/html', body: source});
                if (u.pathname === '/api/sell/options') {
                    if (defer) {pending.push(route); return;}
                    return route.fulfill({status: failure ? 503 : 200, contentType: 'application/json', body: JSON.stringify(fixture)});
                }
                const other = {'/api/history': [], '/api/wallet/links': {wallets: []}, '/api/wallet/dues': {dues: []}, '/api/rates': {}};
                return route.fulfill({contentType: 'application/json', body: JSON.stringify(other[u.pathname] || {})});
            });
            page = await context.newPage(); page.setDefaultTimeout(5000);
            page.on('pageerror', e => report.pageErrors.push(e.message));
            await page.goto(origin + '/webapp', {waitUntil: 'load'});
            await page.locator('#tab-exchange').click();
            await page.locator('#deal-side [data-side="sell"]').click();
            await page.locator('#sell-currency').selectOption('BTC');
            await page.locator('#sell-method').selectOption('card');
            await page.locator('#sell-bank').selectOption('bank-b');
            await page.locator('#sell-amount').fill('0.01');
            await page.locator('#sell-phone').fill('4111111111111111');
            await page.locator('#sell-name').fill('Тестовый Получатель');
            const form = () => page.evaluate(() => ['sell-currency', 'sell-method', 'sell-bank', 'sell-amount', 'sell-phone', 'sell-name'].map(id => document.getElementById(id).value));
            const before = await form();
            if (scenario === 'refresh-race') {
                defer = true;
                async function start() {
                    const index = pending.length;
                    await page.evaluate(() => {void loadSellOptions();});
                    for (let n = 0; pending.length <= index && n < 100; n++) await new Promise(resolve => setTimeout(resolve, 10));
                    assert.equal(pending.length, index + 1); return index;
                }
                for (const outcome of ['old-success', 'old-failure']) {
                    const old = await start(), current = await start();
                    await page.locator('#sell-bank').selectOption('bank-a');
                    await page.locator('#sell-name').fill('Изменённый Получатель');
                    const changed = await form();
                    const latestRate = outcome === 'old-success' ? 4000000 : 4100000;
                    fixture.coins[0].rate = latestRate;
                    await pending[current].fulfill({contentType: 'application/json', body: JSON.stringify(fixture)});
                    await page.waitForFunction(rate => sellEstimateSnapshot?.options.BTC.rate === rate, latestRate);
                    if (outcome === 'old-failure') await pending[old].abort('failed');
                    else {
                        fixture.coins[0].rate = 3000000;
                        await pending[old].fulfill({contentType: 'application/json', body: JSON.stringify(fixture)});
                    }
                    // Await all queued response/body continuations before evaluating ownership.
                    await page.evaluate(() => new Promise(resolve => setTimeout(resolve, 30)));
                    assert.equal(await page.evaluate(() => sellEstimateSnapshot?.options.BTC.rate), latestRate);
                    assert.deepEqual(await form(), changed, 'response-time inputs survive concurrent refresh');
                }
                report.checks.push({width, scenario, result: 'PASS', staleSuccessAndFailureIgnored: true, responseTimeInputsPreserved: true});
                await context.close(); continue;
            }
            if (scenario.startsWith('stale')) {await page.clock.install(); await page.clock.setSystemTime(Date.now() + 86400000);}
            if (scenario === 'malformed-rate' || scenario === 'malformed-fee') {
                fixture.coins[0][scenario === 'malformed-rate' ? 'rate' : 'fee_percent'] = '9';
                await page.evaluate(() => loadSellOptions());
            }
            if (scenario === 'refresh-failure') {failure = true; await page.evaluate(() => loadSellOptions());}
            if (scenario === 'refresh-preserve') {
                fixture.coins.reverse(); fixture.payout_ways.reverse(); fixture.payout_banks.reverse();
                await page.evaluate(() => loadSellOptions());
                assert.deepEqual(await form(), before, 'refresh must preserve selected payout and recipient');
            }
            if (scenario === 'removed-selection') {
                fixture.coins = fixture.coins.filter(x => x.code !== 'BTC');
                fixture.payout_ways = fixture.payout_ways.filter(x => x.code !== 'card');
                fixture.payout_banks = fixture.payout_banks.filter(x => x.code !== 'bank-b');
                await page.evaluate(() => loadSellOptions());
                assert.equal(await page.locator('#sell-currency').inputValue(), '');
                assert.equal(await page.locator('#sell-method').inputValue(), '');
                assert.equal(await page.locator('#sell-bank').inputValue(), '');
                assert.deepEqual((await form()).slice(3), before.slice(3));
                await page.locator('#sell-submit').click();
                assert.equal(await page.locator('#exchange-review').isVisible(), false);
                assert.deepEqual(report.unexpectedWrites, []);
                report.checks.push({width, scenario, result: 'PASS', noSilentSubstitution: true});
                await context.close(); continue;
            }
            if (scenario === 'refresh-failure') {
                assert.equal(await page.locator('#sell-submit').isDisabled(), true);
                assert.doesNotMatch((await page.locator('#sell-payout').innerText()).replace(/\s/g, ''), /45500/);
                assert.deepEqual(await form(), before);
                report.checks.push({width, scenario, result: 'PASS', disabledAfterFailure: true});
                await context.close(); continue;
            }
            await page.locator('#sell-submit').click();
            const modal = page.locator('#exchange-review'), ack = page.locator('#exchange-review-ack');
            const confirm = page.locator('#exchange-review-confirm');
            await modal.waitFor({state: 'visible'});
            const text = await page.locator('#exchange-review-summary').innerText();
            const unavailable = scenario.startsWith('stale') || scenario.startsWith('malformed') || scenario === 'refresh-failure';
            if (unavailable) {
                assert.match(text, /недоступ|не удалось|нет актуальн/i, 'stale/malformed payout must not be shown as current');
                assert.doesNotMatch(text.replace(/\s/g, ''), /45500/);
            } else {
                assert.match(text.replace(/\s/g, ''), /45500/); assert.match(text, /9%/);
                assert.match(text, /ориентир|предварител/i);
            }
            assert.match(text, /4111111111111111/); assert.match(text, /Тестовый Получатель/);
            assert.match(text, /Банк B/); assert.match(text, /Карта/);
            assert.equal(await ack.isChecked(), false); assert.equal(await confirm.isDisabled(), true);
            assert.equal(await page.locator('.exchange-review-surface').evaluate(el => el.scrollWidth <= el.clientWidth + 1), true);
            assert.equal(report.confirmations.filter(x => x.width === width && x.scenario === scenario).length, 0);
            if (scenario === 'fresh') await page.screenshot({path: path.join(output, width + '-fresh.png')});
            await ack.check();
            if (scenario.endsWith('-submit')) {
                await confirm.click();
                if (scenario === 'pending-submit') {
                    for (let n = 0; !pendingPost && n < 100; n++) await new Promise(resolve => setTimeout(resolve, 10));
                    assert.ok(pendingPost);
                    await page.evaluate(() => loadSellOptions());
                    assert.equal(await page.locator('#sell-submit').isDisabled(), true, 'refresh cannot reopen writer while POST pending');
                    await page.evaluate(() => createSellOrder());
                    assert.equal(await modal.isVisible(), false);
                    assert.equal(report.confirmations.filter(x => x.width === width && x.scenario === scenario).length, 1);
                    await pendingPost.fulfill({status: 400, contentType: 'application/json', body: JSON.stringify({ok: false, detail: 'Synthetic rejection'})});
                }
                await page.waitForFunction(() => document.getElementById('sell-result').textContent.includes('Synthetic rejection'));
                const matches = report.confirmations.filter(x => x.width === width && x.scenario === scenario);
                assert.equal(matches.length, 1);
                assert.deepEqual(matches[0].body, {currency: 'BTC', amount: 0.01, phone: '4111111111111111', method: 'card', bank: 'bank-b', full_name: 'Тестовый Получатель'});
                if (scenario === 'pending-submit') {
                    await page.waitForFunction(() => !document.getElementById('sell-submit').disabled);
                    await page.locator('#sell-submit').click();
                    await modal.waitFor({state: 'visible'});
                    await page.locator('#exchange-review-cancel').click();
                }
            } else {
                if (scenario === 'fresh') {
                    fixture.coins[0].rate = 4000000;
                    await page.evaluate(() => loadSellOptions());
                    assert.equal(await page.locator('#exchange-review-summary').innerText(), text);
                    await page.clock.install(); await page.clock.setSystemTime(Date.now() + 61000);
                    await confirm.click(); assert.equal(await confirm.isDisabled(), true);
                    assert.equal(await ack.isChecked(), false);
                }
                await page.locator('#exchange-review-cancel').click();
            }
            assert.equal(await modal.isVisible(), false); assert.deepEqual(report.unexpectedWrites, []);
            report.checks.push({width, scenario, result: 'PASS'}); await context.close();
        }
        assert.deepEqual(report.pageErrors, []); assert.deepEqual(report.unexpectedWrites, []); report.result = 'PASS';
    } catch (e) {
        report.result = 'FAIL'; report.error = e.stack; process.exitCode = 1;
        if (page && !page.isClosed()) await page.screenshot({path: path.join(output, 'failure.png')}).catch(() => {});
    } finally {
        await browser.close(); fs.writeFileSync(path.join(output, 'report.json'), JSON.stringify(report, null, 2) + '\n');
        console.log(JSON.stringify({result: report.result, cases: report.checks.length, error: report.error}));
    }
}
main().catch(e => {console.error(e); process.exitCode = 1;});
