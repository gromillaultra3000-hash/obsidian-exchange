'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const {chromium}=require('playwright-core');
const [input,output]=process.argv.slice(2),source=fs.readFileSync(input),fixtures=JSON.parse(source);
const sha=x=>crypto.createHash('sha256').update(x).digest('hex');
const report={sourceSha256:sha(source),runnerSha256:sha(fs.readFileSync(__filename)),inputHashes:fixtures.inputHashes,checks:[],pageErrors:[]};
(async()=>{
 const browser=await chromium.launch({executablePath:'/opt/google/chrome/chrome',chromiumSandbox:true,headless:true});
 try {
  for(const width of [320,390,1280]) for(const theme of ['legacy','v5']) {
   const context=await browser.newContext({viewport:{width,height:844},serviceWorkers:'block',reducedMotion:'reduce'}),posts=[];
   await context.route('**/*',async route=>{
    const r=route.request(),u=new URL(r.url());
    if(u.origin!=='https://swap-review.invalid') return route.abort();
    if(r.method()==='POST') {
     const body=Object.fromEntries(new URLSearchParams(r.postData()));posts.push({path:u.pathname,body});
     return route.fulfill({contentType:'text/html',body:u.pathname==='/dashboard/swap/quote'?fixtures.pages[theme+'-review']:'Synthetic receipt'});
    }
    if(u.pathname==='/dashboard/swap') return route.fulfill({contentType:'text/html',body:fixtures.pages[theme+'-form']});
    if(fixtures.assets[u.pathname]) return route.fulfill({contentType:u.pathname.endsWith('.css')?'text/css':'application/javascript',body:fixtures.assets[u.pathname]});
    return route.fulfill({status:404,body:''});
   });
   const page=await context.newPage();page.setDefaultTimeout(5000);page.on('pageerror',e=>report.pageErrors.push(e.message));
   await page.goto('https://swap-review.invalid/dashboard/swap');
   assert.deepEqual(await page.locator('form input:not([type=hidden]),form select').evaluateAll(els=>els.filter(e=>!e.labels?.length).map(e=>e.name)),[]);
   await Promise.all([page.waitForNavigation({waitUntil:'domcontentloaded'}),page.getByRole('button',{name:'Рассчитать и проверить условия'}).click()]);
   assert.equal(posts.length,1);assert.equal(posts[0].path,'/dashboard/swap/quote');
   const text=await page.locator('.dash-card').innerText();
   for(const value of ['SwapUZ','BTC','LTC','synthetic-address','KYC','Плавающий','необратимого']) assert.ok(text.includes(value),value);
   assert.equal(await page.locator('input[name=review_ack]').isChecked(),false);
   await page.getByRole('button',{name:'Создать своп',exact:true}).click();
   assert.equal(posts.length,1,'unchecked browser form cannot submit');
   assert.equal(await page.locator('input[name=review_ack]').evaluate(e=>e===document.activeElement),true);
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true);
   await page.screenshot({path:path.join(output,`${width}-${theme}-swap-review.png`),fullPage:true});
   await page.locator('input[name=review_ack]').check();
   await Promise.all([page.waitForNavigation({waitUntil:'domcontentloaded'}),page.getByRole('button',{name:'Создать своп',exact:true}).click()]);
   assert.equal(posts.length,2);assert.equal(posts[1].path,'/dashboard/swap/confirm');assert.equal(posts[1].body.review_ack,'1');assert.equal(posts[1].body.review_action,'confirm');
   assert.equal(posts[1].body.address,'synthetic-address');assert.equal(posts[1].body.review_token,'synthetic-review');
   // Cancellation uses the safe new endpoint and requires no acknowledgement.
   await page.goto('https://swap-review.invalid/dashboard/swap');
   await Promise.all([page.waitForNavigation({waitUntil:'domcontentloaded'}),page.getByRole('button',{name:'Рассчитать и проверить условия'}).click()]);
   await Promise.all([page.waitForNavigation({waitUntil:'domcontentloaded'}),page.getByRole('button',{name:'Изменить данные'}).click()]);
   assert.equal(posts.at(-1).path,'/dashboard/swap/confirm');assert.equal(posts.at(-1).body.review_action,'edit');assert.equal(posts.at(-1).body.review_ack,undefined);
   report.checks.push({width,theme,result:'PASS',quoteBeforeConfirm:true,ack:true,cancel:true,labels:true,recipient:true});await context.close();
  }
  assert.deepEqual(report.pageErrors,[]);report.result='PASS';
 }catch(e){report.result='FAIL';report.error=e.stack;process.exitCode=1;}
 finally{await browser.close();fs.writeFileSync(path.join(output,'report.json'),JSON.stringify(report,null,2));}
})();
