'use strict';

// Exact synthetic /pay output. Only the established isolated non-root launcher
// may run this browser; request routing is deny-by-default.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const {chromium} = require('playwright-core');
const [sourcePath, outputDir] = process.argv.slice(2);
const source = fs.readFileSync(sourcePath), fixtures = JSON.parse(source);
const sha = data => crypto.createHash('sha256').update(data).digest('hex');
const now = fixtures.referenceNowMs;
const report = {schemaVersion: 'e4-payment-expiry-browser.v1', sourceSha256: sha(source),
    runnerSha256: sha(fs.readFileSync(__filename)), inputs: fixtures.inputs,
    playwrightVersion: require('playwright-core/package.json').version,
    checks: [], requests: [], blockedRequests: [], pageErrors: [], timezoneInstants: []};
fs.mkdirSync(outputDir, {recursive: true});

async function main() {
    assert.notEqual(process.getuid(), 0, 'use the isolated non-root launcher');
    const browser = await chromium.launch({executablePath: '/opt/google/chrome/chrome',
        chromiumSandbox: true, headless: true});
    report.browserVersion = browser.version();
    try {
        for (const config of [
            {timezoneId: 'UTC', width: 320, height: 568, full: true},
            {timezoneId: 'Asia/Kolkata', width: 320, height: 568, full: false},
            {timezoneId: 'America/Los_Angeles', width: 390, height: 844, full: true}
        ]) {
            const context = await browser.newContext({timezoneId: config.timezoneId,
                viewport: {width: config.width, height: config.height}, locale: 'ru-RU', serviceWorkers: 'block'});
            let current, pollData, failPoll = false;
            await context.route('**/*', async route => {
                const request = route.request(), url = new URL(request.url());
                if (url.origin === 'https://expiry.invalid' && request.method() === 'GET') {
                    if (url.pathname === '/fixture') return route.fulfill({status: 200,
                        contentType: 'text/html; charset=utf-8', body: current.html});
                    if (/^\/api\/order\/\d+$/.test(url.pathname) && url.searchParams.get('token')?.startsWith('synthetic-')) {
                        report.requests.push({timezone: config.timezoneId, path: url.pathname,
                            method: request.method(), responseCode: failPoll ? 503 : 200, status: pollData.status});
                        return route.fulfill({status: failPoll ? 503 : 200,
                            contentType: 'application/json', body: JSON.stringify(pollData)});
                    }
                }
                report.blockedRequests.push({method: request.method(), path: url.origin + url.pathname});
                return route.abort('blockedbyclient');
            });
            const page = await context.newPage();
            page.setDefaultTimeout(4000);
            page.on('pageerror', error => report.pageErrors.push(error.message));
            await page.clock.install({time: now - 1000});
            await page.clock.pauseAt(now);
            async function open(fixture) {
                current = fixture; pollData = fixture.expected;
                await page.clock.setSystemTime(now);
                await page.goto('https://expiry.invalid/fixture', {waitUntil: 'load'});
            }
            const checkLayout = async () => assert.equal(await page.evaluate(() =>
                document.documentElement.scrollWidth > innerWidth + 1), false);
            for (const fixture of fixtures.pages.filter(f => config.full || f.sameInstantAcrossTimezones)) {
                await open(fixture);
                const actual = await page.evaluate(() => ({parsed: paymentExpiryMs(C.expiresAt),
                    status: C.status, localExpired: _localExpired, noTimer: _timer === null}));
                assert.equal(actual.parsed, fixture.expectedMs, fixture.name);
                assert.equal(actual.status, fixture.expected.status);
                const body = await page.locator('body').innerText();
                assert.doesNotMatch(body, /NaN|Invalid Date/);
                if (fixture.kind === 'future' || fixture.kind === 'boundary') {
                    const seconds = Math.floor((fixture.expectedMs - now) / 1000);
                    const expected = String(Math.floor(seconds/60)).padStart(2,'0') + ':' + String(seconds%60).padStart(2,'0');
                    assert.equal(await page.locator('#timer b').innerText(), expected);
                    assert.equal(actual.localExpired, false);
                    assert.equal(await page.locator('.reqs').count(), 1);
                } else if (fixture.kind === 'unknown') {
                    assert.equal(await page.locator('#timer').innerText(), 'Срок действия реквизитов уточняется.');
                    assert.equal(actual.localExpired, false);
                    assert.equal(actual.noTimer, true);
                    assert.equal(await page.locator('.reqs').count(), 1, 'existing active-session controls preserved');
                    assert.doesNotMatch(body, /Время истекло|Срок оплаты заявки истёк/);
                } else {
                    assert.equal(await page.locator('.reqs,.cp,.qr,#timer').count(), 0);
                    assert.equal(actual.noTimer, true);
                    if (fixture.kind === 'past' && fixture.expected.receipt !== 'sent') assert.equal(actual.localExpired, true);
                    if (fixture.expected.verification && fixture.expected.status === 'pending') assert.match(body, /Требуется подтверждение/);
                    if (fixture.expected.receipt && fixture.expected.status === 'pending') assert.match(body, /[Чч]ек|[Фф]айл/);
                    if (fixture.expected.status === 'paid') assert.match(body, /Оплата получена/);
                    if (fixture.expected.status === 'sent') assert.match(body, /отправлена/);
                    const terminal = {expired: 'Время истекло', failed: 'Заявка не выполнена', cancelled: 'Заявка отменена'};
                    if (terminal[fixture.expected.status]) assert.equal(await page.locator('#view > .pill').innerText(), terminal[fixture.expected.status]);
                }
                await checkLayout();
                if (fixture.sameInstantAcrossTimezones) report.timezoneInstants.push({name: fixture.name,
                    timezone: config.timezoneId, expectedMs: fixture.expectedMs, parsedMs: actual.parsed});
                report.checks.push({name: fixture.name, timezone: config.timezoneId, width: config.width, result: 'PASS'});
                if (config.timezoneId === 'UTC' && ['utc-offset', 'positive-offset', 'invalid-calendar',
                    'past-stored', 'verification-stored'].includes(fixture.name)) {
                    await page.screenshot({path: path.join(outputDir, `${config.width}-expiry-${fixture.name}.png`), fullPage: true});
                }
            }
            if (config.full) {
                await open(fixtures.pages.find(f => f.name === 'expiry-boundary'));
                assert.equal(await page.locator('#timer b').innerText(), '00:02');
                await page.clock.runFor(1000);
                assert.equal(await page.locator('#timer b').innerText(), '00:01');
                await page.clock.runFor(1000);
                assert.deepEqual(await page.evaluate(() => ({status: C.status, expired: _localExpired, timer: _timer})),
                    {status: 'pending', expired: true, timer: null});
                assert.equal(await page.locator('.reqs,.cp,#timer').count(), 0);
                report.checks.push({name: 'actual-interval-crosses-expiry-without-canonical-mutation', timezone: config.timezoneId, result: 'PASS'});
                const before = report.requests.length;
                failPoll = true;
                await page.evaluate(() => poll());
                failPoll = false;
                assert.equal(report.requests.length, before + 1);
                assert.equal(await page.evaluate(() => C.status), 'pending');
                assert.equal(await page.locator('.reqs').count(), 0);
                report.checks.push({name: 'expired-page-still-polls-and-503-preserves-state', timezone: config.timezoneId, result: 'PASS'});
                for (const name of ['past-stored', 'past-sent', 'canonical-paid', 'canonical-sent']) {
                    pollData = fixtures.pages.find(f => f.name === name).expected;
                    await page.evaluate(() => poll());
                    assert.equal(await page.evaluate(() => C.status), pollData.status);
                    assert.equal(await page.locator('.reqs,.cp,#timer').count(), 0);
                    const body = await page.locator('#view').innerText();
                    if (pollData.status === 'pending') assert.match(body, /[Чч]ек|[Фф]айл/);
                    if (pollData.status === 'paid') assert.match(body, /Оплата получена/);
                    if (pollData.status === 'sent') assert.match(body, /отправлена/);
                    report.checks.push({name: 'poll-after-local-expiry-to-' + name, timezone: config.timezoneId, result: 'PASS'});
                }
                await open(fixtures.pages.find(f => f.name === 'utc-z'));
                assert.equal(await page.evaluate(() => _timer !== null), true);
                await page.evaluate(() => {C.expiresAt = 'invalid'; startTimer();});
                assert.equal(await page.evaluate(() => _timer), null);
                assert.equal(await page.locator('#timer').innerText(), 'Срок действия реквизитов уточняется.');
                await page.clock.runFor(2000);
                assert.equal(await page.locator('#timer').innerText(), 'Срок действия реквизитов уточняется.');
                assert.equal(await page.evaluate(() => _localExpired), false);
                report.checks.push({name: 'invalid-replacement-clears-old-timer', timezone: config.timezoneId, result: 'PASS'});
            }
            await context.close();
        }
        assert.equal(report.timezoneInstants.length, 27);
        assert.deepEqual(report.pageErrors, []);
        assert.deepEqual(report.blockedRequests, []);
        assert.ok(report.requests.every(request => request.method === 'GET'));
        report.result = 'PASS';
    } finally {
        await browser.close();
        fs.writeFileSync(path.join(outputDir, 'report.json'), JSON.stringify(report, null, 2) + '\n');
    }
}
main().catch(error => {process.stderr.write(error.stack + '\n'); process.exitCode = 1;});
