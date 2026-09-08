'use strict';
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const sourcePath = process.argv[2] || '/root/relay/webapp.html';
const source = fs.readFileSync(sourcePath, 'utf8');
const begin = source.indexOf('        let historyOrders =');
const end = source.indexOf('        (function wireHistoryControls()', begin);
const escapeBegin = source.indexOf('        function esc(s)');
const escapeEnd = source.indexOf('        async function loadWalletBook()', escapeBegin);
assert.ok(begin > 0 && end > begin && escapeBegin > 0 && escapeEnd > escapeBegin);
const code = source.slice(escapeBegin, escapeEnd) + source.slice(begin, end);
function deferred() {let resolve, reject; const promise = new Promise((a,b) => {resolve=a;reject=b;}); return {promise,resolve,reject};}
const flush = async () => {for(let i=0;i<10;i++) await Promise.resolve();};
function setup() {
  const nodes = new Map(['history-list','history-summary','history-load-status','ecosystem-activity-status'].map(id=>[id,{
    id, innerHTML:'', textContent:'', style:{}, attributes:{}, setAttribute(name,value){this.attributes[name]=value;}, querySelectorAll(){return [];},
  }]));
  const filters=['all','pending','paid','sent'].map(historyFilter=>({dataset:{historyFilter},classList:{toggle(){}}}));
  const requests=[];
  const context=vm.createContext({document:{getElementById:id=>nodes.get(id),querySelectorAll:()=>filters},
    location:{origin:'https://synthetic.invalid'}, userId:'synthetic-user', tg:{initData:'',openLink(){throw Error('navigation forbidden');}},
    window:{open(){throw Error('navigation forbidden');}}, navigator:{get clipboard(){throw Error('clipboard forbidden');}},
    fetch(url, options){
      assert.equal(url,'/api/history?user_id=synthetic-user');
      assert.equal(options.method,undefined); assert.equal(options.cache,'no-store');
      assert.equal(options.headers['X-Telegram-Init-Data'],'');
      const d=deferred();requests.push({...d,url,options});return d.promise;
    }});
  vm.runInContext(code,context);
  const snapshot=()=>({html:nodes.get('history-list').innerHTML,summary:nodes.get('history-summary').innerHTML,
    summaryDisplay:nodes.get('history-summary').style.display, status:nodes.get('history-load-status').textContent,
    busy:nodes.get('history-list').attributes['aria-busy'],overview:nodes.get('ecosystem-activity-status').textContent});
  return {context,nodes,requests,snapshot};
}
const order=(id,status)=>({order_id:id,status,currency:'TON',amount:2000,created:'synthetic date',
  ...(status==='pending'?{session_token:'synthetic-pay-token'}:{tx_url:'https://explorer.invalid/synthetic-evidence'})});
