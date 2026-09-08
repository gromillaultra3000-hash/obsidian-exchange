const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const source = fs.readFileSync(input.path, 'utf8');
const start = source.indexOf('function esc(s){{');
const end = source.indexOf('render();\nsetInterval(poll, 5000);', start);
assert(start >= 0 && end > start);
const js = source.slice(start, end).replaceAll('{{', '{').replaceAll('}}', '}');
const view = {innerHTML: ''};
const context = vm.createContext({
    C: {status: input.status, receipt: input.receipt || '', verification: input.verification || '',
        dead: !!input.dead, currency: 'TON', txid: '', txUrl: '', amount: '2000',
        detailVal: 'synthetic', detailLbl: 'Телефон', expiresAt: '', bank: '', recipient: ''},
    document: {getElementById: id => id === 'view' ? view : null},
    navigator: {}, setInterval: () => 1, clearInterval: () => {}, setTimeout: () => 1,
    fetch: () => { throw new Error('unexpected network'); },
});
vm.runInContext(js, context, {timeout: 1000});
vm.runInContext(`_localExpired=${!!input.localExpired}; render();`, context, {timeout: 1000});
const before = JSON.stringify(context.C);
vm.runInContext('render();', context, {timeout: 1000});
assert.equal(JSON.stringify(context.C), before, 'render must not mutate canonical state');
process.stdout.write(JSON.stringify({html: view.innerHTML, state: context.C}));
