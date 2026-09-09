'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), crypto = require('node:crypto');
const {chromium} = require('playwright-core');
const [sourcePath, output] = process.argv.slice(2), source = fs.readFileSync(sourcePath, 'utf8');
const hash = x => crypto.createHash('sha256').update(x).digest('hex');
const origin = 'https://tonconnect-payload-wait.invalid', initial = 'EQ' + 'A'.repeat(46), verified = 'EQ' + 'B'.repeat(46);
const report = {sourceSha256: hash(source), runnerSha256: hash(fs.readFileSync(__filename)),
    playwrightVersion: require('playwright-core/package.json').version, checks: [], unexpectedWrites: [], pageErrors: []};
fs.mkdirSync(output, {recursive: true});
async function main() {
    assert.notEqual(process.getuid(), 0);
    const browser = await chromium.launch({executablePath: '/opt/google/chrome/chrome', chromiumSandbox: true, headless: true});
    report.browserVersion = browser.version(); let page;
    try {
        for (const width of [320, 390]) for (const scenario of ['headers', 'body', 'headers-edit', 'body-edit', 'delayed-clock', 'fresh']) {
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
            await page.evaluate(scenario => {
                window.__oeTonConnectFailed = false; window.__modals = 0; window.__reads = 0; window.__held = [];
                tcUI = {connected:false, setConnectRequestParameters() {}, async openModal(){window.__modals++;}, closeModal(){}, async disconnect(){}};
                const nativeFetch=window.fetch.bind(window);
                window.fetch=async (url,init)=>{
                    if(!String(url).includes('/tonconnect/payload'))return nativeFetch(url,init);
                    const index=++window.__reads;
                    const response=await nativeFetch(url,{...init,signal:undefined});
                    if(scenario==='fresh')return response;
                    if(scenario.startsWith('body')) {
                        const nativeJson=response.json.bind(response);
                        response.json=async()=>{const data=await nativeJson();await new Promise(resolve=>window.__held[index]=resolve);return data;};
                    } else await new Promise(resolve=>window.__held[index]=resolve);
                    return response;
                };
            }, scenario);
            const state=()=>page.evaluate(()=>({address:document.getElementById('address').value,status:document.getElementById('tc-msg').textContent}));
            await page.clock.install();
            await page.locator('#tc-connect').click();
            if(scenario==='fresh') {
                await page.waitForFunction(()=>window.__modals===1);
            } else {
                await page.waitForFunction(()=>!!window.__held[1]);
                if(scenario.endsWith('-edit'))await page.locator('#address').fill('EQ'+'C'.repeat(46));
                const before=await state();
                if(scenario==='delayed-clock') {
                    await page.evaluate(()=>{window.__realDateNow=Date.now;const captured=Date.now();Date.now=()=>captured+8001;window.__held[1]();});
                    await page.waitForFunction(()=>tcPreparation===null);
                    await page.evaluate(()=>Date.now=window.__realDateNow);
                } else await page.clock.fastForward(8001);
                assert.equal(await page.evaluate(()=>tcPreparation),null,'payload deadline must release preparation');
                assert.equal(await page.locator('#tc-connect').isDisabled(),false);
                assert.equal(await page.evaluate(()=>tcAvailable()),true,'payload expiry must allow explicit retry');
                assert.equal((await state()).address,before.address);
                if(scenario.endsWith('-edit'))assert.equal((await state()).status,before.status);
                assert.equal(await page.evaluate(()=>window.__modals),0);
                await page.screenshot({path:path.join(output,width+'-'+scenario+'.png')});
                await page.locator('#tc-connect').click();
                await page.waitForFunction(()=>!!window.__held[2]);
                await page.evaluate(()=>window.__held[1]());
                assert.equal(await page.evaluate(()=>tcPreparation!==null),true,'late loser cannot release current attempt');
                assert.equal(await page.locator('#tc-connect').isDisabled(),true);
                assert.equal(await page.evaluate(()=>window.__modals),0);
                await page.evaluate(()=>window.__held[2]());
                await page.waitForFunction(()=>window.__modals===1 && tcPreparation===null);
                await page.evaluate(payload=>tcHandleWallet({account:{},connectItems:{tonProof:{proof:{payload}}}}),payloads[0]);
                assert.equal(verifications.length,0,'old challenge cannot verify retry');
            }
            await page.evaluate(payload=>tcHandleWallet({account:{},connectItems:{tonProof:{proof:{payload}}}}),payloads.at(-1));
            assert.equal(verifications.length,1);assert.equal((await state()).address,verified);
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
