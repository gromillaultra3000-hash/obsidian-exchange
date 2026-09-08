'use strict';
// Independent assertions over the acceptance agent's synthetic DOM scaffold.
// No network, real clipboard, SDK or production mutation is possible here.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const sourcePath = process.argv[2] || '/root/relay/webapp.html';
const source = fs.readFileSync(sourcePath, 'utf8');
const harnessPath = '/root/tests/e4_payment_requisites_copy_behavior.cjs';
const harness = fs.readFileSync(harnessPath, 'utf8');
const setup = harness.slice(harness.indexOf('const elements ='), harness.indexOf('async function main()'));
function fixture() {
    return new Function('source', 'vm', 'assert', setup + '\nreturn {ctx,el,start,button,feedback,finish,reply,flush,writes,pending,intervals,clipboard};')(source, vm, assert);
}
const sha = content => crypto.createHash('sha256').update(content).digest('hex');
async function main() {
    const checks = [];
    for (const mode of ['paid', 'sent', 'failed', 'cancelled', 'expired', 'receipt', 'dead', 'timer']) {
        for (const success of [true, false]) {
            const f = fixture(); f.start();
            const oldButton = f.button(), oldStatus = f.feedback();
            await f.reply(0, {status: 'pending'});
            oldButton.fire();
            if (mode === 'timer') {
                const tick = [...f.intervals.values()].find(item => item.delay === 1000).fn;
                for (let i = 0; i < 900; i++) tick();
            } else {
                f.el('pay-check-btn').onclick();
                await f.reply(1, {status: ['receipt', 'dead'].includes(mode) ? 'pending' : mode,
                    receipt: mode === 'receipt' ? 'sent' : '', dead: mode === 'dead'});
            }
            assert.equal(oldStatus.textContent, '');
            assert.equal(oldButton.disabled, true);
            await f.finish(0, success);
            assert.equal(oldStatus.textContent, '');
            oldButton.fire(); assert.equal(f.writes.length, 1);
            assert.equal(f.el('pay-req').textContent, '');
            checks.push(`terminal ${mode}: ${success ? 'fulfilled' : 'rejected'} stale write has no feedback or new invocation`);
        }
    }
    for (const oldSuccess of [true, false]) {
        const f = fixture(); f.start(); const old = f.button(); old.fire();
        f.start('synthetic-a', 'fresh literal'); f.button().fire();
        assert.equal(f.writes.length, 1);
        assert.equal(f.button().disabled, true);
        assert.match(f.feedback().textContent, /предыдущее копирование/);
        await f.finish(0, oldSuccess); old.fire();
        assert.equal(f.feedback().textContent, '');
        assert.equal(f.el('pay-req-value').textContent, 'fresh literal');
        assert.equal(f.button().disabled, false);
        f.button().fire(); await f.finish(1);
        assert.match(f.feedback().textContent, /скопированы/);
        assert.deepEqual(f.writes, ['+7 000 000-00-01', 'fresh literal']);
        checks.push(`same-ID global serialization: old ${oldSuccess ? 'success' : 'failure'} releases current button without success or automatic fresh write`);
    }
    {
        const f = fixture(); f.start(); f.button().fire();
        f.start('synthetic-b', 'B'); const bButton = f.button(), bStatus = f.feedback();
        f.start('synthetic-c', 'C'); const cButton = f.button();
        assert.equal(cButton.disabled, true); await f.finish(0);
        assert.equal(bButton.disabled, true);
        assert.match(bStatus.textContent, /предыдущее копирование/);
        assert.equal(cButton.disabled, false); assert.equal(f.feedback().textContent, '');
        bButton.fire(); assert.equal(f.writes.length, 1);
        cButton.fire(); await f.finish(1); assert.equal(f.writes[1], 'C');
        checks.push('three generations: only current waiter unlocks; no stale waiter starts a write');
    }
    {
        const f = fixture(); f.start(); f.button().fire();
        f.start('synthetic-b', 'B'); const bButton = f.button();
        await f.reply(1, {status: 'cancelled'}); await f.finish(0);
        assert.equal(bButton.disabled, true); bButton.fire();
        assert.equal(f.writes.length, 1); assert.equal(f.el('pay-req').textContent, '');
        checks.push('terminal current waiter stays revoked when older global clipboard token releases');
    }
    {
        const f = fixture(); f.start();
        f.clipboard.writeText = () => {throw {message: 'SYNTHETIC_PRIVATE_DIAGNOSTIC'};};
        await f.button().fire();
        assert.match(f.feedback().textContent, /Не удалось/);
        assert.ok(!f.feedback().textContent.includes('SYNTHETIC_PRIVATE_DIAGNOSTIC'));
        assert.equal(f.button().disabled, false);
        checks.push('synchronous provider diagnostics remain private and button unlocks');
    }
    {
        const f = fixture();
        const literal = "');window.__securitySentinel=true;// <img src=x onerror=bad()> &quot; \\n";
        f.ctx.startOrderTracking('synthetic-literal', null, 'TON', null, null,
            {phone: literal, bank_name: '<img src=x onerror=bad()>', recipient: "O'Brien & <svg onload=bad()>"});
        assert.equal(f.el('pay-req-value').textContent, literal);
        assert.equal(f.button().getAttribute('onclick'), null);
        assert.ok(!f.el('pay-req').innerHTML.includes('<img'));
        assert.ok(!f.el('pay-req').innerHTML.includes('<svg'));
        assert.ok(!f.el('pay-req').innerHTML.includes('window.__securitySentinel'));
        f.button().fire(); await f.finish(0);
        assert.deepEqual(f.writes, [literal]);
        assert.equal(f.ctx.window.__securitySentinel, undefined);
        checks.push('prior executable-handler payload copies literally; bank/recipient markup stays escaped');
    }
    const report = {schemaVersion:'e4-payment-requisites-copy-security-extra-checks.v1',
        recordedAt:new Date().toISOString(),result:'PASS', reviewer:'/root/requisites_diff_review',
        sourcePath, sourceSha256:sha(source),runnerSha256:sha(fs.readFileSync(__filename)),
        scaffoldPath:harnessPath,scaffoldSha256:sha(harness),nodeVersion:process.version,
        checks, actualClipboardUsed:false,networkUsed:false,productionMutated:false,
        limitations:['Synthetic DOM scaffold, not a native HTML parser or browser clipboard.',
            'Scaffolding supplied by acceptance agent; assertions supplied independently by reviewer.']};
    console.log(JSON.stringify(report,null,2));
}
main().catch(error => {console.error(error.stack); process.exitCode = 1;});
