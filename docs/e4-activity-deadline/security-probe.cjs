'use strict';
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const sourcePath=process.argv[2]||'/root/relay/webapp.html',mode=process.argv[3]||'candidate';
const source=fs.readFileSync(sourcePath,'utf8');
const begin=source.indexOf('        let historyOrders ='),end=source.indexOf('        (function wireHistoryControls()',begin);
const eb=source.indexOf('        function esc(s)'),ee=source.indexOf('        async function loadWalletBook()',eb);
assert.ok(begin>0&&end>begin&&eb>0&&ee>eb);
const code=source.slice(eb,ee)+source.slice(begin,end),unhandled=[];
process.on('unhandledRejection',error=>unhandled.push(String(error)));
const flush=async()=>{for(let i=0;i<12;i++)await Promise.resolve();};
function deferred(){let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return{promise,resolve,reject};}
function setup(honorAbort=false){
 let now=0,timerId=0,abortCount=0;
 const timers=new Map(),requests=[],nodes=new Map(['history-list','history-summary','history-load-status','ecosystem-activity-status'].map(id=>[id,{innerHTML:'',textContent:'',style:{},attributes:{},setAttribute(k,v){this.attributes[k]=v;},querySelectorAll(){return[];}}]));
 class Controller extends AbortController {abort(){abortCount++;super.abort();}}
 const context=vm.createContext({document:{getElementById:id=>nodes.get(id),querySelectorAll:()=>[]},
  tg:{initData:'',openLink(){throw Error('navigation forbidden');}},userId:'synthetic-user',location:{origin:'https://synthetic.invalid'},
  performance:{now:()=>now},AbortController:Controller,
  setTimeout(fn,delay){assert.equal(delay,10000);timers.set(++timerId,{at:now+delay,fn});return timerId;},clearTimeout:id=>timers.delete(id),
  fetch(url,options){assert.equal(url,'/api/history?user_id=synthetic-user');assert.equal(options.method,undefined);assert.equal(options.cache,'no-store');const d=deferred();const r={...d,options,bodyCalls:0};requests.push(r);
   if(honorAbort&&options.signal)options.signal.addEventListener('abort',()=>d.reject(Error('synthetic native abort')),{once:true});return d.promise;},
 });
 vm.runInContext(code,context);
 const snapshot=()=>({html:nodes.get('history-list').innerHTML,busy:nodes.get('history-list').attributes['aria-busy'],status:nodes.get('history-load-status').textContent,overview:nodes.get('ecosystem-activity-status').textContent,summary:nodes.get('history-summary').style.display});
 const advance=async(ms,deliver=true)=>{now+=ms;if(deliver)for(const[id,timer]of[...timers])if(timer.at<=now){timers.delete(id);timer.fn();}await flush();};
 const success=(index,rows=[{order_id:'CURRENT',status:'sent',currency:'TON',amount:2000,created:'synthetic',tx_url:'https://explorer.invalid/current'}])=>requests[index].resolve({ok:true,json:async()=>{requests[index].bodyCalls++;return rows;}});
 const body=(index)=>{const d=deferred();requests[index].resolve({ok:true,json:()=>{requests[index].bodyCalls++;return d.promise;}});return d;};
 const settled=promise=>{const result={done:false};promise.then(()=>result.done=true,error=>{result.done=true;result.error=String(error);});return result;};
 return{context,requests,timers,snapshot,advance,success,body,settled,get abortCount(){return abortCount;}};
}
function errorState(env){const s=env.snapshot();assert.equal(s.busy,'false');assert.match(s.status,/Не удалось/);assert.match(s.html,/недоступна/);assert.equal(s.summary,'none');assert.doesNotMatch(s.html,/Оплатить|CURRENT|private/);}
function successState(env){const s=env.snapshot();assert.equal(s.busy,'false');assert.match(s.status,/обновлена/);assert.match(s.html,/CURRENT/);assert.match(s.html,/Транзакция/);}
async function main(){const checks=[];
 if(mode==='baseline'){
  for(const where of['fetch','body']){const env=setup();const result=env.settled(env.context.loadHistory());if(where==='body'){env.body(0);await flush();}await env.advance(30000);assert.equal(result.done,false);assert.equal(env.snapshot().busy,'true');assert.equal(env.timers.size,0);checks.push(where+'_still_loading_after_simulated_30_seconds');}
  return{result:'BASELINE_DEFECT_REPRODUCED',checks,sourceSha256:crypto.createHash('sha256').update(source).digest('hex')};
 }
 for(const honor of[false,true])for(const where of['fetch','body']){
  const env=setup(honor);const result=env.settled(env.context.loadHistory());let body;if(where==='body'){body=env.body(0);await flush();}
  assert.equal(env.timers.size,1);await env.advance(9999);assert.equal(result.done,false);assert.equal(env.snapshot().busy,'true');
  await env.advance(1);assert.equal(result.done,true,'deadline must settle outer read even when abort is ignored');assert.equal(result.error,undefined);errorState(env);assert.equal(env.requests[0].options.signal.aborted,true);assert.equal(env.timers.size,0);
  const after=env.snapshot();if(body)body.reject(Error('private late body'));else env.requests[0].reject(Error('private late fetch'));await flush();assert.deepEqual(env.snapshot(),after);
  const retry=env.context.loadEcosystemActivity();env.success(1);await retry;successState(env);assert.equal(env.timers.size,0);
  checks.push(where+'_deadline_abort_'+(honor?'honored':'ignored')+'_late_reject_and_retry');
 }
 {
  const env=setup();const result=env.settled(env.context.loadHistory());await env.advance(9000);env.body(0);await flush();await env.advance(999);assert.equal(result.done,false);await env.advance(1);assert.equal(result.done,true);errorState(env);assert.equal(env.timers.size,0);checks.push('fetch_9000ms_plus_body_1000ms_share_one_total_deadline');
 }
 for(const missing of['AbortController','performance','fetch']){
  const env=setup();delete env.context[missing];const p=env.context.loadHistory();await p;errorState(env);assert.equal(env.timers.size,0);checks.push('missing_'+missing+'_fails_closed_without_timer_retention');
 }
 for(const when of[9999,10000,10001])for(const where of['fetch','body']){
  const env=setup();const p=env.context.loadHistory();let body;if(where==='body'){body=env.body(0);await flush();}
  await env.advance(when,false);if(body)body.resolve([{order_id:'CURRENT',status:'sent',currency:'TON',amount:2000,created:'synthetic',tx_url:'https://explorer.invalid/current'}]);else env.success(0);
  await p;if(when<10000)successState(env);else errorState(env);assert.equal(env.timers.size,0);if(where==='fetch'&&when>=10000)assert.equal(env.requests[0].bodyCalls,0,'expired headers must not start JSON parsing');
  checks.push(where+'_completion_at_'+when+'_without_timer_delivery');
 }
 for(const oldKind of['fetch','body'])for(const outcome of['success','reject']){
  const env=setup();const old=env.settled(env.context.loadEcosystemActivity());let body;if(oldKind==='body'){body=env.body(0);await flush();}
  await env.advance(1000);const current=env.settled(env.context.loadHistory());await flush();assert.equal(old.done,true,'superseded read must settle');assert.equal(env.requests[0].options.signal.aborted,true);assert.equal(env.timers.size,1);
  const waiting=env.snapshot();if(body){if(outcome==='success')body.resolve([]);else body.reject(Error('private stale body'));}else if(outcome==='success')env.success(0,[]);else env.requests[0].reject(Error('private stale fetch'));
  await flush();assert.deepEqual(env.snapshot(),waiting);assert.equal(current.done,false);assert.equal(env.timers.size,1);if(oldKind==='fetch'&&outcome==='success')assert.equal(env.requests[0].bodyCalls,0,'retired headers must not start JSON parsing');
  const newest=env.context.loadEcosystemActivity();await flush();assert.equal(current.done,true);assert.equal(env.requests[1].options.signal.aborted,true,'old finally must not erase current cancellation handle');assert.equal(env.timers.size,1);
  env.success(2);await newest;successState(env);assert.equal(env.timers.size,0);await env.advance(30000);successState(env);
  checks.push('superseded_'+oldKind+'_'+outcome+'_settles_without_stale_ui_or_cancel_handle_loss');
 }
 {
  const env=setup();const outcomes=[];for(let i=0;i<100;i++){outcomes.push(env.settled(env.context.loadHistory()));await flush();assert.equal(env.timers.size,1);if(i)assert.equal(outcomes[i-1].done,true);}
  assert.equal(env.requests.filter(r=>!r.options.signal.aborted).length,1);await env.advance(10000);assert.ok(outcomes.every(r=>r.done&&!r.error));assert.equal(env.timers.size,0);assert.ok(env.requests.every(r=>r.options.signal.aborted));errorState(env);checks.push('100_ignored_abort_supersessions_retain_one_timer_one_live_signal_all_outer_reads_settle');
 }
 await new Promise(resolve=>setImmediate(resolve));assert.deepEqual(unhandled,[]);
 return{reviewer:'/root/support_security',node:process.version,result:'PASS',sourceSha256:crypto.createHash('sha256').update(source).digest('hex'),checks,unhandledRejections:unhandled,scope:'Synthetic VM timers/fetch only; no network, customer data, messages, money, service or 064A actions.'};
}
main().then(result=>process.stdout.write(JSON.stringify(result,null,2)+'\n')).catch(error=>{console.error(error);process.exitCode=1;});
