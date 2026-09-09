'use strict';
// Actual flow; synthetic SDK/challenge and permanently deferred verification.
const assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
const source = fs.readFileSync('relay/webapp.html', 'utf8');
function extract(name) {const m=source.match(new RegExp('^        (?:async )?function '+name+'\\([^]*?^        \\}(?=\\r?$)','m'));assert.ok(m,name);return m[0];}
const nodes={currency:{value:'TON'},network:{value:'MAINNET'},address:{value:'EQ'+'A'.repeat(46)},dest_tag:{value:''},no_tag:{checked:false},'tc-msg':{textContent:''},'tc-connect':{disabled:false}};
const calls={payload:0,verify:0};const timers=new Map();let seq=0,now=1000000;
const ui={connected:false,setConnectRequestParameters(){},async openModal(){},closeModal(){}};
const context=vm.createContext({document:{getElementById:id=>nodes[id]},tg:{initData:''},AbortController,ui,
 window:{TON_CONNECT_UI:{},__oeOfferings:[{code:'TON',networks:[{code:'MAINNET',label:'TON'}],wallet_connect:true}]},
 Date:{now:()=>now},setTimeout(fn,ms){timers.set(++seq,{fn,at:now+ms});return seq;},clearTimeout(id){timers.delete(id);},
 validateAddress(){},updateTagField(){},loadWallets(){},
 fetch(url){if(url==='/api/tonconnect/payload'){calls.payload++;return Promise.resolve({ok:true,async json(){return {payload:'synthetic-intent-'+calls.payload};}});}assert.equal(url,'/api/tonconnect/verify');calls.verify++;return new Promise(()=>{});}});
vm.runInContext('let tcUI=ui,tcPending=false,tcPreparation=null,tcRecipientGeneration=0,tcConnectionIntent=null;const tcConnectionPayloads=new Set();\n'+['buyRouteSignature','currentOffering','tcSay','tcInvalidateRecipient','tcRecipientState','tcAvailable','tcInit','tcHandleWallet','tcConnect'].map(extract).join('\n'),context);
async function main(){
 await vm.runInContext('tcConnect()',context);
 context.wallet={account:{address:'synthetic'},connectItems:{tonProof:{proof:{payload:'synthetic-intent-1',synthetic:true}}}};
 vm.runInContext('tcHandleWallet(wallet)',context);assert.equal(calls.verify,1);
 now+=3600000;for(const [id,t] of timers){if(t.at<=now){timers.delete(id);t.fn();}}
 await Promise.resolve();await vm.runInContext('tcConnect()',context);
 assert.equal(vm.runInContext('tcPending',context),true);assert.equal(calls.payload,1);assert.equal(timers.size,0);
 console.log(JSON.stringify({criterion:'TONCONNECT_VERIFICATION_WAIT_RECOVERY',simulatedElapsedMs:3600000,verificationPending:true,activeDeadlineTimers:timers.size,newPreparationRequestsAfterRetry:calls.payload-1,realNetworkCalls:0,walletSignatures:0,moneyWrites:0}));
}
main().catch(e=>{console.error(e);process.exitCode=1;});