const permutations=[[0,1,2],[0,2,1],[1,0,2],[1,2,0],[2,0,1],[2,1,0]];
async function main() {
  let schedules=0;
  for(const resolution of ['fetch','body']) for(let loaders=0;loaders<8;loaders++) for(const finalKind of ['success','network_error','invalid_body']) for(const sequence of permutations) {
    const env=setup(), promises=[], bodies=[];
    for(let i=0;i<3;i++) {
      const loader=(loaders>>i)&1?'loadEcosystemActivity':'loadHistory';
      promises.push(env.context[loader]());
      assert.equal(env.requests.length,i+1,'overview/history must use exactly one shared history GET per explicit refresh');
      if(resolution==='body') {
        const body=deferred();bodies.push(body);
        env.requests[i].resolve({ok:true,json:()=>body.promise});await flush();
      }
    }
    const initial=env.snapshot();
    assert.equal(initial.busy,'true');assert.match(initial.status,/Обновляем/);
    assert.equal(initial.summaryDisplay,'none');assert.doesNotMatch(initial.html,/synthetic-pay-token|synthetic-evidence/);
    let latestFinished=false, latestSnapshot;
    for(const i of sequence) {
      const value=[order(i===2?'LATEST-SENT':'STALE-PENDING',''+(i===2?'sent':'pending'))];
      if(resolution==='body') {
        if(i===2 && finalKind==='network_error') bodies[i].reject(Error('private-body-error'));
        else bodies[i].resolve(i===2 && finalKind==='invalid_body'?null:value);
      } else {
        if(i===2 && finalKind==='network_error') env.requests[i].reject(Error('private-fetch-error'));
        else env.requests[i].resolve({ok:true,json:async()=>i===2&&finalKind==='invalid_body'?null:value});
      }
      await promises[i];await flush();
      if(i===2) {
        latestFinished=true;latestSnapshot=env.snapshot();
        assert.equal(latestSnapshot.busy,'false');
        assert.doesNotMatch(latestSnapshot.html,/STALE-PENDING|synthetic-pay-token/);
        if(finalKind==='success') {assert.match(latestSnapshot.html,/LATEST-SENT/);assert.match(latestSnapshot.html,/synthetic-evidence/);assert.match(latestSnapshot.overview,/Нет активных/);}
        else {assert.match(latestSnapshot.html,/недоступна/);assert.equal(latestSnapshot.summaryDisplay,'none');assert.match(latestSnapshot.overview,/недоступны/);}
      } else assert.deepEqual(env.snapshot(),latestFinished?latestSnapshot:initial,'obsolete completion must have zero visible state effect');
    }
    assert.equal(latestFinished,true);
    schedules++;
  }
  const edgeChecks=[];
  for(const obsoleteKind of ['network_error','http_error','json_throw','json_reject','invalid_body','null_row']) for(const newerReady of [false,true]) {
    const env=setup(),old=env.context.loadEcosystemActivity(),latest=env.context.loadHistory();
    if(newerReady) {env.requests[1].resolve({ok:true,json:async()=>[order('LATEST-SENT','sent')]});await latest;}
    const before=env.snapshot();
    if(obsoleteKind==='network_error') env.requests[0].reject(Error('private-obsolete-error'));
    else if(obsoleteKind==='http_error') env.requests[0].resolve({ok:false});
    else if(obsoleteKind==='json_throw') env.requests[0].resolve({ok:true,json(){throw Error('private-obsolete-error');}});
    else if(obsoleteKind==='json_reject') env.requests[0].resolve({ok:true,json:async()=>{throw Error('private-obsolete-error');}});
    else env.requests[0].resolve({ok:true,json:async()=>obsoleteKind==='null_row'?[null]:null});
    await old;assert.deepEqual(env.snapshot(),before,'obsolete failure cannot modify a newer loading or ready state');
    if(!newerReady) {env.requests[1].resolve({ok:true,json:async()=>[order('LATEST-SENT','sent')]});await latest;}
    edgeChecks.push('obsolete_'+obsoleteKind+'_ignored_while_newer_'+(newerReady?'ready':'loading'));
  }
  {
    const env=setup();
    let p=env.context.loadHistory();env.requests[0].resolve({ok:true,json:async()=>[order('OLD','pending')]});await p;
    assert.match(env.snapshot().html,/synthetic-pay-token/);
    p=env.context.loadEcosystemActivity();
    for(const filter of ['pending','sent','all','bogus']) {env.context.setHistoryFilter(filter);assert.equal(env.snapshot().busy,'true');assert.doesNotMatch(env.snapshot().html,/OLD|synthetic-pay-token/);assert.equal(env.snapshot().summaryDisplay,'none');}
    env.requests[1].reject(Error('synthetic private error'));await p;
    for(const filter of ['all','pending','paid','sent']) {env.context.setHistoryFilter(filter);assert.equal(env.snapshot().busy,'false');assert.match(env.snapshot().html,/недоступна/);assert.doesNotMatch(env.snapshot().html,/OLD|private error/);}
    p=env.context.loadHistory();env.context.setHistoryFilter('sent');env.requests[2].resolve({ok:true,json:async()=>[order('NEW','sent'),order('OTHER','pending')]});await p;
    assert.match(env.snapshot().html,/NEW/);assert.doesNotMatch(env.snapshot().html,/OTHER/);assert.match(env.snapshot().overview,/1 ожидают/);
    edgeChecks.push('filter_no_loading_error_resurrection_then_latest_success_respects_current_filter');
  }
  for(const kind of ['http_error','json_throw','json_reject','null_row','nonarray']) {
    const env=setup();const p=env.context.loadHistory();
    if(kind==='http_error') env.requests[0].resolve({ok:false,json(){throw Error('must not parse');}});
    else if(kind==='json_throw') env.requests[0].resolve({ok:true,json(){throw Error('private-json-error');}});
    else if(kind==='json_reject') env.requests[0].resolve({ok:true,json:async()=>{throw Error('private-json-error');}});
    else env.requests[0].resolve({ok:true,json:async()=>kind==='null_row'?[null]:{orders:[]}});
    await p;const state=env.snapshot();assert.equal(state.busy,'false');assert.match(state.html,/недоступна/);assert.doesNotMatch(state.html,/private-json-error/);assert.equal(state.summaryDisplay,'none');edgeChecks.push(kind+'_fails_closed');
  }
  return {reviewer:'/root/support_security',node:process.version,source:sourcePath,sourceSha256:crypto.createHash('sha256').update(source).digest('hex'),result:'PASS',interleavings:schedules,edgeChecks,
    scope:'Exact shipped JavaScript executed in synthetic VM; fetch never contacts network, navigation and clipboard throw; no money/customer/service/064A actions.'};
}
main().then(result=>process.stdout.write(JSON.stringify(result,null,2)+'\n')).catch(error=>{console.error(error);process.exitCode=1;});
