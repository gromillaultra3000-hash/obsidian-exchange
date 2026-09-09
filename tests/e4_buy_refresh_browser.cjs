'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), crypto = require('node:crypto');
const {chromium} = require('playwright-core');
const [sourcePath, output] = process.argv.slice(2), source = fs.readFileSync(sourcePath, 'utf8');
const hash = x => crypto.createHash('sha256').update(x).digest('hex');
const origin = 'https://buy-refresh.invalid', address = 'EQ' + 'A'.repeat(46), saved = 'EQ' + 'B'.repeat(46);
const report = {sourceSha256: hash(source), runnerSha256: hash(fs.readFileSync(__filename)),
    playwrightVersion: require('playwright-core/package.json').version, checks: [], unexpectedWrites: [], confirmations: [], pageErrors: []};
fs.mkdirSync(output, {recursive: true});
async function main() {
    assert.notEqual(process.getuid(), 0);
    const browser = await chromium.launch({executablePath: '/opt/google/chrome/chrome', chromiumSandbox: true, headless: true});
    report.browserVersion = browser.version(); let page;
    try {
        for (const width of [320, 390]) for (const scenario of ['same', 'first-hydration', 'reorder', 'no-tag', 'response-input-change', 'malformed', 'duplicate', 'duplicate-network', 'empty', 'removed-currency', 'removed-network', 'removed-all-networks', 'retire-review', 'keep-review', 'explicit-network', 'explicit-currency', 'submit']) {
            const context = await browser.newContext({viewport: {width, height: 844}, serviceWorkers: 'block'});
            await context.addInitScript(saved => {
                window.Telegram = {WebApp: {initData: '', initDataUnsafe: {}, expand() {}, ready() {}, onEvent() {}, setHeaderColor() {}, setBackgroundColor() {}, setBottomBarColor() {}}};
                localStorage.setItem('lastAddress_TON_ALT', saved);
                localStorage.setItem('lastAddress_TON_MAINNET', saved);
                localStorage.setItem('lastAddress_BTC_MAINNET', 'bc1' + 'q'.repeat(87));
            }, saved);
            const fixture = {BTC: 5000000, TON: 200, ts: Math.floor(Date.now() / 1000),
                commission_tiers: [{to_rub: null, percent: 19}], offerings: [
                    {code: 'BTC', networks: [{code: 'MAINNET', label: 'Bitcoin'}]},
                    {code: 'TON', networks: [{code: 'MAINNET', label: 'TON main'}, {code: 'ALT', label: 'Synthetic alternate'}], tag_name: 'memo', tag_kind: 'text', tag_sep: '#'}]};
            let defer = scenario === 'first-hydration', pendingRates;
            await context.route('**/*', async route => {
                const r = route.request(), u = new URL(r.url());
                if (scenario === 'submit' && u.origin === origin && u.pathname === '/api/create_order' && r.method() === 'POST') {
                    report.confirmations.push({width, body: r.postDataJSON()});
                    return route.fulfill({status: 400, contentType: 'application/json', body: JSON.stringify({ok: false, detail: 'Synthetic rejection'})});
                }
                if (r.method() !== 'GET') {report.unexpectedWrites.push(u.origin + u.pathname); return route.abort();}
                if (u.origin !== origin) return route.abort();
                if (u.pathname === '/webapp') return route.fulfill({contentType: 'text/html', body: source});
                if (u.pathname === '/api/rates') {
                    if (defer) {pendingRates = route; return;}
                    return route.fulfill({contentType: 'application/json', body: JSON.stringify(fixture)});
                }
                const other = {'/api/history': [], '/api/wallet/links': {wallets: []}, '/api/wallet/dues': {dues: []}};
                return route.fulfill({contentType: 'application/json', body: JSON.stringify(other[u.pathname] || {})});
            });
            page = await context.newPage(); page.setDefaultTimeout(5000); page.on('pageerror', e => report.pageErrors.push(e.message));
            await page.goto(origin + '/webapp', {waitUntil: 'load'}); await page.locator('#tab-exchange').click();
            if (scenario === 'first-hydration') {
                for (let n = 0; !pendingRates && n < 100; n++) await new Promise(resolve => setTimeout(resolve, 10));
                assert.ok(pendingRates);
                await page.locator('#amount').fill('12500');
                const typed = 'bc1' + 'p'.repeat(87);
                await page.locator('#address').fill(typed);
                await pendingRates.fulfill({contentType: 'application/json', body: JSON.stringify(fixture)});
                await page.waitForFunction(() => window.__oeOfferings?.length === 2);
                assert.equal(await page.locator('#currency').inputValue(), 'BTC');
                assert.equal(await page.locator('#network').inputValue(), 'MAINNET');
                assert.equal(await page.locator('#address').inputValue(), typed);
                assert.equal(await page.locator('#amount').inputValue(), '12500');
                assert.equal(await page.evaluate(() => buyRouteSignature('BTC', selectedNetwork()) !== null), true);
                report.checks.push({width, scenario, result: 'PASS', soleNetworkHydratedWithoutRecipientOverwrite: true});
                await context.close(); continue;
            }
            await page.locator('#currency').selectOption('TON'); await page.locator('#network').selectOption('ALT');
            await page.locator('#amount').fill('12500'); await page.locator('#address').fill(address);
            await page.locator('#dest_tag').fill(scenario === 'no-tag' ? '' : '  memo <>&  ');
            if (scenario === 'no-tag') await page.locator('#no_tag').check();
            const state = () => page.evaluate(() => ({currency: document.getElementById('currency').value, network: selectedNetwork(),
                address: document.getElementById('address').value, tag: document.getElementById('dest_tag').value,
                noTag: document.getElementById('no_tag').checked, amount: document.getElementById('amount').value}));
            let before = await state();
            if (scenario === 'retire-review' || scenario === 'keep-review') {
                await page.locator('#create-order').click(); await page.locator('#exchange-review').waitFor({state: 'visible'});
                await page.locator('#exchange-review-ack').check();
            }
            if (scenario === 'reorder') {fixture.offerings.reverse(); fixture.offerings.find(x => x.code === 'TON').networks.reverse();}
            if (scenario === 'malformed') fixture.offerings[1].networks = null;
            if (scenario === 'duplicate') fixture.offerings.push(structuredClone(fixture.offerings[1]));
            if (scenario === 'duplicate-network') fixture.offerings[1].networks.push(structuredClone(fixture.offerings[1].networks[0]));
            if (scenario === 'empty') fixture.offerings = [];
            if (scenario === 'removed-currency') fixture.offerings = fixture.offerings.filter(x => x.code !== 'TON');
            if (scenario === 'removed-network') fixture.offerings[1].networks = fixture.offerings[1].networks.filter(x => x.code !== 'ALT');
            if (scenario === 'removed-all-networks') fixture.offerings[1].networks = [];
            if (scenario === 'retire-review') fixture.offerings[1].tag_sep = ':';
            if (scenario === 'response-input-change') {
                defer = true;
                await page.evaluate(() => {window.__pendingRefresh = loadRates();});
                for (let n = 0; !pendingRates && n < 100; n++) await new Promise(resolve => setTimeout(resolve, 10));
                assert.ok(pendingRates);
                await page.locator('#network').selectOption('MAINNET');
                await page.locator('#address').fill('EQ' + 'C'.repeat(46));
                await page.locator('#dest_tag').fill(' changed during refresh ');
                before = await state();
                await pendingRates.fulfill({contentType: 'application/json', body: JSON.stringify(fixture)});
                await page.evaluate(() => window.__pendingRefresh);
            } else await page.evaluate(() => loadRates());
            if (scenario === 'retire-review') {
                assert.equal((await state()).currency, '');
                assert.equal(await page.locator('#exchange-review-confirm').isDisabled(), true);
                await page.locator('#exchange-review-confirm').evaluate(el => el.click());
                assert.deepEqual(report.unexpectedWrites, []);
                if (await page.locator('#exchange-review').isVisible()) await page.locator('#exchange-review-cancel').click();
            } else if (scenario === 'keep-review') {
                assert.deepEqual(await state(), before);
                assert.equal(await page.locator('#exchange-review').isVisible(), true);
                assert.equal(await page.locator('#exchange-review-ack').isChecked(), true);
                assert.equal(await page.locator('#exchange-review-confirm').isEnabled(), true);
                await page.locator('#exchange-review-cancel').click();
            } else if (scenario.startsWith('removed-') || scenario === 'empty') {
                assert.equal((await state())[scenario === 'removed-network' ? 'network' : 'currency'], '');
                if (scenario === 'removed-all-networks') {
                    assert.equal(await page.locator('#currency option[value="TON"]').isDisabled(), true);
                    await page.evaluate(() => {document.getElementById('currency').value = 'TON'; onCurrencyChange();});
                    assert.equal(await page.evaluate(() => buyRouteSignature('TON', '')), null);
                }
                if (await page.locator('#create-order').isEnabled()) await page.locator('#create-order').click();
                assert.equal(await page.locator('#exchange-review').isVisible(), false);
            } else {
                assert.deepEqual(await state(), before, 'background refresh must preserve exact typed recipient and route');
                if (scenario === 'explicit-network') {
                    await page.locator('#network').selectOption('MAINNET');
                    assert.equal((await state()).address, saved);
                } else if (scenario === 'explicit-currency') {
                    await page.locator('#currency').selectOption('BTC');
                    assert.equal((await state()).address, 'bc1' + 'q'.repeat(87));
                    assert.equal((await state()).tag, ''); assert.equal((await state()).noTag, false);
                } else if (scenario === 'submit') {
                    await page.locator('#create-order').click();
                    const modal = page.locator('#exchange-review'); await modal.waitFor({state: 'visible'});
                    assert.match(await page.locator('#exchange-review-summary').innerText(), /memo <>&/);
                    assert.equal(report.confirmations.filter(x => x.width === width).length, 0);
                    await page.locator('#exchange-review-ack').check(); await page.locator('#exchange-review-confirm').click();
                    await page.waitForFunction(() => document.getElementById('exchange-result').textContent.includes('Synthetic rejection'));
                    const posts = report.confirmations.filter(x => x.width === width); assert.equal(posts.length, 1);
                    assert.deepEqual(posts[0].body, {currency: 'TON', amount: 12500, address, network: 'ALT', pay_method: 'sbp', dest_tag: 'memo <>&', no_tag: false});
                }
            }
            if (scenario === 'same') await page.screenshot({path: path.join(output, width + '-preserved.png')});
            assert.deepEqual(report.unexpectedWrites, []); report.checks.push({width, scenario, result: 'PASS'}); await context.close();
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
