'use strict';

// Exact synthetic /pay output, no live site. The established launcher supplies
// non-root sandboxed Chrome, PrivateNetwork, time limits and verified cleanup.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const {chromium} = require('playwright-core');
const [sourcePath, outputDir] = process.argv.slice(2);
const source = fs.readFileSync(sourcePath), fixtures = JSON.parse(source);
const sha = value => crypto.createHash('sha256').update(value).digest('hex');
const stored = 'Файл чека получен, но платёжному партнёру пока не передан.';
const sent = 'Чек получен и передан платёжному партнёру.';
const report = {schemaVersion: 'e4-payment-pending-receipt-browser.v1', sourceSha256: sha(source),
    runnerSha256: sha(fs.readFileSync(__filename)), inputs: fixtures.inputs,
    playwrightVersion: require('playwright-core/package.json').version,
    checks: [], requests: [], blockedRequests: [], pageErrors: [], expiryFormatObservations: []};
fs.mkdirSync(outputDir, {recursive: true});

async function main() {
    assert.notEqual(process.getuid(), 0, 'use the isolated non-root launcher');
    const browser = await chromium.launch({executablePath: '/opt/google/chrome/chrome',
        chromiumSandbox: true, headless: true});
    report.browserVersion = browser.version();
    try {
        for (const viewport of [{width: 320, height: 568}, {width: 390, height: 844}]) {
            const context = await browser.newContext({viewport, locale: 'ru-RU', serviceWorkers: 'block'});
            let current, pollData;
            await context.route('**/*', async route => {
                const req = route.request(), url = new URL(req.url());
                if (url.origin === 'https://pending-receipt.invalid' && req.method() === 'GET') {
                    if (url.pathname === '/fixture') return route.fulfill({status: 200,
                        contentType: 'text/html; charset=utf-8', body: current.html});
                    if (/^\/api\/order\/\d+$/.test(url.pathname) && url.searchParams.get('token')?.startsWith('synthetic-')) {
                        report.requests.push({method: req.method(), path: url.pathname,
                            responseStatus: pollData.status, receipt: pollData.receipt, width: viewport.width});
                        return route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify(pollData)});
                    }
                }
                report.blockedRequests.push({method: req.method(), path: url.origin + url.pathname});
                return route.abort('blockedbyclient');
            });
            const page = await context.newPage();
            page.setDefaultTimeout(4000);
            page.on('pageerror', error => report.pageErrors.push(error.message));
            await page.clock.install();
            const checkLayout = async () => assert.equal(await page.evaluate(() =>
                document.documentElement.scrollWidth > innerWidth + 1), false, 'narrow viewport overflow');
            async function checkPending(fixture, localExpired = false) {
                const {receipt, dead, verification} = fixture.expected;
                const body = await page.locator('body').innerText();
                if (fixture.numeric) {
                    assert.equal(await page.locator('.cp,.reqs,.qr').count(), 0);
                    if (receipt === 'stored') {
                        assert.equal(await page.locator('h1').innerText(), 'Файл чека получен');
                        assert.match(body, /Платёжному партнёру файл пока не передан/);
                    }
                    if (receipt === 'sent') assert.match(body, /Чек получен, реквизиты недоступны/);
                    if (!receipt) assert.doesNotMatch(body, /[Чч]ек|[Фф]айл/);
                    assert.match(body, /[Пп]овторно не переводите|не платите повторно/);
                } else {
                    assert.equal(await page.evaluate(() => C.status), 'pending');
                    const expectedEvidence = dead && (receipt === 'stored' || (receipt === 'sent' && !!verification));
                    assert.equal(await page.locator('.pending-receipt-evidence').count(), expectedEvidence ? 1 : 0);
                    if (expectedEvidence) {
                        const evidence = await page.locator('.pending-receipt-evidence').innerText();
                        assert.ok(evidence.startsWith(receipt === 'stored' ? stored : sent));
                        assert.doesNotMatch(evidence, /Оплата получена|платёж подтвержд|занимается сотрудник|до 30 минут/);
                        if (receipt === 'stored') assert.doesNotMatch(evidence, /^Чек получен и передан/);
                    }
                    if (verification) {
                        assert.match(body, /Требуется подтверждение/);
                        assert.ok(body.includes('Трейдер запросил ' + (verification === 'video' ? 'видео' : 'PDF-чек')));
                        assert.match(body, /Откройте бота и отправьте/);
                    }
                    const shouldPay = !dead && !verification && receipt !== 'sent' && !localExpired;
                    assert.equal(await page.locator('.reqs').count(), shouldPay ? 1 : 0);
                    if (!shouldPay) assert.equal(await page.locator('.cp,.qr').count(), 0);
                    if (dead && receipt && !verification) assert.match(body, /[Чч]ек|[Фф]айл/);
                    if (dead && receipt) assert.match(body, /[Пп]овторно не|не переводите повторно/);
                }
                assert.equal(await page.getByText('Перейти к оплате', {exact: true}).count(), 0);
                await checkLayout();
            }
            async function checkRegression(fixture) {
                const body = await page.locator('body').innerText();
                const {status, receipt} = fixture.expected;
                assert.equal(await page.evaluate(() => C.status), status);
                assert.equal(await page.locator('.pending-receipt-evidence,.reqs,.cp,.qr').count(), 0);
                if (status === 'paid') assert.match(body, /Оплата получена/);
                else if (status === 'sent') assert.match(body, /отправлена/);
                else {
                    const labels = {expired: 'Время истекло', failed: 'Заявка не выполнена', cancelled: 'Заявка отменена'};
                    assert.equal(await page.locator('#view > .pill').innerText(), labels[status]);
                    assert.doesNotMatch(body, /Требуется подтверждение/);
                    assert.ok(body.includes(receipt === 'stored' ? stored : sent));
                }
                await checkLayout();
            }
            for (const fixture of fixtures.pages) {
                current = fixture; pollData = fixture.expected;
                await page.goto('https://pending-receipt.invalid/fixture', {waitUntil: 'load'});
                if (fixture.expiryFormatProbe) {
                    const observation = await page.evaluate(() => ({
                        serializedExpiry: C.expiresAt,
                        originalISOValid: !Number.isNaN(new Date(C.expiresAt).getTime()),
                        pageConstructedISOValid: !Number.isNaN(new Date(C.expiresAt.replace(' ', 'T') +
                            (C.expiresAt.includes('Z') ? '' : 'Z')).getTime()),
                        timerText: document.getElementById('timer').innerText,
                        canonicalStatus: C.status
                    }));
                    assert.equal(observation.serializedExpiry, fixture.serializedExpiry);
                    if (viewport.width === 320) report.expiryFormatObservations.push(observation);
                    await page.screenshot({path: path.join(outputDir, `${viewport.width}-pending-receipt-aware-expiry.png`), fullPage: true});
                    continue;
                }
                if (fixture.pending) {
                    for (const localExpired of fixture.numeric ? [false] : [false, true]) {
                        if (!fixture.numeric) await page.evaluate(value => {_localExpired = value; render();}, localExpired);
                        await checkPending(fixture, localExpired);
                        if (!fixture.numeric && fixture.expected.dead && fixture.expected.receipt) {
                            await page.evaluate(() => {render(); render();});
                            await checkPending(fixture, localExpired);
                        }
                        report.checks.push({name: fixture.name, width: viewport.width, localExpired, result: 'PASS'});
                    }
                } else {
                    for (const staleDead of [false, true]) {
                        await page.evaluate(value => {C.dead = value; _localExpired = true; render();}, staleDead);
                        await checkRegression(fixture);
                        report.checks.push({name: fixture.name, width: viewport.width, staleDead, result: 'PASS'});
                    }
                }
                if (['pending-stored-unavailable-none', 'pending-stored-unavailable-video',
                     'pending-sent-unavailable-pdf', 'numeric-pending-stored-unavailable-none',
                     'pending-stored-active-none', 'failed-stored'].includes(fixture.name)) {
                    if (fixture.pending && !fixture.numeric) {
                        await page.evaluate(() => {_localExpired = false; render();});
                        await checkPending(fixture);
                    }
                    await page.screenshot({path: path.join(outputDir, `${viewport.width}-${fixture.name}.png`), fullPage: true});
                }
            }
            current = fixtures.pages.find(f => f.name === 'pending-absent-active-none');
            pollData = current.expected;
            await page.goto('https://pending-receipt.invalid/fixture', {waitUntil: 'load'});
            await page.evaluate(() => {C.receipt = 'future-receipt'; _localExpired = true; render();});
            assert.doesNotMatch(await page.locator('#view').innerText(), /Файл получен|Ваш файл у нас|Чек получен/);
            assert.equal(await page.locator('.pending-receipt-evidence').count(), 0);
            assert.equal(await page.evaluate(() => C.status), 'pending');
            report.checks.push({name: 'unknown-receipt-does-not-invent-stored-file', width: viewport.width, result: 'PASS'});
            await page.goto('https://pending-receipt.invalid/fixture', {waitUntil: 'load'});
            for (const name of ['pending-absent-unavailable-none', 'pending-stored-unavailable-none',
                                'pending-stored-unavailable-video', 'pending-sent-unavailable-video',
                                'pending-sent-unavailable-none', 'paid-sent', 'sent-sent']) {
                const fixture = fixtures.pages.find(f => f.name === name);
                pollData = fixture.expected;
                await page.evaluate(() => poll());
                if (fixture.pending) await checkPending(fixture);
                else await checkRegression(fixture);
                report.checks.push({name: 'poll-to-' + name, width: viewport.width, result: 'PASS'});
            }
            await context.close();
        }
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
