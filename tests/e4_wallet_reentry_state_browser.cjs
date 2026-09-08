'use strict';
// Exact public template, native browser storage/reload and DOM controls; inert SDK/API.
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), crypto = require('node:crypto');
const {chromium} = require('playwright-core');
const [sourcePath, output] = process.argv.slice(2), source = fs.readFileSync(sourcePath, 'utf8');
const hash = x => crypto.createHash('sha256').update(x).digest('hex');
const origin = 'https://wallet-state.invalid', address = 'EQ' + 'A'.repeat(46), wallet = '0:' + 'b'.repeat(64);
function friendly(raw) {
 const body=Buffer.concat([Buffer.from([0x11,0]),Buffer.from(raw.split(':')[1],'hex')]);let crc=0;
 for(const byte of body){crc^=byte<<8;for(let i=0;i<8;i++)crc=((crc<<1)^((crc&0x8000)?0x1021:0))&0xffff;}
 return Buffer.concat([body,Buffer.from([crc>>8,crc&255])]).toString('base64url');
}
const sender=friendly(wallet), key = 'oe.wallet-attempt.v1';
const request = {validUntil: 2000, network: '-239', messages: [{address, amount: '1250000000', payload: 'synthetic-not-a-boc'}]};
const report = {sourceSha256: hash(source), runnerSha256: hash(fs.readFileSync(__filename)),
 playwrightVersion: require('playwright-core/package.json').version, checks: [], unexpectedWrites: [], pageErrors: []};
