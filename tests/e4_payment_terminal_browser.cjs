'use strict';

// Exact /pay HTML emitted from the real handler over a synthetic SQLite ledger.
// Launch only with the established disconnected non-root sandboxed supervisor.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const {chromium} = require('playwright-core');
const [sourcePath, outputDir] = process.argv.slice(2);
const source = fs.readFileSync(sourcePath);
const fixtures = JSON.parse(source);
const sha = data => crypto.createHash('sha256').update(data).digest('hex');
const labels = {
    expired: {pill: 'Время истекло', label: 'Срок оплаты заявки истёк', numeric: 'Заявка истекла'},
    failed: {pill: 'Заявка не выполнена', label: 'Обмен по этой заявке не выполнен', numeric: 'Заявка не выполнена'},
    cancelled: {pill: 'Заявка отменена', label: 'Эта заявка отменена', numeric: 'Заявка отменена'}
};
const report = {schemaVersion: 'e4-payment-terminal-browser.v1', sourceSha256: sha(source),
    runnerSha256: sha(fs.readFileSync(__filename)), inputs: fixtures.inputs,
    playwrightVersion: require('playwright-core/package.json').version,
    checks: [], requests: [], blockedRequests: [], pageErrors: [], pendingReceiptObservations: []};
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
                if (url.origin === 'https://terminal.invalid' && req.method() === 'GET') {
                    if (url.pathname === '/fixture') return route.fulfill({status: 200,
                        contentType: 'text/html; charset=utf-8', body: current.html});
                    if (/^\/api\/order\/\d+$/.test(url.pathname) && url.searchParams.get('token')?.startsWith('synthetic-')) {
                        report.requests.push({method: req.method(), path: url.pathname,
                            responseStatus: pollData.status, width: viewport.width});
                        return route.fulfill({status: 200, contentType: 'application/json',
                            body: JSON.stringify(pollData)});
                    }
                }
                report.blockedRequests.push({method: req.method(), path: url.origin + url.pathname});
                return route.abort('blockedbyclient');
            });
            const page = await context.newPage();
            page.setDefaultTimeout(4000);
            page.on('pageerror', error => report.pageErrors.push(error.message));
            await page.clock.install();
            async function assertTerminal(fixture) {
                const {status, receipt} = fixture.expected, copy = labels[status];
                const body = await page.locator('body').innerText();
                if (fixture.numeric) assert.equal(await page.locator('h1').innerText(), copy.numeric);
                else {
                    assert.equal(await page.locator('#view > .pill').innerText(), copy.pill);
                    assert.equal(await page.locator('#view > .lbl').innerText(), copy.label);
                    assert.equal(await page.evaluate(() => C.status), status);
                }
                if (status !== 'expired') assert.doesNotMatch(body, /[Вв]ремя истекло|[Сс]рок оплаты заявки истёк|[Зз]аявка истекла/);
                assert.doesNotMatch(body, /Требуется подтверждение|Трейдер запросил|Проверяем ваш платёж|Разбираем вручную/);
                assert.doesNotMatch(body, /Обычно до 30 минут|Как только платёж подтвердится/);
                if (receipt) {
                    assert.match(body, /[Чч]ек|[Фф]айл/);
                    assert.match(body, /[Пп]олучен/);
                    assert.doesNotMatch(body, /создайте новую заявку/i);
                }
                if (!fixture.numeric && receipt === 'sent') {
                    assert.match(body, /Чек получен и передан платёжному партнёру\./);
                    assert.doesNotMatch(body, /пока не передан/);
                }
                if (!fixture.numeric && receipt === 'stored') {
                    assert.match(body, /Файл чека получен, но платёжному партнёру пока не передан\./);
                }
                assert.equal(await page.locator('.reqs,.cp,.qr').count(), 0);
                assert.equal(await page.getByText('Перейти к оплате', {exact: true}).count(), 0);
                assert.equal(await page.locator('a[href^="https://t.me/"]').count(), 1);
                assert.match(body, /[Нн]е (переводите|платите)|[Пп]овторно не/);
                assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false);
            }
            for (const fixture of fixtures.pages) {
                current = fixture;
                pollData = fixture.expected;
                await page.goto('https://terminal.invalid/fixture', {waitUntil: 'load'});
                if (fixture.terminal) {
                    if (fixture.numeric) {
                        await assertTerminal(fixture);
                        report.checks.push({name: fixture.name, width: viewport.width, result: 'PASS'});
                    } else {
                        for (const dead of [false, true]) for (const localExpired of [false, true]) {
                            await page.evaluate(({dead, localExpired}) => {
                                C.dead = dead; _localExpired = localExpired; render();
                            }, {dead, localExpired});
                            await assertTerminal(fixture);
                            report.checks.push({name: fixture.name, width: viewport.width,
                                staleDead: dead, localExpired, result: 'PASS'});
                        }
                        const requestsBefore = report.requests.length;
                        await page.evaluate(() => poll());
                        assert.equal(report.requests.length, requestsBefore, 'canonical terminal stops polling');
                    }
                    if (['expired-absent-none', 'failed-sent-video', 'cancelled-stored-pdf',
                         'numeric-failed-sent-video'].includes(fixture.name)) {
                        await page.screenshot({path: path.join(outputDir, `${viewport.width}-terminal-${fixture.name}.png`), fullPage: true});
                    }
                } else {
                    const body = await page.locator('body').innerText();
                    if (fixture.name === 'pending-active') assert.equal(await page.locator('.reqs').count(), 1);
                    if (fixture.name === 'pending-review') assert.match(body, /Проверяем ваш платёж/);
                    if (fixture.name === 'paid') assert.match(body, /Оплата получена/);
                    if (fixture.name === 'sent') assert.match(body, /отправлена/);
                    if (fixture.name.endsWith('pending-stored-unavailable')) {
                        assert.equal(fixture.expected.receipt, 'stored');
                        assert.equal(await page.locator('.reqs,.cp').count(), 0);
                        const receiptAcknowledged = /[Чч]ек|[Фф]айл/.test(body);
                        if (viewport.width === 320) report.pendingReceiptObservations.push({
                            surface: fixture.numeric ? 'numeric' : 'opaque', canonicalStatus: 'pending',
                            receipt: 'stored', dead: true, receiptAcknowledged,
                            visibleText: body, noPaymentInstructions: true});
                        await page.screenshot({path: path.join(outputDir,
                            `${viewport.width}-terminal-${fixture.name}.png`), fullPage: true});
                    }
                    report.checks.push({name: fixture.name + '-preserved-control', width: viewport.width, result: 'PASS'});
                }
            }
            const active = fixtures.pages.find(fixture => fixture.name === 'pending-active');
            for (const fixture of fixtures.pages.filter(f => f.terminal && !f.numeric)) {
                current = active;
                pollData = active.expected;
                await page.goto('https://terminal.invalid/fixture', {waitUntil: 'load'});
                await page.evaluate(verification => {
                    C.verification = verification; C.dead = true; _localExpired = true; render();
                }, fixture.expected.verification);
                pollData = fixture.expected;
                await page.evaluate(() => poll());
                await assertTerminal(fixture);
                assert.equal(await page.evaluate(() => C.dead), false);
                report.checks.push({name: 'poll-pending-to-' + fixture.name, width: viewport.width, result: 'PASS'});
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
