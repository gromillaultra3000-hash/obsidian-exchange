const fs = require('fs');
const vm = require('vm');
const crypto = require('crypto');
const sourcePath='/root/relay/webapp.html';
const html=fs.readFileSync(sourcePath, 'utf8');
const start=html.indexOf('        async function copyOrderId(');
const end=html.indexOf('        function renderHistoryOrders()', start);
if(start<0 || end<0) throw Error('baseline function boundaries absent');
const exact=html.slice(start, end);
async function run(mode) {
  let opens=0, writes=0, selected=0, removed=0, settled=false, rejected=false;
  const field={value:'',style:{},setAttribute(){}, select(){selected++}, remove(){removed++}};
  const button={textContent:'💬 Поддержка по заявке',disabled:false};
  const sandbox={ navigator:{clipboard:{writeText(value){writes++; if(value!=='acceptance-synthetic-42') throw Error('wrong value'); if(mode==='pending') return new Promise(()=>{}); if(mode.startsWith('reject')) return Promise.reject(Error('denied')); return Promise.resolve();}}}, window:{isSecureContext:true,setTimeout(){}}, document:{createElement(){return field}, body:{appendChild(){}},execCommand(){if(mode==='reject-throw') throw Error('copy unsupported'); return false}}, tg:{},openSupport(){opens++}};
  vm.createContext(sandbox);
  vm.runInContext(exact,sandbox);
  const p=sandbox.openOrderSupport('acceptance-synthetic-42',button);
  p.then(()=>{settled=true},()=>{settled=true;rejected=true});
  const opensSynchronous=opens;
  await new Promise(resolve=>setImmediate(resolve));
  return {mode,opensSynchronous,opensAfterMicrotasks:opens,clipboardWrites:writes,selected,removed,settled,rejected,button};
}
(async()=>{
 const results=[];
 for(const mode of ['pending','reject-throw','reject-false','success']) results.push(await run(mode));
 const report={schemaVersion:'e4-order-support-acceptance-baseline.v1',recordedAt:new Date().toISOString(),sourcePath,sourceSha256:crypto.createHash('sha256').update(html).digest('hex'),method:'Exact source declarations executed in Node VM with synthetic clipboard/DOM and navigation spy. No real navigation or data.',results,acceptance:[
 'Support is invoked synchronously from an explicit support tap, exactly once, independently of optional clipboard completion.',
 'Clipboard denial, stalled completion, legacy false/throw and absent clipboard API never prevent support access.',
 'Support destination remains fixed https://t.me/ObsidianSupBot, without order ID or personal data in a URL/payload/message.',
 'Copy feedback claims success only after a successful write; denied/unsupported copy gives an honest accessible failure and retains a retry path.',
 'No permanently disabled support button or duplicate navigation on clipboard settlement; user can retry support after returning or failed navigation.',
 'Pending/stale copy completion cannot mutate a different or replaced order UI or overwrite a newer order ID clipboard write.',
 'Keyboard Enter/Space and ordinary taps work at 320/390/1280px with default motion; order ID remains visible when copying is unavailable.',
 'No order/payment/transaction/evidence flow or real money authority is added or changed.'
 ]};
 fs.writeFileSync('/root/output/playwright/e4-order-support-20260908/acceptance/baseline.json',JSON.stringify(report,null,2)+'\n');
 console.log(JSON.stringify(report,null,2));
})();
