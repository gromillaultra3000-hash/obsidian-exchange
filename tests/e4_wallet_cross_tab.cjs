'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const sourcePath = process.argv[2] || 'relay/webapp.html';
const source = fs.readFileSync(path.join(__dirname,'e4_recipient_review_behavior.cjs'),'utf8');
const prefix = source.slice(0,source.indexOf('\nfunction assertBuyWrite('));
const harness = vm.runInThisContext('(function(require,process){'+prefix+'\nreturn harness;})')(require,{argv:['','',sourcePath,'','{}']});
const key='oe.wallet-attempt.shared.v1', legacyKey='oe.wallet-attempt.v1';
const wallet='0:'+ 'b'.repeat(64);
function deferred(){let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {resolve,reject,promise};}
async function flush(){for(let i=0;i<16;i++)await Promise.resolve();}
function manager(){let held=false;return {calls:[], delay:null, async request(name,options,callback){
 this.calls.push({name,options});assert.equal(name,'oe.wallet-handoff.v1');assert.deepEqual(JSON.parse(JSON.stringify(options)),{mode:'exclusive',ifAvailable:true});
 if(held)return callback(null);held=true;
 try{if(this.delay)await this.delay.promise;return await callback({name});}finally{held=false;}
}};}
function fixture(localValues,locks,options={}){
 const h=harness({localValues,locks,...options});h.el('w-to').value=h.walletRequest.messages[0].address;h.el('w-amount').value='1.25';h.context.loadWallets=()=>{};
 h.start=()=>h.context.walletTransfer();return h;
}
async function clear(h){h.context.readWalletAttempt();h.context.renderWalletAttempt();h.el('wallet-attempt-ack').checked=true;await h.el('wallet-attempt-ack').fire('change');await h.el('wallet-attempt-remove').fire('click');}
function record(id='00000000-0000-4000-8000-000000000001'){return {version:2,attemptId:id,wallet,network:'-239',operation:'transfer',orderId:null};}
(async()=>{let cases=0;
 // Both tabs prepare before either confirms. Only one can publish/sign; deletion
 // and timer/reload cannot remove the winner's evidence while SDK pending.
 {
 const values=new Map(),locks=manager(),a=fixture(values,locks),b=fixture(values,locks),sdk=deferred();
 a.context.tcUI.sendTransaction=()=>{a.signingAttempts.push('inert');assert.ok(values.has(key));return sdk.promise;};
 await a.start();await b.start();const first=a.confirm(),second=b.confirm();await flush();await second;
 assert.equal(a.signingAttempts.length,1);assert.equal(b.signingAttempts.length,0);
 await clear(b);assert.ok(values.has(key));assert.match(b.el('wallet-attempt-details').textContent,/другой вкладке/);
 const reload=fixture(values,locks);reload.advance(365*86400000);await reload.start();assert.equal(reload.requests.length,0);
 sdk.reject(Error('unknown'));await first;assert.ok(values.has(key));await clear(b);assert.equal(values.has(key),false);assert.equal(b.signingAttempts.length,0);cases++;
 }
 // A holder can disappear after publication; released browser lock is not
 // evidence of cancellation. A different tab still cannot send automatically.
 {
 const values=new Map([[key,JSON.stringify(record())]]),h=fixture(values,manager());await h.start();assert.equal(h.requests.length,0);await clear(h);assert.equal(values.has(key),false);assert.equal(h.signingAttempts.length,0);cases++;
 }
 // A delayed Web Locks callback must not use a cancelled, expired or changed review/account.
 for(const change of ['close','expire','account']){
 const locks=manager(),values=new Map(),h=fixture(values,locks);await h.start();locks.delay=deferred();const pending=h.confirm();await flush();
 if(change==='close')h.context.closeExchangeReview();if(change==='expire')h.advance(120001);if(change==='account')h.context.tcUI.account.address='0:'+ 'c'.repeat(64);
 locks.delay.resolve();await pending;assert.equal(h.signingAttempts.length,0);assert.equal(values.has(key),false);cases++;
 }
 // Stale acknowledgement of identical business fields cannot delete the next attempt.
 {
 const values=new Map([[key,JSON.stringify(record())]]),h=fixture(values,manager());
 h.el('wallet-attempt-ack').checked=true;values.set(key,JSON.stringify(record('00000000-0000-4000-8000-000000000002')));
 await h.el('wallet-attempt-remove').fire('click');assert.ok(values.has(key));assert.equal(h.el('wallet-attempt-ack').checked,false);cases++;
 }
 for(const failure of ['locks_absent','locks_reject','storage_read','storage_write','storage_silent','storage_remove','uuid_absent']){
 const values=new Map(),locks=manager(),h=fixture(values,locks);
 if(failure==='locks_absent')h.context.navigator={};
 if(failure==='locks_reject')locks.request=async()=>{throw Error('denied');};
 if(failure==='uuid_absent')h.context.crypto={};
 if(failure==='storage_read')h.context.localStorage.getItem=()=>{throw Error('denied');};
 if(failure==='storage_write')h.context.localStorage.setItem=()=>{throw Error('quota');};
 if(failure==='storage_silent')h.context.localStorage.setItem=()=>{};
 await h.start();if(!['locks_absent','storage_read','uuid_absent'].includes(failure))await h.confirm();
 if(failure==='storage_remove'){h.context.localStorage.removeItem=()=>{throw Error('denied');};await clear(h);assert.ok(values.has(key));assert.equal(h.signingAttempts.length,1);}
 else assert.equal(h.signingAttempts.length,0);
 cases++;
 }
 // Legacy evidence migrates under the same lock and remains in session storage;
 // conflicting shared evidence is not overwritten or silently discarded.
 for(const conflict of [false,true]){
 const old={version:1,wallet,network:'-239',operation:'payment',orderId:42};
 const sessionValues=new Map([[legacyKey,JSON.stringify(old)]]),values=new Map();
 if(conflict)values.set(key,JSON.stringify(record()));
 const before=values.get(key),h=fixture(values,manager(),{sessionValues});await flush();await h.start();
 assert.equal(h.signingAttempts.length,0);assert.equal(h.requests.length,0);assert.ok(sessionValues.has(legacyKey));
 assert.ok(values.has(key));if(conflict)assert.equal(values.get(key),before);else assert.equal(JSON.parse(values.get(key)).orderId,42);
 await clear(h);assert.equal(values.has(key),false);assert.equal(sessionValues.has(legacyKey),false);cases++;
 }
 console.log('WALLET_CROSS_TAB_PASS '+cases);
})().catch(e=>{console.error(e.stack);process.exitCode=1;});