fs.mkdirSync(output, {recursive: true});
async function main() {
 assert.notEqual(process.getuid(), 0);
 const browser = await chromium.launch({executablePath:'/opt/google/chrome/chrome',chromiumSandbox:true,headless:true});
 report.browserVersion = browser.version(); let page;
 try {
  for (const width of [320,390]) {
   const context = await browser.newContext({viewport:{width,height:844},serviceWorkers:'block'});
   let preparations=[], notifications=[], responseNetwork='-239', responseWallet=sender, responseOrder=42;
   await context.addInitScript(() => {window.Telegram={WebApp:{initData:'',initDataUnsafe:{},expand(){},ready(){},onEvent(){},setHeaderColor(){},setBackgroundColor(){},setBottomBarColor(){}}};});
   await context.route('**/*', async route => {
    const r=route.request(),u=new URL(r.url());
    if(u.origin!==origin)return route.abort();
    if(r.method()==='GET'&&u.pathname==='/webapp')return route.fulfill({contentType:'text/html',body:source});
    if(r.method()==='POST'&&['/api/wallet/transfer-request','/api/wallet/send-request'].includes(u.pathname)) {
     preparations.push(u.pathname); return route.fulfill({contentType:'application/json',body:JSON.stringify({ok:true,sell_id:responseOrder,from_address:responseWallet,address,amount:1.25,marker:'synthetic',request:{...request,network:responseNetwork}})});
    }
    if(r.method()==='POST'&&u.pathname==='/api/wallet/send-signed'){notifications.push(r.postDataJSON());return route.fulfill({contentType:'application/json',body:'{"ok":true}'});}
    if(r.method()!=='GET'){report.unexpectedWrites.push(u.pathname);return route.abort();}
    const fixtures={'/api/history':[], '/api/wallet/links':{wallets:[{chain:'TON',address,balance:null}]},'/api/wallet/dues':{dues:[{sell_id:42,amount:1.25,currency:'TON',marker:'synthetic'}]},'/api/rates':{BTC:5000000,offerings:[{code:'BTC',networks:[{code:'MAINNET'}]}]}};
    return route.fulfill({contentType:'application/json',body:JSON.stringify(fixtures[u.pathname]||{})});
   });
   page=await context.newPage();page.setDefaultTimeout(5000);page.on('pageerror',e=>report.pageErrors.push(e.message));
   async function setup(mode='pending') {
    await page.evaluate(({address,wallet,mode})=>{
     window.__signing=[];tcUI={account:{address:wallet,chain:'-239'},sendTransaction(r){window.__signing.push(structuredClone(r)); if(mode==='reject')return Promise.reject(new Error('ambiguous'));if(mode==='success')return Promise.resolve({});return new Promise(()=>{});}};
     document.getElementById('w-to').value=address;document.getElementById('w-amount').value='1.25';document.getElementById('w-comment').value='DO-NOT-RETAIN';
     walletRender([{chain:'TON',address,balance:null}]);walletDuesRender([{sell_id:42,amount:1.25,currency:'TON',marker:'synthetic'}]);
    },{address,wallet,mode});
    await page.locator('#tab-wallet').click();await page.locator('#w-act-send').click();
   }
   async function fresh(mode='pending') {
    await page.goto(origin+'/webapp',{waitUntil:'load'});await page.evaluate(()=>sessionStorage.clear());await page.reload({waitUntil:'load'});await setup(mode);preparations=[];notifications=[];responseWallet=sender;responseNetwork='-239';responseOrder=42;
   }
   async function action(kind){await page.locator(kind==='transfer'?'#w-send-go':'.wallet-pay').click();}
   async function confirm(kind){await action(kind);await page.locator('#exchange-review').waitFor({state:'visible'});assert.equal(await page.locator('#exchange-review-ack').isChecked(),false);assert.equal(await page.locator('#exchange-review-confirm').isDisabled(),true);await page.locator('#exchange-review-ack').check();await page.locator('#exchange-review-confirm').click();}
   async function calls(n){assert.equal(await page.evaluate(()=>window.__signing.length),n);}
   async function blocked(kind,n=0){const before=preparations.length;await action(kind);await calls(n);assert.equal(preparations.length,before);assert.equal(await page.locator('#exchange-review').isVisible(),false);await page.locator('#wallet-attempt-notice').waitFor({state:'visible'});}
   async function remove(){const b=page.locator('#wallet-attempt-remove');assert.equal(await b.isDisabled(),true);await page.locator('#wallet-attempt-ack').check();await b.click();assert.equal(await page.evaluate(k=>sessionStorage.getItem(k),key),null);await calls(0);}
   for(const kind of ['transfer','payment']) {
    await fresh();await confirm(kind);await calls(1);
    const record=await page.evaluate(k=>JSON.parse(sessionStorage.getItem(k)),key);
    assert.deepEqual(record,{version:1,wallet,network:'-239',operation:kind,orderId:kind==='payment'?42:null});
    assert.equal(await page.locator('#wallet-attempt-remove').isDisabled(),true);
    await page.reload({waitUntil:'load'});await setup();await page.clock.install();await page.clock.setSystemTime(new Date('2036-01-01'));await blocked(kind);await blocked(kind==='transfer'?'payment':'transfer');
    await page.locator('#wallet-attempt-notice').scrollIntoViewIfNeeded();assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
    await page.screenshot({path:path.join(output,`${width}-${kind}-reload-blocked.png`)});
    await page.evaluate(()=>{tcUI.account={address:'0:'+ 'c'.repeat(64),chain:'-3'};});await blocked(kind);
    await page.evaluate(({wallet})=>{tcUI.account={address:wallet,chain:'-239'};},{wallet});
    await remove();await confirm(kind);await calls(1);assert.equal(notifications.length,0);
    report.checks.push({width,case:kind+' reload cross-action/account block, minimal retention, explicit clear then fresh review',result:'PASS'});
   }
   for(const kind of ['transfer','payment'])for(const mode of ['reject','success']) {
    await fresh(mode);await confirm(kind);await page.waitForFunction(()=>walletHandoffPending===false);await blocked(kind,1);
    assert.ok(await page.evaluate(k=>sessionStorage.getItem(k),key));assert.equal(notifications.length,mode==='success'&&kind==='payment'?1:0);
    report.checks.push({width,case:kind+' '+mode+' retains unresolved state',result:'PASS'});
   }
   await fresh();await page.evaluate(k=>sessionStorage.setItem(k,'{"broken":true}'),key);await page.reload({waitUntil:'load'});await setup();await blocked('transfer');await remove();
   report.checks.push({width,case:'corrupt storage blocks and explicit recovery clears',result:'PASS'});
   for(const fault of ['getItem','setItem']) {
    await fresh();await page.evaluate(f=>{const original=Storage.prototype[f];window.__restoreStorage=()=>Storage.prototype[f]=original;Storage.prototype[f]=()=>{throw new Error('storage denied');};},fault);
    if(fault==='getItem')await action('transfer');else await confirm('transfer');await calls(0);
    await page.evaluate(()=>window.__restoreStorage());
    report.checks.push({width,case:fault+' failure prevents signing',result:'PASS'});
   }
   await fresh('reject');await confirm('transfer');await page.waitForFunction(()=>walletHandoffPending===false);
   await page.evaluate(()=>{const original=Storage.prototype.removeItem;window.__restoreStorage=()=>Storage.prototype.removeItem=original;Storage.prototype.removeItem=()=>{throw new Error('remove denied');};});
   await page.locator('#wallet-attempt-ack').check();await page.locator('#wallet-attempt-remove').click();await calls(1);assert.ok(await page.evaluate(k=>sessionStorage.getItem(k),key));await blocked('payment',1);await page.evaluate(()=>window.__restoreStorage());
   report.checks.push({width,case:'remove failure preserves block',result:'PASS'});
   for(const mismatch of ['wallet','network']) {
    await fresh();if(mismatch==='wallet')responseWallet='0:'+'c'.repeat(64);else responseNetwork='-3';await action('transfer');await calls(0);assert.equal(await page.locator('#exchange-review').isVisible(),false);
    report.checks.push({width,case:'response '+mismatch+' binding rejects mismatch',result:'PASS'});
   }
   await fresh();responseOrder=43;await action('payment');await calls(0);assert.equal(await page.locator('#exchange-review').isVisible(),false);
   report.checks.push({width,case:'payment response order mismatch rejected',result:'PASS'});
   await fresh();await action('transfer');await page.locator('#exchange-review').waitFor({state:'visible'});await page.evaluate(()=>{tcUI.account.chain='-3';});await page.locator('#exchange-review-ack').check();await page.locator('#exchange-review-confirm').click();await calls(0);
   report.checks.push({width,case:'account changes after review prevent signing',result:'PASS'});
   await context.close();
  }
  assert.deepEqual(report.pageErrors,[]);assert.deepEqual(report.unexpectedWrites,[]);report.result='PASS';
 } catch(e) {report.result='FAIL';report.error=e.stack;process.exitCode=1;if(page&&!page.isClosed())await page.screenshot({path:path.join(output,'failure.png')}).catch(()=>{});}
 finally {await browser.close();fs.writeFileSync(path.join(output,'report.json'),JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify({result:report.result,cases:report.checks.length,error:report.error}));}
}
main().catch(e=>{console.error(e);process.exitCode=1;});
