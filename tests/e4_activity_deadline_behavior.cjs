'use strict';
// Shipped functions; native AbortController with an abort-ignoring synthetic read
// and controlled monotonic timer queue exposes stale and delayed-timer outcomes.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const [sourcePath, scenario] = process.argv.slice(2);
const source = fs.readFileSync(sourcePath, 'utf8');
const elements = new Map(['history-list','history-summary','history-load-status','ecosystem-activity-status']
    .map(id => [id, {innerHTML:'',textContent:'',style:{},attributes:{},querySelectorAll:()=>[],
        setAttribute(k,v) {this.attributes[k]=v;}}]));
const requests=[], timers=new Map(), unhandled=[];
let now=0, nextTimer=0;
process.on('unhandledRejection', error => unhandled.push(error.message));
const ctx=vm.createContext({document:{getElementById:id=>elements.get(id),querySelectorAll:()=>[]},
    tg:{initData:''},userId:'synthetic-user',location:{origin:'https://deadline.invalid'},AbortController,
    performance:{now:()=>now},setTimeout:(callback,ms)=>{const id=++nextTimer;timers.set(id,{callback,at:now+ms});return id;},
    clearTimeout:id=>timers.delete(id),
    fetch:(url,options)=>new Promise((resolve,reject)=>requests.push({url,options,resolve,reject}))});
const begin=source.indexOf('        let historyOrders =');
const end=source.indexOf('        (function wireHistoryControls()',begin);
const eb=source.indexOf('        function esc(s) {'), ee=source.indexOf('        async function loadWalletBook()',eb);
assert.ok([begin,end,eb,ee].every(n=>n>=0));
vm.runInContext(source.slice(eb,ee)+source.slice(begin,end),ctx);
const sent={order_id:'synthetic-deadline',currency:'TON',amount:2000,status:'sent',created:'2026-09-08',tx_url:'https://explorer.invalid/synthetic'};
const stale={...sent,status:'pending',session_token:'synthetic-session'};
const flush=async()=>{for(let n=0;n<16;n++)await Promise.resolve();};
const snap=()=>({orders:JSON.parse(vm.runInContext('JSON.stringify(historyOrders)',ctx)),
    nodes:[...elements].map(([id,e])=>({id,html:e.innerHTML,text:e.textContent,style:{...e.style},attributes:{...e.attributes}}))});
