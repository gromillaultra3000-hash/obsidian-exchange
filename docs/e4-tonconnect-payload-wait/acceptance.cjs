'use strict';
// Execute the shipped recipient helper with adversarial SDK scheduling.
// All addresses/challenges are synthetic; no network, wallet, or money writes.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(process.argv[2] || 'relay/webapp.html', 'utf8');
const block = source.slice(source.indexOf('        let tcUI = null;'), source.indexOf("        document.getElementById('tc-connect').addEventListener"));
assert.ok(block.includes('async function tcConnect()'));
function extract(name) {
  const match = source.match(new RegExp('^        (?:async )?function ' + name + '\\([^]*?^        \\}(?=\\r?$)', 'm'));
  assert.ok(match, name); return match[0];
}
function deferred() {
  let resolve, reject;
  const promise = new Promise((a, b) => { resolve = a; reject = b; });
  return {promise, resolve, reject};
}
async function flush() { for (let i = 0; i < 20; i++) await Promise.resolve(); }
function harness(stage, options = {}) {
  const nodes = {currency:{value:'TON'},network:{value:'MAINNET'},address:{value:'manual-recipient'},dest_tag:{value:'manual-memo'},no_tag:{checked:false},'tc-msg':{textContent:''},'tc-connect':{disabled:false},'tc-group':{style:{}}};
  const gate = deferred(), second = deferred(), verification = deferred(), timers = new Map();
  let now = 1000000, sequence = 0, entered = false, callback, payloads = 0, verifies = 0, validations = 0, payloadSignal;
  const ui = {
    connected:stage === 'disconnect',
    onStatusChange(fn) { callback = fn; return () => {}; },
    setConnectRequestParameters() {},
    disconnect() { entered = true; return stage === 'disconnect' ? gate.promise : Promise.resolve(); },
    openModal() { entered = true; if(stage === 'closeModal') nodes.address.value='edited-before-close'; return stage === 'openModal' ? gate.promise : Promise.resolve(); },
    closeModal() { return stage === 'closeModal' ? gate.promise : Promise.resolve(); }
  };
  const context = vm.createContext({document:{getElementById:id=>nodes[id],addEventListener(){}},tg:{initData:''},AbortController,
    window:{location:{origin:'https://synthetic.invalid'},TON_CONNECT_UI:{TonConnectUI:function(){return ui;}},__oeOfferings:[{code:'TON',networks:[{code:'MAINNET',label:'TON'}],wallet_connect:true}]},
    Date:{now:()=>now},setTimeout(fn,ms){timers.set(++sequence,{fn,at:now+ms});return sequence;},clearTimeout(id){timers.delete(id);},
    validateAddress(){validations++;},updateTagField(){},loadWallets(){},
    async fetch(url, init) {
      if(url === '/api/tonconnect/payload') {
        payloads++;payloadSignal=init.signal;
        if(options.stallPayload==='fetch' && payloads===1) return gate.promise;
        if(options.holdSecond && payloads===2) return second.promise;
        return {ok:true,async json(){if(options.stallPayload==='body' && payloads===1)return gate.promise;return {payload:'synthetic-'+payloads};}};
      }
      assert.equal(url,'/api/tonconnect/verify'); verifies++;
      if(options.slowVerification) return verification.promise;
      return {ok:true,async json(){return {verified:true,address:'verified-synthetic-recipient'};}};
    }
  });
  vm.runInContext(extract('buyRouteSignature')+'\n'+extract('currentOffering')+'\n'+block,context);
  return {nodes,gate,second,verification,ui,context,timers,connect:()=>vm.runInContext('tcConnect()',context),get entered(){return entered;},
    stats:()=>({payloads,verifies,validations,payloadAborted:payloadSignal?.aborted}),get:code=>vm.runInContext(code,context),
    async status(wallet){await callback(wallet);await flush();},
    advance(ms,deliver=true){now+=ms;if(deliver)for(const [id,timer] of [...timers])if(timer.at<=now){timers.delete(id);timer.fn();}}
  };
}

const response=payload=>({ok:true,async json(){return {payload};}});
async function expired(stage,edit=false) {
  const h=harness('immediate',{stallPayload:stage,holdSecond:true});let settled=false;
  const first=h.connect().then(()=>settled=true);await flush();
  if(edit){h.nodes.address.value='edited';h.get('tcInvalidateRecipient()');}
  const status=h.nodes['tc-msg'].textContent;
  h.advance(8000);await flush();assert.equal(settled,true,stage+' deadline must release preparation');await first;
  assert.equal(h.get('tcPreparation'),null);assert.equal(h.nodes['tc-connect'].disabled,false);
  assert.equal(h.get('tcAvailable()'),true);assert.equal(h.stats().payloadAborted,true);
  if(edit)assert.equal(h.nodes['tc-msg'].textContent,status);
  const retry=h.connect();await flush();assert.equal(h.stats().payloads,2);
  const preparation=h.get('tcPreparation');
  h.gate.resolve(stage==='fetch'?response('synthetic-old'):{payload:'synthetic-old'});await flush();
  assert.equal(h.get('tcPreparation'),preparation,'late first read cannot clear retry');
  assert.equal(h.nodes['tc-connect'].disabled,true);assert.equal(h.entered,false);
  h.second.resolve(response('synthetic-fresh'));await retry;
  await h.status({account:{},connectItems:{tonProof:{proof:{payload:'synthetic-old'}}}});assert.equal(h.stats().verifies,0);
  await h.status({account:{},connectItems:{tonProof:{proof:{payload:'synthetic-fresh'}}}});assert.equal(h.stats().verifies,1);
  assert.equal(h.nodes.address.value,'verified-synthetic-recipient');assert.equal(h.timers.size,0);
  return {stage,edit,deadlineReleased:true,lateLoserIsolated:true,freshRetryVerified:true};
}
async function delayed(stage,delta) {
  const h=harness('immediate',{stallPayload:stage});const pending=h.connect();await flush();h.advance(delta,false);
  h.gate.resolve(stage==='fetch'?response('synthetic-late'):{payload:'synthetic-late'});await pending;
  assert.equal(h.get('tcConnectionIntent'),null);assert.equal(h.entered,false);assert.equal(h.get('tcPreparation'),null);
  assert.equal(h.nodes['tc-connect'].disabled,false);assert.equal(h.get('tcAvailable()'),true);assert.equal(h.timers.size,0);
  return {stage,clockDelta:delta,lateReadRejected:true};
}
(async()=>{const cases=[];for(const stage of ['fetch','body']){
 for(const edit of [false,true])cases.push(await expired(stage,edit));
 for(const delta of [8000,-1])cases.push(await delayed(stage,delta));
}console.log(JSON.stringify({criterion:'TONCONNECT_PAYLOAD_WAIT_RECOVERY',cases,realNetworkCalls:0,walletSignatures:0,moneyWrites:0}));
})().catch(error=>{console.error(error);process.exitCode=1;});
