'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), crypto = require('node:crypto');
const {chromium} = require('playwright-core');
const [sourcePath, output] = process.argv.slice(2), source = fs.readFileSync(sourcePath, 'utf8');
const hash = x => crypto.createHash('sha256').update(x).digest('hex');
const origin = 'https://tonconnect-binding.invalid', initial = 'EQ' + 'A'.repeat(46), verified = 'EQ' + 'B'.repeat(46);
const report = {sourceSha256: hash(source), runnerSha256: hash(fs.readFileSync(__filename)),
    playwrightVersion: require('playwright-core/package.json').version, checks: [], unexpectedWrites: [], verificationRequests: [], pageErrors: []};
fs.mkdirSync(output, {recursive: true});
async function main() {
    assert.notEqual(process.getuid(), 0);
    const browser = await chromium.launch({executablePath: '/opt/google/chrome/chrome', chromiumSandbox: true, headless: true});
    report.browserVersion = browser.version(); let page;
    try {
        for (const width of [320, 390]) for (const scenario of ['route', 'success', 'same-route-refresh', 'address', 'memo', 'no-tag', 'away-back', 'disconnect', 'non-ton', 'json-delay', 'stale-error', 'error', 'http-error', 'malformed-address', 'nonboolean-verified']) {
            const context = await browser.newContext({viewport: {width, height: 844}, serviceWorkers: 'block'});
            await context.addInitScript(() => {
                window.Telegram = {WebApp: {initData: '', initDataUnsafe: {}, expand() {}, ready() {}, onEvent() {}, setHeaderColor() {}, setBackgroundColor() {}, setBottomBarColor() {}}};
                window.TON_CONNECT_UI = {}; // inert eligibility marker, no SDK/signature methods.
                const fetchNative = window.fetch.bind(window);
                window.fetch = async (...args) => {
                    const response = await fetchNative(...args);
                    if (String(args[0]) === '/api/tonconnect/verify' && window.__holdVerificationJson) {
                        const jsonNative = response.json.bind(response);
                        response.json = async () => {
                            const data = await jsonNative(); window.__jsonReached = true;
                            await new Promise(resolve => {window.__releaseJson = resolve;}); return data;
                        };
                    }
                    return response;
                };
            });
            let pending;
            await context.route('**/*', async route => {
                const r = route.request(), u = new URL(r.url());
                if (u.origin === origin && u.pathname === '/api/tonconnect/verify' && r.method() === 'POST') {
                    report.verificationRequests.push({width, scenario, body: r.postDataJSON()}); pending = route; return;
                }
                if (r.method() !== 'GET') {report.unexpectedWrites.push(u.origin + u.pathname); return route.abort();}
                if (u.origin !== origin) return route.abort();
                if (u.pathname === '/webapp') return route.fulfill({contentType: 'text/html', body: source});
                const other = {'/api/history': [], '/api/wallet/links': {wallets: []}, '/api/wallet/dues': {dues: []},
                    '/api/rates': {BTC: 5000000, TON: 200, ts: Math.floor(Date.now() / 1000), commission_tiers: [{to_rub: null, percent: 19}],
                        offerings: [{code: 'BTC', networks: [{code: 'MAINNET', label: 'Bitcoin'}]},
                            {code: 'TON', networks: [{code: 'MAINNET', label: 'TON'}], tag_name: 'memo', tag_kind: 'text', tag_sep: '#', wallet_connect: true}]}};
                return route.fulfill({contentType: 'application/json', body: JSON.stringify(other[u.pathname] || {})});
            });
            page = await context.newPage(); page.setDefaultTimeout(5000); page.on('pageerror', e => report.pageErrors.push(e.message));
            await page.goto(origin + '/webapp', {waitUntil: 'load'}); await page.locator('#tab-exchange').click();
            await page.locator('#currency').selectOption('TON'); await page.locator('#address').fill(initial);
            await page.locator('#dest_tag').fill('old memo');
            if (scenario === 'non-ton') await page.locator('#currency').selectOption('BTC');
            await page.evaluate(hold => {
                window.__holdVerificationJson = hold;
                window.__verification = tcHandleWallet({account: {address: 'synthetic-account'}, connectItems: {tonProof: {proof: {synthetic: true}}}});
            }, scenario === 'json-delay');
            if (scenario === 'non-ton') {
                await page.evaluate(() => window.__verification);
                assert.equal(pending, undefined, 'non-TON route cannot begin verification');
                report.checks.push({width, scenario, result: 'PASS'}); await context.close(); continue;
            }
            for (let n = 0; !pending && n < 100; n++) await new Promise(resolve => setTimeout(resolve, 10));
            assert.ok(pending);
            const success = {verified: true, address: verified};
            if (scenario === 'same-route-refresh') await page.evaluate(() => loadRates());
            if (scenario === 'route') {
                await page.locator('#currency').selectOption('BTC'); await page.locator('#address').fill('bc1' + 'q'.repeat(87));
            }
            if (scenario === 'address' || scenario === 'stale-error') await page.locator('#address').fill('EQ' + 'C'.repeat(46));
            if (scenario === 'memo') await page.locator('#dest_tag').fill('new memo');
            if (scenario === 'no-tag') await page.locator('#no_tag').check();
            if (scenario === 'away-back') {
                await page.locator('#address').fill('EQ' + 'C'.repeat(46)); await page.locator('#address').fill(initial);
            }
            if (scenario === 'disconnect') await page.evaluate(() => tcHandleWallet(null));
            if (scenario === 'json-delay') {
                await pending.fulfill({contentType: 'application/json', body: JSON.stringify(success)});
                await page.waitForFunction(() => window.__jsonReached === true);
                await page.locator('#dest_tag').fill('edited during JSON delivery');
            }
            const state = () => page.evaluate(() => ({currency: document.getElementById('currency').value, address: document.getElementById('address').value,
                tag: document.getElementById('dest_tag').value, noTag: document.getElementById('no_tag').checked, status: document.getElementById('tc-msg').textContent}));
            const beforeResponse = await state();
            if (scenario === 'json-delay') await page.evaluate(() => window.__releaseJson());
            else if (scenario === 'error' || scenario === 'stale-error') await pending.abort('failed');
            else await pending.fulfill({status: scenario === 'http-error' ? 403 : 200, contentType: 'application/json',
                body: JSON.stringify(scenario === 'malformed-address' ? {verified: true, address: {bad: true}}
                    : scenario === 'nonboolean-verified' ? {verified: 'true', address: verified} : success)});
            await page.evaluate(() => window.__verification);
            const after = await state();
            if (scenario === 'success' || scenario === 'same-route-refresh') {
                assert.equal(after.address, verified); assert.equal(after.tag, ''); assert.equal(after.noTag, true);
                assert.match(after.status, /Адрес подставлен/);
            } else if (['error', 'http-error', 'malformed-address', 'nonboolean-verified'].includes(scenario)) {
                assert.equal(after.address, initial); assert.equal(after.tag, 'old memo'); assert.equal(after.noTag, false);
                assert.doesNotMatch(after.status, /Адрес подставлен/);
            } else assert.deepEqual(after, beforeResponse, 'obsolete verification must not overwrite newer intent or feedback');
            assert.equal(await page.evaluate(() => tcPending), false);
            assert.deepEqual(report.unexpectedWrites, []); report.checks.push({width, scenario, result: 'PASS'});
            if (scenario === 'success') await page.screenshot({path: path.join(output, width + '-verified.png')});
            await context.close();
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