const signal=n=>requests[n].options.signal;
const reply=(n,rows=[sent])=>requests[n].resolve({ok:true,json:async()=>rows});
async function body(n) {let resolve,reject;requests[n].resolve({ok:true,json:()=>new Promise((a,b)=>{resolve=a;reject=b;})});await flush();return {resolve,reject};}
async function advance(ms,fire=true) {now+=ms;if(fire)for(const[id,t]of [...timers])if(t.at<=now){timers.delete(id);t.callback();}await flush();}
function loading(){assert.equal(vm.runInContext('historyLoadState',ctx),'loading');assert.equal(elements.get('history-list').attributes['aria-busy'],'true');assert.ok(!elements.get('history-list').innerHTML.includes('Оплатить'));}
function failed(){assert.equal(vm.runInContext('historyLoadState',ctx),'error');assert.equal(elements.get('history-list').attributes['aria-busy'],'false');assert.match(elements.get('history-list').innerHTML,/История сейчас недоступна/);assert.match(elements.get('ecosystem-activity-status').textContent,/недоступны/);}
function ready(){assert.equal(vm.runInContext('historyLoadState',ctx),'ready');assert.equal(elements.get('history-list').attributes['aria-busy'],'false');assert.match(elements.get('history-list').innerHTML,/Транзакция/);}
function clean(){assert.equal(timers.size,0);assert.equal(vm.runInContext('historyReadCancel',ctx),null);}
async function main(){
    if(['fetch_stall','body_stall','body_budget'].includes(scenario)){
        let settled=false;const p=ctx.loadHistory().then(()=>{settled=true;});
        assert.equal(timers.size,1);assert.equal([...timers.values()][0].at,10000);assert.equal(signal(0).aborted,false);
        if(scenario==='body_budget')await advance(9000);
        if(scenario!=='fetch_stall')await body(0);
        await advance(scenario==='body_budget'?999:9999);loading();assert.equal(settled,false);
        await advance(1);assert.equal(settled,true,'deadline must settle even when read ignores abort');await p;failed();assert.equal(signal(0).aborted,true);clean();
        const count=requests.length;ctx.setHistoryFilter('sent');failed();assert.equal(requests.length,count);
    }else if(scenario.startsWith('late_')){
        const p=ctx.loadHistory();let b;if(scenario.includes('body'))b=await body(0);
        await advance(10000);await p;failed();const before=snap();
        if(scenario==='late_fetch_success')reply(0,[stale]);
        if(scenario==='late_fetch_failure')requests[0].reject(Error('late private fetch'));
        if(scenario==='late_body_success')b.resolve([stale]);
        if(scenario==='late_body_failure')b.reject(Error('late private body'));
        await flush();assert.deepEqual(snap(),before);clean();
    }else if(['retry_success','retry_failure','overview_retry'].includes(scenario)){
        const p=ctx.loadHistory();await advance(10000);await p;failed();
        const q=scenario==='overview_retry'?ctx.loadEcosystemActivity():ctx.loadHistory();loading();
        assert.equal(signal(1).aborted,false);assert.equal(timers.size,1);
        if(scenario==='retry_failure')requests[1].reject(Error('retry failed'));else reply(1);
        await q;if(scenario==='retry_failure')failed();else ready();clean();
        const before=snap();reply(0,[stale]);await flush();assert.deepEqual(snap(),before);
    }else if(['supersede_fetch','supersede_body','old_timer','old_finally'].includes(scenario)){
        let settled=false;const p=ctx.loadHistory().then(()=>{settled=true;});
        let b;if(scenario==='supersede_body')b=await body(0);
        const oldTimer=[...timers.values()][0].callback;
        await advance(2500);const q=ctx.loadEcosystemActivity();
        assert.equal(signal(0).aborted,true);assert.equal(signal(1).aborted,false);
        await flush();assert.equal(settled,true);loading();assert.equal(timers.size,1);
        assert.equal([...timers.values()][0].at,12500);
        if(scenario==='old_timer'){oldTimer();await flush();loading();assert.equal(signal(1).aborted,false);assert.equal(timers.size,1);}
        if(scenario==='old_finally'){assert.equal(typeof vm.runInContext('historyReadCancel',ctx),'function');await advance(10000);await q;failed();assert.equal(signal(1).aborted,true);}
        else {reply(1);await q;ready();}
        clean();const before=snap();if(b)b.reject(Error('obsolete body'));else reply(0,[stale]);await p;await flush();assert.deepEqual(snap(),before);
    }else if(['success_before','success_at','success_after','body_after','cleared_success_timer'].includes(scenario)){
        const p=ctx.loadHistory();const saved=[...timers.values()][0].callback;
        let b;if(scenario==='body_after')b=await body(0);
        await advance(scenario==='success_before'?9999:scenario==='success_at'?10000:10001,false);
        if(scenario==='cleared_success_timer'){now=10;reply(0);}else if(b)b.resolve([sent]);else reply(0);
        await p;
        if(['success_before','cleared_success_timer'].includes(scenario)){ready();assert.equal(signal(0).aborted,false);}
        else {failed();assert.equal(signal(0).aborted,true);}
        clean();if(scenario==='cleared_success_timer'){const before=snap();saved();await flush();assert.deepEqual(snap(),before);}
    }else if(['retired_headers','expired_headers'].includes(scenario)){
        const p=ctx.loadHistory();let q;let bodyCalls=0;
        if(scenario==='retired_headers')q=ctx.loadHistory();else await advance(10000,false);
        requests[0].resolve({ok:true,json:()=>{bodyCalls++;return Promise.resolve([stale]);}});
        await flush();await p;assert.equal(bodyCalls,0);
        if(q){loading();reply(1);await q;ready();}else failed();clean();
    }else if(['network_error','http_error','json_error','missing_abort'].includes(scenario)){
        if(scenario==='missing_abort')ctx.AbortController=undefined;
        const p=ctx.loadHistory();
        if(scenario==='network_error')requests[0].reject(Error('private'));
        if(scenario==='http_error')requests[0].resolve({ok:false});
        if(scenario==='json_error'){const b=await body(0);b.reject(Error('private'));}
        await p;failed();clean();if(requests.length)assert.equal(signal(0).aborted,true);
    }else throw Error('unknown scenario');
    await new Promise(resolve=>setImmediate(resolve));assert.deepEqual(unhandled,[]);
    assert.ok(requests.every(r=>r.url==='/api/history?user_id=synthetic-user'&&r.options.cache==='no-store'&&!r.options.method&&r.options.headers['X-Telegram-Init-Data']===''));
    console.log(JSON.stringify({scenario,result:'PASS'}));
}
main().catch(error=>{console.error(error);process.exitCode=1;});
