'use strict';
// Actual preparation helper; fake SDK waits/clock, no network or signatures.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('relay/webapp.html','utf8');
function extract(name){const m=source.match(new RegExp('^        (?:async )?function '+name+'\\([^]*?^        \\}(?=\\r?$)','m'));assert.ok(m,name);return m[0];}
async function scenario(stage){
 const nodes={currency:{value:'TON'},network:{value:'MAINNET'},address:{value:'EQ'+'A'.repeat(46)},dest_tag:{value:''},no_tag:{checked:false},'tc-msg':{textContent:''},'tc-connect':{disabled:false}};
 let requests=0,waiting=false,now=1000000,seq=0;const timers=new Map();
 const ui={connected:stage==='disconnect',setConnectRequestParameters(){},disconnect(){waiting=true;return new Promise(()=>{});},openModal(){waiting=true;return new Promise(()=>{});},closeModal(){}};
 const context=vm.createContext({document:{getElementById:id=>nodes[id]},tg:{initData:''},AbortController,ui,Date:{now:()=>now},
 window:{TON_CONNECT_UI:{},__oeOfferings:[{code:'TON',networks:[{code:'MAINNET',label:'TON'}],wallet_connect:true}]},
 setTimeout(fn,ms){timers.set(++seq,{fn,at:now+ms});return seq;},clearTimeout(id){timers.delete(id);},
 async fetch(url){assert.equal(url,'/api/tonconnect/payload');requests++;return {ok:true,async json(){return {payload:'synthetic-'+requests};}};}});
 vm.runInContext('let tcUI=ui,tcPending=false,tcPreparation=null,tcRecipientGeneration=0,tcConnectionIntent=null;const tcConnectionPayloads=new Set();\n'+['buyRouteSignature','currentOffering','tcSay','tcInvalidateRecipient','tcRecipientState','tcAvailable','tcInit','tcConnect'].map(extract).join('\n'),context);
 vm.runInContext('tcConnect()',context);while(!waiting)await new Promise(resolve=>setImmediate(resolve));
 now+=3600000;for(const [id,t] of timers){if(t.at<=now){timers.delete(id);t.fn();}}
 await Promise.resolve();await vm.runInContext('tcConnect()',context);
 assert.equal(vm.runInContext('tcPreparation !== null',context),true);assert.equal(nodes['tc-connect'].disabled,true);assert.equal(requests,1);assert.equal(timers.size,0);
 return {stage,simulatedElapsedMs:3600000,preparationPending:true,connectButtonDisabled:true,activeDeadlineTimers:0,newPreparationRequestsAfterRetry:0};
}
(async()=>console.log(JSON.stringify({criterion:'TONCONNECT_SDK_HANDOFF_WAIT_RECOVERY',cases:[await scenario('disconnect'),await scenario('modal-opening')],realNetworkCalls:0,walletSignatures:0,moneyWrites:0})))().catch(e=>{console.error(e);process.exitCode=1;});
