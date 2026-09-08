'use strict';
// Verbatim production functions in shared VM; no wallet/network boundary is live.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const sourcePath = process.argv[2] || 'relay/webapp.html';
const source = fs.readFileSync(path.join(__dirname, 'e4_recipient_review_behavior.cjs'), 'utf8');
const prefix = source.slice(0, source.indexOf('\nfunction assertBuyWrite('));
const harness = vm.runInThisContext('(function(require,process){' + prefix + '\nreturn harness;})')(require,{argv:['','',sourcePath,'','{}']});
const key = 'oe.wallet-attempt.shared.v1';
const raw = '0:' + 'b'.repeat(64);
function fixture(options) {
 const h = harness(options);
 h.el('w-to').value = h.walletRequest.messages[0].address;
 h.el('w-amount').value = '1.25';
 h.context.loadWallets = () => {};
 return h;
}
async function clear(h) {
 h.el('wallet-attempt-ack').checked = true;
 await h.el('wallet-attempt-ack').fire('change');
 await h.el('wallet-attempt-remove').fire('click');
}
function friendly(wc = 0, flag = 0x51) {
 const body = Buffer.concat([Buffer.from([flag, wc & 255]), Buffer.alloc(32,0xbb)]);
 let crc = 0;
 for (const byte of body) { crc ^= byte << 8; for(let i=0;i<8;i++) crc = ((crc<<1)^((crc&0x8000)?0x1021:0))&65535; }
 return Buffer.concat([body,Buffer.from([crc>>8,crc&255])]).toString('base64url');
}
(async () => {
 let cases = 0;
 for (const action of ['transfer','payment']) {
  const values = new Map(); const h = fixture({localValues:values});
  const start = x => action === 'payment' ? x.context.walletPay(42,x.el('sell-card-pay')) : x.context.walletTransfer();
  await start(h); await h.confirm(); // synthetic generic failure
  assert.equal(h.signingAttempts.length,1);
  const record = JSON.parse(values.get(key));
  assert.match(record.attemptId,/^[0-9a-f-]{36}$/);
  const {attemptId,...metadata}=record;
  assert.deepEqual(metadata,{version:2,wallet:raw,network:'-239',operation:action,orderId:action==='payment'?42:null});
  await start(h); assert.equal(h.requests.length,1);
  const reload = fixture({localValues:values});
  reload.advance(365*86400000);
  await start(reload); assert.equal(reload.requests.length,0);
  await reload.el('wallet-attempt-remove').fire('click'); assert.ok(values.has(key));
  await clear(reload); assert.equal(values.has(key),false);
  assert.equal(reload.signingAttempts.length,0);
  await start(reload); assert.equal(reload.el('exchange-review-ack').checked,false);
  assert.equal(reload.signingAttempts.length,0); cases++;
 }
 // Persistence exists before the SDK is entered, and pending callbacks cannot clear it.
 {
 const values = new Map(); const h=fixture({localValues:values}); let reject;
 h.context.tcUI.sendTransaction=() => {assert.ok(values.has(key));return new Promise((_,r)=>{reject=r;});};
 await h.context.walletTransfer();const pending=h.confirm();for(let i=0;i<8;i++)await Promise.resolve();
 await clear(h);assert.ok(values.has(key));reject(new Error('unknown'));await pending;
 assert.ok(values.has(key));cases++;
 }
 // Hostile storage must never reach signing, even with manual event invocation.
 for(const failure of ['read','write','silent_write','remove']) {
 const values=new Map();const storage={getItem(k){if(failure==='read')throw Error('denied');return values.get(k)??null;},setItem(k,v){if(failure==='write')throw Error('quota');if(failure!=='silent_write')values.set(k,v);},removeItem(k){if(failure==='remove')throw Error('denied');values.delete(k);}};
 const h=fixture({localStorage:storage});await h.context.walletTransfer();
 if(failure!=='read')await h.confirm();
 if(failure==='remove'){assert.equal(h.signingAttempts.length,1);await clear(h);assert.ok(values.has(key));}
 else assert.equal(h.signingAttempts.length,0);
 await h.context.walletTransfer();assert.equal(h.signingAttempts.length,failure==='remove'?1:0);cases++;
 }
 for(const corrupt of ['{','null','{}',JSON.stringify({version:1,wallet:raw,network:'-239',operation:'transfer',orderId:null,secret:'unexpected'}),'x'.repeat(513)]) {
 const values=new Map([[key,corrupt]]);const h=fixture({localValues:values});await h.context.walletTransfer();assert.equal(h.requests.length,0);await clear(h);assert.equal(values.has(key),false);cases++;
 }
 // Friendly account normalization: bounce flags, both alphabets, workchain, CRC.
 {
 const h=fixture();assert.equal(h.context.walletAttemptAddress('EQDKbjIcfM6ezt8KjKJJLshZJJSqX7XOA4ff-W72r5gqPrHF','-239'),'0:ca6e321c7cce9ecedf0a8ca2492ec8592494aa5fb5ce0387dff96ef6af982a3e');for(const flag of [0x11,0x51])for(const wc of [0,-1]) {
 const address=friendly(wc,flag);for(const form of [address,address.replace(/-/g,'+').replace(/_/g,'/')])assert.equal(h.context.walletAttemptAddress(form,'-239'),wc+':'+ 'b'.repeat(64));
 }
 assert.equal(h.context.walletAttemptAddress(friendly(0,0xd1),'-239'),null);
 assert.equal(h.context.walletAttemptAddress(friendly(0,0xd1),'-3'),raw);
 const good=friendly();assert.equal(h.context.walletAttemptAddress(good.slice(0,47)+(good[47]==='A'?'B':'A'),'-239'),null);
 assert.equal(h.context.walletAttemptAddress(friendly(1),'-239'),null);cases++;
 }
 for(const changed of ['wallet','network','disconnect']) {
 const h=fixture();await h.context.walletTransfer();
 if(changed==='wallet')h.context.tcUI.account.address='0:'+ 'c'.repeat(64);
 if(changed==='network')h.context.tcUI.account.chain='-3';
 if(changed==='disconnect')h.context.tcUI.account=null;
 await h.confirm();assert.equal(h.signingAttempts.length,0);cases++;
 }
 // A previous checkbox cannot acknowledge substituted evidence.
 {
 const record={version:2,attemptId:'00000000-0000-4000-8000-000000000001',wallet:raw,network:'-239',operation:'payment',orderId:42};
 const values=new Map([[key,JSON.stringify(record)]]);const h=fixture({localValues:values});
 h.el('wallet-attempt-ack').checked=true;
 values.set(key,JSON.stringify({...record,orderId:43}));
 await h.el('wallet-attempt-remove').fire('click');assert.ok(values.has(key));
 assert.equal(h.el('wallet-attempt-ack').checked,false);assert.match(h.el('wallet-attempt-details').textContent,/#43/);
 await clear(h);assert.equal(values.has(key),false);cases++;
 }
 {
 const h=fixture();
 assert.equal(h.context.validWalletAttempt({version:1,wallet:[raw],network:'-239',operation:'transfer',orderId:null}),false);
 assert.equal(h.context.walletAttemptBinding({from_address:raw,request:h.walletRequest,sell_id:43},'payment',42),null);
 assert.equal(h.context.walletAttemptBinding({from_address:raw,request:h.walletRequest,sell_id:'42'},'payment',42),null);cases++;
 }
 console.log('WALLET_ATTEMPT_STATE_PASS '+cases);
})().catch(e=>{console.error(e.stack);process.exitCode=1;});
