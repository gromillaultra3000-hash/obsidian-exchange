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
  const gate = deferred(), verification = deferred(), timers = new Map();
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
        if(options.stallPayload==='fetch') return new Promise(()=>{});
        return {ok:true,async json(){if(options.stallPayload==='body')return new Promise(()=>{});return {payload:'synthetic-'+payloads};}};
      }
      assert.equal(url,'/api/tonconnect/verify'); verifies++;
      if(options.slowVerification) return verification.promise;
      return {ok:true,async json(){return {verified:true,address:'verified-synthetic-recipient'};}};
    }
  });
  vm.runInContext(extract('buyRouteSignature')+'\n'+extract('currentOffering')+'\n'+block,context);
  return {nodes,gate,verification,ui,context,timers,connect:()=>vm.runInContext('tcConnect()',context),get entered(){return entered;},
    stats:()=>({payloads,verifies,validations,payloadAborted:payloadSignal?.aborted}),get:code=>vm.runInContext(code,context),
    async status(wallet){await callback(wallet);await flush();},
    advance(ms,deliver=true){now+=ms;if(deliver)for(const [id,timer] of [...timers])if(timer.at<=now){timers.delete(id);timer.fn();}}
  };
}
async function expired(stage,lateOutcome) {
  const h=harness(stage);let settled=false;
  const completion=h.connect().then(()=>{settled=true;});await flush();assert.equal(h.entered,true);
  h.advance(8000);await flush();assert.equal(settled,true,stage+' must release stalled preparation');await completion;
  assert.equal(h.nodes['tc-connect'].disabled,false);assert.equal(h.get('tcPreparation'),null);
  assert.equal(h.get('tcConnectionIntent'),null);assert.equal(h.get('tcAvailable()'),false);
  if(stage !== 'closeModal') assert.match(h.nodes['tc-msg'].textContent,/перезагруз|обновите|обновить/i);
  h.nodes.address.value='edited-after-timeout';h.nodes.dest_tag.value='edited-memo';
  await h.connect();assert.equal(h.stats().payloads,1,'same-page retry cannot reuse poisoned SDK');
  if(lateOutcome==='resolve'){h.ui.connected=false;h.gate.resolve();}else h.gate.reject(new Error('late SDK failure'));
  await flush();
  await h.status({account:{},connectItems:{tonProof:{proof:{payload:'synthetic-1'}}}});
  await h.status(null);
  assert.equal(h.nodes.address.value,'edited-after-timeout');assert.equal(h.nodes.dest_tag.value,'edited-memo');
  assert.equal(h.stats().verifies,0);assert.equal(h.stats().validations,0);assert.equal(h.get('tcPreparation'),null);
  assert.equal(h.timers.size,0);
  return {stage,lateOutcome,preparationReleased:true,lateProofIgnored:true,samePageRetryQuarantined:true};
}
async function freshPage() {
  const h=harness('immediate');await h.connect();
  assert.equal(h.get('tcAvailable()'),true);assert.equal(h.nodes['tc-connect'].disabled,false);
  await h.status({account:{},connectItems:{tonProof:{proof:{payload:'synthetic-1'}}}});
  assert.equal(h.stats().verifies,1);assert.equal(h.nodes.address.value,'verified-synthetic-recipient');
  assert.equal(h.timers.size,0);return {stage:'fresh-page',timelyHandoffVerified:true};
}
async function delayedTimer(stage) {
  const h=harness(stage);const completion=h.connect();await flush();
  h.advance(8000,false);h.ui.connected=false;h.gate.resolve();await flush();await completion;
  assert.equal(h.get('tcConnectionIntent'),null,'wall-clock deadline must retire late handoff before timer delivery');
  assert.equal(h.get('tcAvailable()'),false);assert.equal(h.nodes['tc-connect'].disabled,false);
  assert.equal(h.timers.size,0);return {stage,delayedTimer:true,lateHandoffRejected:true};
}
async function verificationRetired() {
  const h=harness('openModal',{slowVerification:true});const completion=h.connect();await flush();
  h.advance(1000);
  const proof=h.status({account:{},connectItems:{tonProof:{proof:{payload:'synthetic-1'}}}});await flush();
  assert.equal(h.stats().verifies,1);
  h.advance(7000);await flush();await completion;
  h.nodes.address.value='manual-after-sdk-expiry';
  h.verification.resolve({ok:true,async json(){return {verified:true,address:'late-verification'};}});
  await proof;assert.equal(h.nodes.address.value,'manual-after-sdk-expiry');assert.equal(h.stats().validations,0);
  assert.equal(h.timers.size,0);return {stage:'openModal',inFlightVerificationRetired:true};
}
async function timelyRejectionRetry() {
  const h=harness('openModal');const completion=h.connect();await flush();h.gate.reject(new Error('timely failure'));await completion;
  assert.equal(h.get('tcAvailable()'),true);assert.equal(h.get('tcConnectionIntent'),null);
  h.ui.openModal=()=>Promise.resolve();await h.connect();assert.equal(h.stats().payloads,2);
  await h.status({account:{},connectItems:{tonProof:{proof:{payload:'synthetic-1'}}}});
  assert.equal(h.stats().verifies,0,'prior attempt proof cannot authorize retry');
  await h.status({account:{},connectItems:{tonProof:{proof:{payload:'synthetic-2'}}}});
  assert.equal(h.stats().verifies,1);return {stage:'timely-rejection',explicitRetryVerified:true,previousProofIgnored:true};
}
module.exports={harness,flush};
if(require.main===module)(async()=>{
  const cases=[];
  for(const stage of ['disconnect','openModal','closeModal'])for(const outcome of ['resolve','reject'])cases.push(await expired(stage,outcome));
  for(const stage of ['disconnect','openModal','closeModal'])cases.push(await delayedTimer(stage));
  cases.push(await verificationRetired());cases.push(await timelyRejectionRetry());
  cases.push(await freshPage());
  console.log(JSON.stringify({criterion:'TONCONNECT_SDK_HANDOFF_WAIT_RECOVERY',cases,realNetworkCalls:0,walletSignatures:0,moneyWrites:0}));
})().catch(error=>{console.error(error);process.exitCode=1;});
