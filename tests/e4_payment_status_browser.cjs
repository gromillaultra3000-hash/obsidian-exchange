'use strict';

// Exact synthetic handler output only. The existing launcher supplies the
// disconnected, non-root, sandboxed unit and verifies complete process cleanup.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const {chromium} = require('playwright-core');
const [sourcePath, outputDir] = process.argv.slice(2);
const source = fs.readFileSync(sourcePath);
const fixtures = JSON.parse(source);
const sha = value => crypto.createHash('sha256').update(value).digest('hex');
const report = {schemaVersion: 'e4-payment-status-browser.v1', sourceSha256: sha(source),
    runnerSha256: sha(fs.readFileSync(__filename)), inputs: fixtures.inputs,
    playwrightVersion: require('playwright-core/package.json').version,
    checks: [], requests: [], blockedRequests: [], pageErrors: [], terminalObservations: []};
fs.mkdirSync(outputDir, {recursive: true});

async function main() {
    assert.notEqual(process.getuid(), 0, 'must use the isolated non-root launcher');
    const browser = await chromium.launch({executablePath: '/opt/google/chrome/chrome',
        chromiumSandbox: true, headless: true});
    report.browserVersion = browser.version();
    try {
        for (const viewport of [{width: 320, height: 568}, {width: 390, height: 844}]) {
            const context = await browser.newContext({viewport, locale: 'ru-RU', serviceWorkers: 'block'});
            let current, pollData, failPoll = false;
            await context.addInitScript(() => {
                window.__copied = [];
                Object.defineProperty(navigator, 'clipboard', {value: {
                    writeText: async value => {window.__copied.push(value);}
                }});
            });
            await context.route('**/*', async route => {
                const req = route.request(), url = new URL(req.url());
                if (url.origin === 'https://payment.invalid' && req.method() === 'GET') {
                    if (url.pathname === '/fixture') return route.fulfill({status: 200,
                        contentType: 'text/html; charset=utf-8', body: current.html});
                    if (/^\/api\/order\/\d+$/.test(url.pathname) && url.searchParams.get('token')?.startsWith('synthetic-')) {
                        report.requests.push({width: viewport.width, path: url.pathname, method: req.method(),
                            response: failPoll ? 503 : 200});
                        return route.fulfill({status: failPoll ? 503 : 200,
                            contentType: 'application/json', body: JSON.stringify(pollData)});
                    }
                }
                report.blockedRequests.push({url: url.origin + url.pathname, method: req.method()});
                return route.abort('blockedbyclient');
            });
            const page = await context.newPage();
            page.setDefaultTimeout(4000);
            page.on('pageerror', error => report.pageErrors.push(error.message));
            await page.clock.install();
            for (const fixture of fixtures.pages) {
                current = fixture;
                pollData = fixture.expected;
                await page.goto('https://payment.invalid/fixture', {waitUntil: 'load'});
                const body = await page.locator('body').innerText();
                assert.equal(await page.locator('.reqs').count(), fixture.hasRequisites ? 1 : 0, fixture.name);
                if (!fixture.hasRequisites) {
                    assert.equal(await page.locator('.cp').count(), 0, fixture.name + ': no payment copy');
                    assert.equal(await page.getByText('Перейти к оплате', {exact: true}).count(), 0);
                }
                const state = fixture.expected.status;
                if (state === 'paid') assert.match(body, /Оплата получена/);
                if (state === 'sent') assert.match(body, /отправлен/);
                if (['expired', 'failed', 'cancelled'].includes(state) && fixture.expected.receipt) {
                    assert.match(body, /[Зз]аявка закрыта/);
                    assert.match(body, /[Чч]ек/);
                }
                if (state === 'pending' && fixture.expected.dead) {
                    assert.match(body, /[Нн]е (переводите|платите)|[Пп]овторно не/);
                    assert.doesNotMatch(body, /Обычно до 30 минут/);
                }
                assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false,
                    fixture.name + ': narrow viewport overflow');
                assert.equal(await page.evaluate(() => window.__injected), undefined, fixture.name + ': injected code');
                if (fixture.maliciousValue) {
                    assert.equal(await page.locator('script').count(), 1);
                    const cp = page.locator('.row.main .cp');
                    assert.equal(await cp.getAttribute('data-value'), fixture.maliciousValue);
                    await cp.click();
                    assert.deepEqual(await page.evaluate(() => window.__copied), [fixture.maliciousValue]);
                    assert.equal(await page.evaluate(() => window.__injected), undefined);
                }
                if (viewport.width === 320 && ['failed-absent', 'cancelled-absent'].includes(fixture.name)) {
                    report.terminalObservations.push({canonicalStatus: state,
                        visiblePill: await page.locator('.pill').innerText(),
                        visibleLabel: await page.locator('#view > .lbl').innerText(),
                        noPaymentInstructions: true});
                }
                if (['pending-stored', 'pending-sent', 'stale', 'active', 'attack',
                     'numeric-cancelled-absent', 'failed-absent'].includes(fixture.name)) {
                    await page.screenshot({path: path.join(outputDir, `${viewport.width}-pay-${fixture.name}.png`), fullPage: true});
                }
                report.checks.push({width: viewport.width, name: fixture.name, result: 'PASS'});
            }
            current = fixtures.pages.find(f => f.name === 'active');
            pollData = current.expected;
            await page.goto('https://payment.invalid/fixture', {waitUntil: 'load'});
            assert.equal(await page.locator('.reqs').count(), 1);
            failPoll = true;
            await page.evaluate(() => poll());
            assert.equal(await page.locator('.reqs').count(), 1, '503 preserves prior known state');
            failPoll = false;
            for (const name of ['pending-absent', 'pending-stored', 'pending-sent', 'paid-sent', 'sent-sent']) {
                pollData = fixtures.pages.find(f => f.name === name).expected;
                await page.evaluate(() => poll());
                assert.equal(await page.locator('.reqs').count(), 0, name + ': poll suppresses payment');
                const text = await page.locator('#view').innerText();
                if (name === 'paid-sent') assert.match(text, /Оплата получена/);
                if (name === 'sent-sent') assert.match(text, /отправлена/);
                report.checks.push({width: viewport.width, name: 'poll-' + name, result: 'PASS'});
            }
            assert.equal(await page.locator('a.tx').count(), 1, 'canonical sent transaction link');
            assert.match(await page.locator('a.tx').getAttribute('href'), /^https:\/\//);
            report.checks.push({width: viewport.width, name: '503-preservation-and-canonical-transaction-link', result: 'PASS'});
            await context.close();
        }
        assert.deepEqual(report.pageErrors, []);
        assert.deepEqual(report.blockedRequests, []);
        assert.ok(report.requests.every(r => r.method === 'GET'));
        report.result = 'PASS';
    } finally {
        await browser.close();
        fs.writeFileSync(path.join(outputDir, 'report.json'), JSON.stringify(report, null, 2) + '\n');
    }
}
main().catch(error => {process.stderr.write(error.stack + '\n'); process.exitCode = 1;});
