'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), crypto = require('node:crypto');
const {chromium} = require('playwright-core');
const [sourcePath, output] = process.argv.slice(2), source = fs.readFileSync(sourcePath, 'utf8'), fixtures = JSON.parse(source);
const hash = x => crypto.createHash('sha256').update(x).digest('hex');
const origin = 'https://website-review.invalid';
const report = {sourceSha256: hash(source), runnerSha256: hash(fs.readFileSync(__filename)), inputHashes: fixtures.inputHashes, checks: [], posts: [], unexpectedWrites: [], pageErrors: [], playwrightVersion: require('playwright-core/package.json').version};
fs.mkdirSync(output, {recursive:true});
async function main() {
  assert.notEqual(process.getuid(), 0);
  const browser = await chromium.launch({executablePath:'/opt/google/chrome/chrome', chromiumSandbox:true, headless:true});
  report.browserVersion = browser.version(); let page;
  try {
    for (const width of [320,390,1280]) for (const theme of ['legacy','v5']) for (const scenario of ['buy','sell','sell-single']) {
      const kind = scenario === 'buy' ? 'buy' : 'sell';
      const context = await browser.newContext({viewport:{width,height:844}, serviceWorkers:'block', reducedMotion:'reduce'});
      let posts = [], pendingPosts = [];
      const endpoint = '/dashboard/' + (kind === 'buy' ? 'exchange' : 'sell');
      await context.route('**/*', async route => {
        const r=route.request(), u=new URL(r.url());
        if(r.method() !== 'GET') {
          if(u.origin === origin && u.pathname === endpoint && r.method() === 'POST') {posts.push(Object.fromEntries(new URLSearchParams(r.postData()))); pendingPosts.push(route); return;}
          report.unexpectedWrites.push({url:r.url(),method:r.method()}); return route.abort();
        }
        if(u.origin !== origin) return route.abort();
        if(u.pathname === endpoint) return route.fulfill({contentType:'text/html', body:fixtures.pages[theme+'-'+scenario]});
        if(fixtures.assets[u.pathname]) return route.fulfill({contentType:u.pathname.endsWith('.css')?'text/css':'application/javascript',body:fixtures.assets[u.pathname]});
        return route.fulfill({status:404, body:''});
      });
      page=await context.newPage(); page.setDefaultTimeout(5000); page.on('pageerror',e=>report.pageErrors.push({width,theme,kind,error:e.message}));
      await page.clock.install();
      await page.goto(origin+endpoint);
      const form=page.locator('#action-order-form'), open=page.locator('#action-review-open'), dialog=page.locator('#action-review'), ack=page.locator('#action-review-ack'), confirm=page.locator('#action-review-confirm'), cancel=page.locator('#action-review-cancel');
      assert.equal(await open.isEnabled(),true);
      if(kind === 'buy') {
        await page.locator('#network').selectOption('ALT'); await page.locator('#amount').fill('12500');
        await page.locator('#address').fill('EQ'+'A'.repeat(46)); await page.locator('#dest_tag').fill('memo <>& synthetic');
        await form.locator('[name=payment_method]').selectOption('card');
      } else {
        await page.locator('#sell-amount').fill('10'); await page.locator('#payout-details').fill('79001234567');
        await page.locator('#payout-bank').selectOption('fixture-bank'); await page.locator('#payout-name').fill('Синтетический Получатель');
      }
      const expected=await form.evaluate(el=>Object.fromEntries(new FormData(el)));
      const unlabeled=await form.locator('input:not([type=hidden]),select').evaluateAll(els=>els.filter(el=>!el.labels?.length&&!el.getAttribute('aria-label')).map(el=>el.id));
      assert.deepEqual(unlabeled,[], 'Form labels are associated');
      await open.click(); await dialog.waitFor({state:'visible'});
      assert.equal(posts.length,0); assert.equal(await ack.isChecked(),false); assert.equal(await confirm.isDisabled(),true);
      const text=await dialog.innerText();
      for(const value of ['ObsidianExchange','KYC','комисс']) assert.ok(text.toLowerCase().includes(value.toLowerCase()),value);
      if(kind==='buy') for(const value of ['ALT', 'EQ'+'A'.repeat(46),'memo <>& synthetic']) assert.ok(text.includes(value),value);
      else for(const value of ['TON mainnet','79001234567','Синтетический банк','Синтетический Получатель']) assert.ok(text.includes(value),value);
      await page.keyboard.press('Tab'); assert.equal(await ack.evaluate(el=>el===document.activeElement),true,'Tab reaches acknowledgement');
      await page.keyboard.press('Shift+Tab'); assert.equal(await cancel.evaluate(el=>el===document.activeElement),true,'reverse Tab wraps disabled confirmation');
      await page.keyboard.press('Tab'); assert.equal(await ack.evaluate(el=>el===document.activeElement),true,'Tab wraps to acknowledgement');
      await page.keyboard.press('Space'); assert.equal(await confirm.isEnabled(),true);
      await page.keyboard.press('Tab'); await page.keyboard.press('Tab'); assert.equal(await confirm.evaluate(el=>el===document.activeElement),true,'Tab reaches confirmation');
      await page.keyboard.press('Tab'); assert.equal(await ack.evaluate(el=>el===document.activeElement),true,'Tab traps enabled confirmation');
      await page.screenshot({path:path.join(output,`${width}-${theme}-${scenario}-review.png`),fullPage:true});
      assert.equal(await dialog.evaluate(el=>el.scrollWidth <= el.clientWidth+1),true,'dialog horizontal fit');
      await cancel.click(); assert.equal(await dialog.isVisible(),false); assert.equal(posts.length,0);
      assert.deepEqual(await form.evaluate(el=>Object.fromEntries(new FormData(el))),expected);
      await open.focus(); await page.keyboard.press('Enter'); await dialog.waitFor({state:'visible'});
      assert.equal(await ack.isChecked(),false); await page.keyboard.press('Escape'); assert.equal(await dialog.isVisible(),false);
      assert.equal(await open.evaluate(el=>el===document.activeElement),true,'focus returned');
      await open.click(); await ack.check();
      await page.clock.fastForward(60001);
      assert.equal(await dialog.isVisible(),false,'expired review closes');
      assert.equal(posts.length,0,'expired review never posts');
      assert.ok((await page.locator('#action-review-status').innerText()).includes('истекло'));
      await open.click(); assert.equal(await ack.isChecked(),false,'expiry requires fresh acknowledgement'); await ack.check();
      const amount=kind==='buy'?'amount':'sell-amount';
      await page.evaluate(id=>{document.getElementById(id).value='9999';},amount);
      await confirm.click(); assert.equal(posts.length,0,'silent stale edit never posts');
      if(await dialog.isVisible()) await cancel.click();
      await page.locator('#'+amount).fill(kind==='buy'?'12500':'10');
      await open.click(); await ack.check();
      await confirm.evaluate(el=>{el.click();el.click();});
      await page.waitForTimeout(100);
      assert.equal(posts.length,1,'one explicit confirmation => one POST'); assert.deepEqual(posts[0],expected,'original server POST contract preserved');
      report.posts.push({width,theme,kind,scenario,body:posts[0]});
      const receiptLoaded = page.waitForNavigation({waitUntil:'domcontentloaded',timeout:5000});
      for(const route of pendingPosts) await route.fulfill({status:200,contentType:'text/html',body:'Synthetic POST receipt'});
      await receiptLoaded;
      report.checks.push({width,theme,kind,scenario,expiry:true,tabTrap:true,singlePayout:scenario === 'sell-single',result:'PASS',labels:true,ack:true,cancel:true,keyboard:true,staleEdit:true,singlePost:true,preservedPost:true});
      await context.close();
    }
    assert.deepEqual(report.unexpectedWrites,[]); assert.deepEqual(report.pageErrors,[]); report.result='PASS';
  } catch(e) {report.result='FAIL';report.error=e.stack;if(page) await page.screenshot({path:path.join(output,'failure.png'),fullPage:true}).catch(()=>{}); process.exitCode=1;}
  finally {await browser.close(); fs.writeFileSync(path.join(output,'report.json'),JSON.stringify(report,null,2)+'\n');}
}
main().catch(e=>{report.result='FAIL';report.error=e.stack;fs.writeFileSync(path.join(output,'report.json'),JSON.stringify(report,null,2));process.exitCode=1;});
