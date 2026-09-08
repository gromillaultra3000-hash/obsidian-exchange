'use strict';
// Adversarial clipboard model: native side effect occurs immediately before
// its promise resolves. Completion order is intentionally chosen by the test.
// This is a possible API-level ordering model, not a claim about Chrome internals.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const source = fs.readFileSync(process.argv[2] === '-' ? 0 : (process.argv[2] || '/root/relay/webapp.html'), 'utf8');
const harness = fs.readFileSync('/root/tests/e4_payment_requisites_copy_behavior.cjs', 'utf8');
const setup = harness.slice(harness.indexOf('const elements ='), harness.indexOf('async function main()'));
const f = new Function('source','vm','assert',setup + '\nreturn {ctx,start,button,feedback,flush,clipboard};')(source,vm,assert);
const pending = [], writes = [];
let clipboardContents = 'existing clipboard';
f.clipboard.writeText = value => {
    writes.push(value);
    return new Promise(resolve => pending.push(() => {clipboardContents = value; resolve();}));
};
async function main() {
    f.start('synthetic-A', 'recipient A'); f.button().fire();
    f.start('synthetic-B', 'recipient B'); f.button().fire();
    let result, successFeedbackBeforeLateOld = false;
    if (pending.length === 2) {
        pending[1](); await f.flush();
        successFeedbackBeforeLateOld = /скопированы/.test(f.feedback().textContent);
        pending[0](); await f.flush();
        assert.equal(clipboardContents, 'recipient A');
        assert.equal(successFeedbackBeforeLateOld, true);
        result = 'OUT_OF_ORDER_CLIPBOARD_RISK_REPRODUCED';
    } else {
        assert.equal(pending.length, 1, 'fresh view must defer while old native write is unresolved');
        assert.ok(!/скопированы/.test(f.feedback().textContent));
        pending[0](); await f.flush();
        assert.equal(clipboardContents, 'recipient A');
        f.button().fire(); assert.equal(pending.length, 2);
        pending[1](); await f.flush();
        assert.equal(clipboardContents, 'recipient B');
        assert.match(f.feedback().textContent, /скопированы/);
        result = 'CROSS_GENERATION_SERIALIZATION_VERIFIED';
    }
    console.log(JSON.stringify({result,sourceSha256:crypto.createHash('sha256').update(source).digest('hex'),
        runnerSha256:crypto.createHash('sha256').update(fs.readFileSync(__filename)).digest('hex'),
        clipboardContents,writes,successFeedbackBeforeLateOld,
        actualClipboardUsed:false,networkUsed:false,
        limitation:'Deferred write-on-resolve counterexample, not proof that current Chrome internally settles writes out of order.'},null,2));
}
main().catch(error=>{console.error(error.stack);process.exitCode=1;});
