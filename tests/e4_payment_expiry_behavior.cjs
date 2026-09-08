const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const source = fs.readFileSync(input.path, 'utf8');
const begin = source.indexOf('function esc(s){{');
const end = source.indexOf('render();\nsetInterval(poll, 5000);', begin);
assert(begin >= 0 && end > begin);
const js = source.slice(begin, end).replaceAll('{{', '{').replaceAll('}}', '}');
let now = Date.parse('2026-09-08T12:00:00Z'), serial = 0;
const intervals = new Map(), requests = [];
const timer = {innerHTML: '', textContent: ''}, view = {innerHTML: ''};
class Clock extends Date { static now() { return now; } }
const context = vm.createContext({Date: Clock,
    C: {status: 'pending', receipt: '', verification: '', dead: false,
        amount: '2000', currency: 'TON', detailVal: 'synthetic', detailLbl: 'Телефон',
        bank: '', recipient: '', expiresAt: input.value, orderId: 1, token: 'synthetic',
        ...input.state},
    document: {getElementById: id => id === 'view' ? view : id === 'timer' ? timer : null},
    navigator: {}, setTimeout: () => 1,
    setInterval: callback => { intervals.set(++serial, callback); return serial; },
    clearInterval: id => intervals.delete(id),
    fetch: async url => { requests.push(url); return {ok: true, json: async () => input.pollState || {status: 'pending'}}; },
});
vm.runInContext(js, context, {timeout: 1000});
async function main() {
    if (input.mode === 'parse') {
        process.stdout.write(JSON.stringify({milliseconds: vm.runInContext('paymentExpiryMs(C.expiresAt)', context)}));
        return;
    }
    vm.runInContext('render();', context, {timeout: 1000});
    if (input.repeat) vm.runInContext('render();', context, {timeout: 1000});
    if (input.advance) {
        now += input.advance;
        for (const callback of [...intervals.values()]) callback();
    }
    if (input.poll) await vm.runInContext('poll()', context, {timeout: 1000});
    process.stdout.write(JSON.stringify({html: view.innerHTML, timer: timer.textContent || timer.innerHTML,
        state: context.C, localExpired: vm.runInContext('_localExpired', context),
        intervals: intervals.size, requests}));
}
main().catch(error => {process.stderr.write(error.stack); process.exitCode = 1;});
