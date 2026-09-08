'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const {webkit}=require('playwright-core');
const [sourcePath,output]=process.argv.slice(2),source=fs.readFileSync(sourcePath,'utf8'),hash=x=>crypto.createHash('sha256').update(x).digest('hex');
const baseline=!source.includes('oe.wallet-attempt.shared.v1');
const origin='https://wallet-webkit.invalid',wallet='0:'+'b'.repeat(64),address='EQ'+'A'.repeat(46),key='oe.wallet-attempt.shared.v1',lockName='oe.wallet-handoff.v1';
function friendly(){const bytes=Buffer.concat([Buffer.from([0x11,0]),Buffer.from(wallet.split(':')[1],'hex')]);let crc=0;for(const byte of bytes){crc^=byte<<8;for(let i=0;i<8;i++)crc=((crc<<1)^((crc&0x8000)?0x1021:0))&65535;}return Buffer.concat([bytes,Buffer.from([crc>>8,crc&255])]).toString('base64url');}
const request={network:'-239',validUntil:2000,messages:[{address,amount:'1250000000',payload:'SYNTHETIC-NOT-A-BOC'}]};
const report={sourceSha256:hash(source),runnerSha256:hash(fs.readFileSync(__filename)),baseline,playwrightVersion:require('playwright-core/package.json').version,browserEngine:'Linux Playwright WebKit (not iOS/Safari)',capabilities:[],checks:[],unexpectedWrites:[],pageErrors:[]};
fs.mkdirSync(output,{recursive:true});
async function main(){
 assert.notEqual(process.getuid(),0);const browser=await webkit.launch({headless:true});report.browserVersion=browser.version();let page;
 try{for(const width of [320,390]){
  async function fixture(modes=['pending','pending']){
   const context=await browser.newContext({viewport:{width,height:844},serviceWorkers:'block'});const counts={prepare:0,notify:0};
   await context.addInitScript(()=>{window.Telegram={WebApp:{initData:'',initDataUnsafe:{},expand(){},ready(){},onEvent(){},setHeaderColor(){},setBackgroundColor(){},setBottomBarColor(){}}};});
   await context.route('**/*',async route=>{const r=route.request(),u=new URL(r.url());if(u.origin!==origin)return route.abort();if(r.method()==='GET'&&u.pathname==='/webapp')return route.fulfill({contentType:'text/html',body:source});
    if(r.method()==='POST'&&['/api/wallet/transfer-request','/api/wallet/send-request'].includes(u.pathname)){counts.prepare++;return route.fulfill({contentType:'application/json',body:JSON.stringify({ok:true,sell_id:42,from_address:friendly(),address,amount:1.25,marker:'synthetic',request})});}
    if(r.method()==='POST'&&u.pathname==='/api/wallet/send-signed'){counts.notify++;return route.fulfill({contentType:'application/json',body:'{"ok":true}'});}
    if(r.method()!=='GET'){report.unexpectedWrites.push(u.pathname);return route.abort();}
    const fixtures={'/api/history':[],'/api/wallet/links':{wallets:[{chain:'TON',address,balance:null}]},'/api/wallet/dues':{dues:[{sell_id:42,amount:1.25,currency:'TON',marker:'synthetic'}]}};
    return route.fulfill({contentType:'application/json',body:JSON.stringify(fixtures[u.pathname]||{})});});
   const pages=[];for(const mode of modes){page=await context.newPage();page.setDefaultTimeout(8000);page.on('pageerror',e=>report.pageErrors.push(e.message));await page.goto(origin+'/webapp',{waitUntil:'load'});await setup(page,mode);pages.push(page);}return {context,pages,counts};
  }
  async function setup(p,mode='pending'){await p.evaluate(({wallet,address,mode})=>{window.__signing=[];tcUI={account:{address:wallet,chain:'-239'},sendTransaction(r){window.__signing.push(structuredClone(r));if(mode==='success')return Promise.resolve({});if(mode==='reject')return Promise.reject(new Error('unknown'));return new Promise((resolve,reject)=>{window.__settle=()=>resolve({});window.__reject=()=>reject(new Error('unknown'));});}};document.getElementById('w-to').value=address;document.getElementById('w-amount').value='1.25';document.getElementById('w-comment').value='NEVER-RETAIN';walletRender([{chain:'TON',address,balance:null}]);walletDuesRender([{sell_id:42,amount:1.25,currency:'TON',marker:'synthetic'}]);},{wallet,address,mode});await p.locator('#tab-wallet').click();await p.locator('#w-act-send').click();}
  async function open(p,kind='transfer'){await p.locator(kind==='transfer'?'#w-send-go':'.wallet-pay').click();await p.locator('#exchange-review').waitFor({state:'visible'});assert.equal(await p.locator('#exchange-review-ack').isChecked(),false);assert.equal(await p.locator('#exchange-review-confirm').isDisabled(),true);assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);await p.locator('#exchange-review-ack').check();}
  const count=p=>p.evaluate(()=>window.__signing.length),record=p=>p.evaluate(k=>localStorage.getItem(k),key);
  async function blocked(p,kind='transfer'){await p.locator(kind==='transfer'?'#w-send-go':'.wallet-pay').click();assert.equal(await count(p),0);assert.equal(await p.locator('#exchange-review').isVisible(),false);}
  function pass(name){report.checks.push({width,case:name,result:'PASS'});}
  {
   const f=await fixture(),[a,b]=f.pages;await open(a);await open(b,'payment');await a.screenshot({path:path.join(output,`${width}-transfer-review.png`)});await b.screenshot({path:path.join(output,`${width}-payment-review.png`)});
   // Actual native competing confirmations, no Web Locks or localStorage stubs.
   await Promise.all([a.locator('#exchange-review-confirm').click(),b.locator('#exchange-review-confirm').click()]);
   await a.waitForFunction(()=>window.__signing.length===1||!!localStorage.getItem('oe.wallet-attempt.shared.v1'));
   const ca=await count(a),cb=await count(b);assert.equal(ca+cb,baseline?2:1);
   if(baseline){pass('baseline two independent real tabs both entered inert SDK');await f.context.close();continue;}
   report.capabilities.push(await a.evaluate(()=>({secureContext:isSecureContext,locks:typeof navigator.locks?.request,randomUUID:typeof crypto.randomUUID,userAgent:navigator.userAgent})));
   const winner=ca?a:b,loser=ca?b:a;assert.equal((await winner.evaluate(()=>navigator.locks.query())).held.filter(l=>l.name==='oe.wallet-handoff.v1').length,1);
   const stored=JSON.parse(await record(loser));assert.deepEqual(Object.keys(stored).sort(),['attemptId','network','operation','orderId','version','wallet']);assert.equal(stored.version,2);assert.equal(stored.wallet,wallet);assert.match(stored.attemptId,/^[0-9a-f-]{36}$/);
   await loser.locator('#wallet-attempt-notice').waitFor({state:'visible'});await loser.locator('#wallet-attempt-ack').check();await loser.locator('#wallet-attempt-remove').click();assert.equal(await record(loser),JSON.stringify(stored));assert.equal(await count(loser),0);
   await loser.locator('#wallet-attempt-notice').scrollIntoViewIfNeeded();assert.equal(await loser.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);await loser.screenshot({path:path.join(output,`${width}-other-tab-pending.png`)});
   await winner.close();await loser.waitForFunction(async()=>!(await navigator.locks.query()).held.some(l=>l.name==='oe.wallet-handoff.v1'));
   await blocked(loser);await loser.evaluate(()=>{tcUI.account={address:'0:'+'c'.repeat(64),chain:'-3'};});await blocked(loser,'payment');
   await loser.locator('#wallet-attempt-ack').check();await loser.locator('#wallet-attempt-remove').click();await loser.waitForFunction(()=>localStorage.getItem('oe.wallet-attempt.shared.v1')===null);assert.equal(await count(loser),0);
   await loser.evaluate(w=>{tcUI.account={address:w,chain:'-239'};},wallet);await open(loser);assert.equal(await count(loser),0);await loser.locator('#exchange-review-cancel').click();
   assert.equal(f.counts.notify,0);pass('native simultaneous review exclusion; lock-held clear denied; holder close preserves record; account switch blocked; explicit clear never signs');await f.context.close();
  }
  {
   const f=await fixture(),[a,b]=f.pages;await b.evaluate(()=>{navigator.locks.request('oe.wallet-handoff.v1',async()=>{window.__nativeHeld=true;await new Promise(resolve=>window.__releaseNative=resolve);});});await b.waitForFunction(()=>window.__nativeHeld===true);await open(a);await a.locator('#exchange-review-confirm').click();await a.waitForFunction(()=>walletHandoffPending===false);assert.equal(await count(a),0);assert.equal(await record(a),null);await b.evaluate(()=>window.__releaseNative());await a.waitForFunction(async()=>!(await navigator.locks.query()).held.length);assert.equal(await count(a),0);assert.equal(await record(a),null);assert.equal((await a.evaluate(()=>navigator.locks.query())).pending.length,0);pass('native lock unavailable with no record fails without queue or automatic retry on release');await f.context.close();
  }
  for(const mode of ['success','reject']){const f=await fixture([mode,'pending']),[a,b]=f.pages;await open(a,'payment');await a.locator('#exchange-review-confirm').click();await a.waitForFunction(()=>window.__signing.length===1&&walletHandoffPending===false);assert.ok(await record(b));await blocked(b);assert.equal(f.counts.notify,mode==='success'?1:0);pass(mode+' retains shared unresolved outcome across tabs');await f.context.close();}
  for(const fault of ['unsupported','request-reject','storage-read','storage-write','corrupt']){const f=await fixture(['pending']),[a]=f.pages;
   await a.evaluate(({fault,key})=>{if(fault==='unsupported')Object.defineProperty(navigator,'locks',{value:undefined,configurable:true});if(fault==='request-reject')navigator.locks.request=()=>Promise.reject(new Error('lock denied'));if(fault==='storage-read'){Storage.prototype.getItem=function(){throw new Error('read denied');};}if(fault==='storage-write'){Storage.prototype.setItem=function(){throw new Error('write denied');};}if(fault==='corrupt')localStorage.setItem(key,'broken');},{fault,key});
   await a.locator('#w-send-go').click();if(await a.locator('#exchange-review').isVisible()){await a.locator('#exchange-review-ack').check();await a.locator('#exchange-review-confirm').click();}await a.evaluate(()=>new Promise(resolve=>setTimeout(resolve,50)));assert.equal(await count(a),0);pass(fault+' prevents SDK handoff');await f.context.close();
  }
  {
   const f=await fixture(['reject','reject']),[a,b]=f.pages;await open(b);await b.locator('#exchange-review-confirm').click();await b.waitForFunction(()=>window.__signing.length===1&&walletHandoffPending===false);await a.locator('#wallet-attempt-notice').waitFor({state:'visible'});await a.locator('#wallet-attempt-ack').check();const first=JSON.parse(await record(a));
   await b.locator('#wallet-attempt-ack').check();await b.locator('#wallet-attempt-remove').click();await b.waitForFunction(()=>localStorage.getItem('oe.wallet-attempt.shared.v1')===null);await open(b);await b.locator('#exchange-review-confirm').click();await b.waitForFunction(()=>window.__signing.length===2&&walletHandoffPending===false);const second=JSON.parse(await record(a));assert.notEqual(first.attemptId,second.attemptId);assert.equal(first.wallet,second.wallet);await a.waitForFunction(()=>!document.getElementById('wallet-attempt-ack').checked);assert.equal(await a.locator('#wallet-attempt-remove').isDisabled(),true);assert.equal(await count(a),0);assert.equal(await record(a),JSON.stringify(second));pass('real same-fields replacement resets stale reconciliation acknowledgement with unique attempt ID');await f.context.close();
  }
  {
   const f=await fixture(),[a,b]=f.pages;await a.evaluate(({wallet})=>sessionStorage.setItem('oe.wallet-attempt.v1',JSON.stringify({version:1,wallet,network:'-239',operation:'transfer',orderId:null})),{wallet});await a.reload({waitUntil:'load'});await setup(a);await a.waitForFunction(()=>!!localStorage.getItem('oe.wallet-attempt.shared.v1'));assert.ok(await a.evaluate(()=>sessionStorage.getItem('oe.wallet-attempt.v1')));await blocked(b);pass('legacy session evidence migrated without deletion and blocks second tab');await f.context.close();
  }
  // Delay the callback while retaining native acquisition; fault injection only in these cases.
  for(const stale of ['identity','review']){const f=await fixture(['pending']),[a]=f.pages;await open(a);await a.evaluate(()=>{const native=navigator.locks.request.bind(navigator.locks);navigator.locks.request=(name,options,callback)=>native(name,options,async lock=>{window.__lockCaptured=true;await new Promise(resolve=>window.__releaseCallback=resolve);return callback(lock);});});await a.locator('#exchange-review-confirm').click();await a.waitForFunction(()=>window.__lockCaptured===true);await a.evaluate(stale=>{if(stale==='identity')tcUI.account.chain='-3';else closeExchangeReview();window.__releaseCallback();},stale);await a.evaluate(()=>new Promise(resolve=>setTimeout(resolve,50)));assert.equal(await count(a),0);pass('delayed acquired callback '+stale+' change prevents handoff');await f.context.close();}
 }
 assert.deepEqual(report.pageErrors,[]);assert.deepEqual(report.unexpectedWrites,[]);report.result='PASS';
 }catch(e){report.result='FAIL';report.error=e.stack;process.exitCode=1;if(page&&!page.isClosed())report.failureDiagnostics=await page.evaluate(async()=>{const el=document.getElementById('tab-wallet'),rect=()=>{const r=el.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height};};let frames=0;requestAnimationFrame(()=>frames++);const before=rect();await new Promise(r=>setTimeout(r,1100));return {visibility:document.visibilityState,frames,before,after:rect(),computed:{display:getComputedStyle(el).display,visibility:getComputedStyle(el).visibility},raf:typeof requestAnimationFrame};}).catch(e=>({error:e.message}));if(page&&!page.isClosed())await page.screenshot({path:path.join(output,'failure.png')}).catch(()=>{});}
 finally{await browser.close();fs.writeFileSync(path.join(output,'report.json'),JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify({result:report.result,cases:report.checks.length,error:report.error}));}
}
main().catch(e=>{console.error(e);process.exitCode=1;});
