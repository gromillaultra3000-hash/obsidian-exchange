'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), crypto = require('node:crypto');
const {chromium} = require('playwright-core');
const [sourcePath, output] = process.argv.slice(2), source = fs.readFileSync(sourcePath, 'utf8');
const hash = x => crypto.createHash('sha256').update(x).digest('hex');
const origin = 'https://tonconnect-timeout.invalid', initial = 'EQ' + 'A'.repeat(46), verified = 'EQ' + 'B'.repeat(46);
const report = {sourceSha256: hash(source), runnerSha256: hash(fs.readFileSync(__filename)),
    playwrightVersion: require('playwright-core/package.json').version, checks: [], unexpectedWrites: [], pageErrors: []};
fs.mkdirSync(output, {recursive: true});
async function main() {
    assert.notEqual(process.getuid(), 0);
    const browser = await chromium.launch({executablePath: '/opt/google/chrome/chrome', chromiumSandbox: true, headless: true});
    report.browserVersion = browser.version(); let page;
    try {
        for (const width of [320, 390]) for (const scenario of ['timeout-retry', 'body-late', 'edit-timeout', 'disconnect-timeout', 'fresh']) {
            const context = await browser.newContext({viewport: {width, height: 844}, serviceWorkers: 'block'});
            await context.addInitScript(() => {
                window.Telegram = {WebApp: {initData: '', initDataUnsafe: {}, expand() {}, ready() {}, onEvent() {}, setHeaderColor() {}, setBackgroundColor() {}, setBottomBarColor() {}}};
                window.TON_CONNECT_UI = {};
            });
            const payloads = [], verifications = []; let heldPayload, heldVerify, failVerify = false;
            await context.route('**/*', async route => {
                const r = route.request(), u = new URL(r.url());
                if (u.origin === origin && u.pathname === '/api/tonconnect/verify' && r.method() === 'POST') {
                    verifications.push(r.postDataJSON());
                    if (scenario !== 'fresh' && scenario !== 'body-late') {heldVerify = route; return;}
                    return route.fulfill({status: failVerify ? 503 : 200, contentType: 'application/json', body: JSON.stringify({verified: true, address: verified})});
                }
                if (r.method() !== 'GET') {report.unexpectedWrites.push(u.origin + u.pathname); return route.abort();}
                if (u.origin !== origin) return route.abort();
                if (u.pathname === '/api/tonconnect/payload') {
                    const payload = 'synthetic-nonce-' + (payloads.length + 1); payloads.push(payload);
                    if (scenario === 'old-during-new-prep' && payloads.length === 2) {heldPayload = route; return;}
                    return route.fulfill({contentType: 'application/json', body: JSON.stringify({payload})});
                }
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
            await page.evaluate(() => {
                window.__oeTonConnectFailed = false; window.__params = []; window.__modals = 0;
                tcUI = {connected: false, setConnectRequestParameters(value) {window.__params.push(structuredClone(value));},
                    async openModal() {window.__modals++;}, closeModal() {}, async disconnect() {this.connected = false; await tcHandleWallet(null);}};
            });
            const prepare = () => page.evaluate(() => tcConnect());
            const callback = payload => page.evaluate(payload => tcHandleWallet({account: {address: 'synthetic-account'}, connectItems: {tonProof: {proof: {payload, synthetic: true}}}}), payload);
            const state = () => page.evaluate(() => ({address: document.getElementById('address').value, status: document.getElementById('tc-msg').textContent,
                tag: document.getElementById('dest_tag').value, noTag: document.getElementById('no_tag').checked}));
            await page.clock.install();
            if (scenario === 'body-late') await page.evaluate(() => {
                const nativeFetch = window.fetch.bind(window); window.__heldBodies = [];
                window.fetch = async (...args) => {
                    const res = await nativeFetch(...args);
                    if (String(args[0]).includes('/tonconnect/verify')) {
                        const nativeJson = res.json.bind(res);
                        res.json = async () => {const data = await nativeJson(); await new Promise(resolve => window.__heldBodies.push(resolve)); return data;};
                    }
                    return res;
                };
            });
            await prepare(); assert.equal(payloads.length, 1);
            if (scenario === 'fresh') {
                await callback(payloads[0]); assert.equal((await state()).address, verified); assert.equal(verifications.length, 1);
            } else {
                const start = nonce => page.evaluate(nonce => {window.__verification = tcHandleWallet({account: {address: 'synthetic-account'}, connectItems: {tonProof: {proof: {payload: nonce, synthetic: true}}}});}, nonce);
                await start(payloads[0]);
                await page.waitForFunction(() => tcPending);
                if (scenario === 'body-late') await page.waitForFunction(() => window.__heldBodies.length === 1);
                else {for(let n=0;!heldVerify&&n<100;n++)await new Promise(r=>setTimeout(r,10));assert.ok(heldVerify);}
                if (scenario === 'edit-timeout') await page.locator('#address').fill('EQ' + 'C'.repeat(46));
                if (scenario === 'disconnect-timeout') await page.evaluate(() => tcHandleWallet(null));
                const before = await state();
                await page.clock.fastForward(8001);
                assert.equal(await page.evaluate(() => tcPending), false, 'deadline must release pending verification');
                await page.evaluate(() => window.__verification);
                assert.equal(payloads.length, 1, 'no automatic retry');
                if (scenario.endsWith('-timeout')) assert.deepEqual(await state(), before);
                else {
                    assert.match((await state()).status, /слишком много времени/);
                    assert.equal((await state()).address, initial);
                    await page.screenshot({path: path.join(output, width + '-' + scenario + '.png')});
                    heldVerify = null; await prepare(); await start(payloads[1]);
                    if (scenario === 'body-late') {
                        await page.waitForFunction(() => window.__heldBodies.length === 2);
                        await page.evaluate(() => window.__heldBodies[0]());
                        assert.equal(await page.evaluate(() => tcPending), true);
                        assert.equal((await state()).address, initial);
                        await page.evaluate(() => window.__heldBodies[1]());
                    } else {
                        for(let n=0;!heldVerify&&n<100;n++)await new Promise(r=>setTimeout(r,10));assert.ok(heldVerify);
                        await heldVerify.fulfill({contentType:'application/json',body:JSON.stringify({verified:true,address:verified})});
                    }
                    await page.evaluate(() => window.__verification);
                    assert.equal((await state()).address, verified); assert.equal(verifications.length, 2);
                    assert.equal(await page.evaluate(() => tcPending), false);
                }
            }
            assert.deepEqual(report.unexpectedWrites, []); report.checks.push({width, scenario, result: 'PASS', payloadReads: payloads.length, verificationRequests: verifications.length});
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
