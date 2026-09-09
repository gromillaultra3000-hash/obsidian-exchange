'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), crypto = require('node:crypto');
const {chromium} = require('playwright-core');
const [sourcePath, output] = process.argv.slice(2), source = fs.readFileSync(sourcePath, 'utf8');
const hash = x => crypto.createHash('sha256').update(x).digest('hex');
const origin = 'https://tonconnect-preparation.invalid', initial = 'EQ' + 'A'.repeat(46);
const report = {sourceSha256: hash(source), runnerSha256: hash(fs.readFileSync(__filename)),
    playwrightVersion: require('playwright-core/package.json').version, checks: [], unexpectedWrites: [], verificationRequests: [], pageErrors: []};
fs.mkdirSync(output, {recursive: true});
async function main() {
    assert.notEqual(process.getuid(), 0);
    const browser = await chromium.launch({executablePath: '/opt/google/chrome/chrome', chromiumSandbox: true, headless: true});
    report.browserVersion = browser.version(); let page;
    try {
        for (const width of [320, 390]) for (const scenario of ['route', 'success', 'own-disconnect', 'disconnect-route', 'disconnect-away-back', 'disconnect-status', 'disconnect-error', 'modal-edit', 'modal-status', 'modal-edit-proof', 'modal-proof', 'away-back', 'json-delay', 'stale-error', 'http-error', 'bad-payload', 'duplicate', 'retry', 'timeout']) {
            const context = await browser.newContext({viewport: {width, height: 844}, serviceWorkers: 'block'});
            await context.addInitScript(() => {
                window.Telegram = {WebApp: {initData: '', initDataUnsafe: {}, expand() {}, ready() {}, onEvent() {}, setHeaderColor() {}, setBackgroundColor() {}, setBottomBarColor() {}}};
                window.TON_CONNECT_UI = {};
                const fetchNative = window.fetch.bind(window);
                window.fetch = async (...args) => {
                    const response = await fetchNative(...args);
                    if (String(args[0]) === '/api/tonconnect/payload' && window.__holdJson) {
                        const jsonNative = response.json.bind(response);
                        response.json = async () => {const data = await jsonNative(); window.__jsonReached = true;
                            await new Promise(resolve => {window.__releaseJson = resolve;}); return data;};
                    }
                    return response;
                };
            });
            const pending = [];
            await context.route('**/*', async route => {
                const r = route.request(), u = new URL(r.url());
                if (scenario === 'modal-proof' && u.origin === origin && u.pathname === '/api/tonconnect/verify' && r.method() === 'POST') {
                    report.verificationRequests.push({width, scenario, body: r.postDataJSON()});
                    return route.fulfill({contentType: 'application/json', body: JSON.stringify({verified: true, address: 'EQ' + 'B'.repeat(46)})});
                }
                if (r.method() !== 'GET') {report.unexpectedWrites.push(u.origin + u.pathname); return route.abort();}
                if (u.origin !== origin) return route.abort();
                if (u.pathname === '/api/tonconnect/payload') {pending.push(route); return;}
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
            await page.evaluate(scenario => {
                window.__oeTonConnectFailed = false;
                window.__calls = {params: [], modals: [], disconnects: 0, closes: 0}; window.__holdJson = scenario === 'json-delay';
                tcUI = {
                    connected: scenario.includes('disconnect'),
                    setConnectRequestParameters(value) {window.__calls.params.push(structuredClone(value));},
                    async disconnect() {
                        window.__calls.disconnects++;
                        if (scenario === 'disconnect-error') throw new Error('Synthetic disconnect error');
                        if (['disconnect-route', 'disconnect-away-back', 'disconnect-status'].includes(scenario)) {
                            window.__disconnectStarted = true; await new Promise(resolve => {window.__releaseDisconnect = resolve;});
                        }
                        await tcHandleWallet(null); this.connected = false;
                    },
                    async openModal() {
                        window.__calls.modals.push({currency: document.getElementById('currency').value, address: document.getElementById('address').value});
                        if (scenario.startsWith('modal-')) {window.__modalStarted = true; await new Promise(resolve => {window.__releaseModal = resolve;});}
                    },
                    closeModal() {window.__calls.closes++;}
                };
            }, scenario);
            if (scenario === 'timeout') await page.clock.install();
            await page.evaluate(() => {window.__preparation = tcConnect();});
            for (let n = 0; pending.length < 1 && n < 100; n++) await new Promise(resolve => setTimeout(resolve, 10));
            assert.equal(pending.length, 1);
            if (scenario === 'duplicate') {await page.evaluate(() => tcConnect()); assert.equal(pending.length, 1);}
            if (scenario === 'route' || scenario === 'stale-error') {
                await page.locator('#currency').selectOption('BTC'); await page.locator('#address').fill('bc1' + 'q'.repeat(87));
            }
            if (scenario === 'away-back') {await page.locator('#address').fill('other'); await page.locator('#address').fill(initial);}
            const valid = {payload: 'synthetic-payload-1'};
            if (scenario === 'timeout') await page.clock.fastForward(8001);
            else if (scenario === 'stale-error' || scenario === 'retry') await pending[0].abort('failed');
            else await pending[0].fulfill({status: scenario === 'http-error' ? 403 : 200, contentType: 'application/json',
                body: JSON.stringify(scenario === 'bad-payload' ? {payload: {bad: true}} : valid)});
            if (scenario === 'json-delay') {
                await page.waitForFunction(() => window.__jsonReached === true);
                await page.locator('#address').fill('edited during JSON'); await page.evaluate(() => window.__releaseJson());
            }
            if (['disconnect-route', 'disconnect-away-back', 'disconnect-status'].includes(scenario)) {
                await page.waitForFunction(() => window.__disconnectStarted === true);
                if (scenario === 'disconnect-route') await page.locator('#currency').selectOption('BTC');
                else if (scenario === 'disconnect-status') await page.evaluate(() => tcHandleWallet({account: {address: 'synthetic replacement'}}));
                else {await page.locator('#address').fill('other'); await page.locator('#address').fill(initial);}
                await page.evaluate(() => window.__releaseDisconnect());
            }
            if (scenario.startsWith('modal-')) {
                await page.waitForFunction(() => window.__modalStarted === true);
                if (scenario === 'modal-edit' || scenario === 'modal-edit-proof') await page.locator('#address').fill('edited while modal opening');
                if (scenario === 'modal-edit-proof' || scenario === 'modal-proof') {
                    await page.evaluate(() => tcHandleWallet({account: {address: 'synthetic'}, connectItems: {tonProof: {proof: {payload: 'synthetic-payload-1', synthetic: true}}}}));
                    assert.equal(report.verificationRequests.filter(x => x.width === width).length, scenario === 'modal-proof' ? 1 : 0);
                }
                else if (scenario === 'modal-status') await page.evaluate(() => tcHandleWallet({account: {address: 'synthetic replacement'}}));
                await page.evaluate(() => window.__releaseModal());
            }
            await page.evaluate(() => window.__preparation);
            let calls = await page.evaluate(() => window.__calls);
            // Unowned status events cannot invalidate the current explicit intent.
            const succeeded = ['success', 'own-disconnect', 'duplicate', 'disconnect-status', 'modal-status'].includes(scenario);
            assert.equal(calls.modals.length, succeeded || scenario.startsWith('modal-') ? 1 : 0, 'stale/failed preparation must not open wallet modal');
            if (scenario.startsWith('modal-')) assert.equal(calls.closes, scenario === 'modal-status' ? 0 : 1, 'only stale owned opening is closed');
            if (!succeeded) assert.equal(calls.params.at(-1), null, 'failed preparation clears SDK parameters');
            if (scenario === 'retry') {
                await page.evaluate(() => {window.__preparation = tcConnect();});
                for (let n = 0; pending.length < 2 && n < 100; n++) await new Promise(resolve => setTimeout(resolve, 10));
                assert.equal(pending.length, 2);
                await pending[1].fulfill({contentType: 'application/json', body: JSON.stringify({payload: 'synthetic-payload-2'})});
                await page.evaluate(() => window.__preparation);
                calls = await page.evaluate(() => window.__calls); assert.equal(calls.modals.length, 1);
            }
            assert.equal(await page.locator('#tc-connect').isDisabled(), false);
            assert.deepEqual(report.unexpectedWrites, []); report.checks.push({width, scenario, result: 'PASS', payloadReads: pending.length, modalCalls: calls.modals.length});
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
