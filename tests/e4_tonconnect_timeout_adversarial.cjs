'use strict';
const assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
const source = fs.readFileSync(process.argv[2] || 'relay/webapp.html', 'utf8');
function extract(name) {const m=source.match(new RegExp('^        (?:async )?function '+name+'\\([^]*?^        \\}(?=\\r?$)','m'));assert.ok(m,name);return m[0];}
async function flush() {for(let i=0;i<12;i++) await Promise.resolve();}
function setup(mode) {
    const nodes={currency:{value:'TON'},network:{value:'MAINNET'},address:{value:'EQ'+'A'.repeat(46)},dest_tag:{value:''},no_tag:{checked:false},'tc-msg':{textContent:''},'tc-connect':{disabled:false}};
    const calls={payload:0,verify:[],profiles:0};const timers=new Map();let seq=0,now=1000000;
    const ui={connected:false,setConnectRequestParameters(){},async openModal(){},closeModal(){}};
    const context=vm.createContext({document:{getElementById:id=>nodes[id]},tg:{initData:''},AbortController,ui,
        window:{TON_CONNECT_UI:{},__oeOfferings:[{code:'TON',networks:[{code:'MAINNET',label:'TON'}],wallet_connect:true}]},
        Date:{now:()=>now},setTimeout(fn,ms){timers.set(++seq,{fn,at:now+ms});return seq;},clearTimeout(id){timers.delete(id);},
        validateAddress(){},updateTagField(){},loadWallets(){calls.profiles++;},
        fetch(url,options){
            if(url==='/api/tonconnect/payload'){calls.payload++;return Promise.resolve({ok:true,async json(){return {payload:'nonce-'+calls.payload};}});}
            assert.equal(url,'/api/tonconnect/verify');
            const call={signal:options.signal};calls.verify.push(call);
            if(mode==='body') return Promise.resolve({ok:true,json(){return new Promise((resolve,reject)=>Object.assign(call,{resolve,reject}));}});
            return new Promise((resolve,reject)=>Object.assign(call,{resolve,reject}));
        }});
    vm.runInContext('let tcUI=ui,tcPending=false,tcPreparation=null,tcRecipientGeneration=0,tcConnectionIntent=null;const tcConnectionPayloads=new Set();\n'+
        ['buyRouteSignature','currentOffering','tcSay','tcInvalidateRecipient','tcRecipientState','tcAvailable','tcInit','tcHandleWallet','tcConnect'].map(extract).join('\n'),context);
    return {nodes,calls,timers,context,prepare:()=>vm.runInContext('tcConnect()',context),
        start(){context.wallet={account:{address:'synthetic'},connectItems:{tonProof:{proof:{payload:'nonce-'+calls.payload}}}};return vm.runInContext('tcHandleWallet(wallet)',context);},
        jump(ms){now+=ms;},
        async advance(ms){now+=ms;for(const [id,t] of timers){if(t.at<=now){timers.delete(id);t.fn();}}await flush();},
        deliver(i,error=false){const call=calls.verify[i];if(error)call.reject(new Error('late synthetic failure'));else {const data={verified:true,address:'EQ'+'B'.repeat(46)};call.resolve(mode==='body'?data:{ok:true,async json(){return data;}});}}
    };
}
let checks=0;
async function main(){
    for(const mode of ['headers','body']) for(const late of ['success','error']) {
        const h=setup(mode);await h.prepare();const first=h.start();await flush();
        assert.equal(h.calls.verify.length,1);await h.advance(8001);await first;
        assert.equal(vm.runInContext('tcPending',h.context),false);assert.equal(h.calls.verify[0].signal.aborted,true);
        assert.match(h.nodes['tc-msg'].textContent,/слишком много времени/);assert.equal(h.calls.payload,1);
        await h.prepare();const second=h.start();await flush();assert.equal(h.calls.verify.length,2);
        const before=JSON.stringify(h.nodes);h.deliver(0,late==='error');await flush();
        assert.equal(vm.runInContext('tcPending',h.context),true,'old loser must not unlock newer verification');
        assert.equal(JSON.stringify(h.nodes),before);assert.equal(h.calls.profiles,0);
        h.deliver(1);await second;assert.equal(vm.runInContext('tcPending',h.context),false);
        assert.equal(h.calls.profiles,1);assert.equal(h.timers.size,0);checks++;
    }
    for(const mode of ['edit','disconnect']) {
        const h=setup('headers');await h.prepare();const p=h.start();await flush();
        if(mode==='edit'){h.nodes.address.value='new';vm.runInContext('tcInvalidateRecipient()',h.context);}
        else await vm.runInContext('tcHandleWallet(null)',h.context);
        const before=JSON.stringify(h.nodes);await h.advance(8001);await p;
        assert.equal(JSON.stringify(h.nodes),before);assert.equal(vm.runInContext('tcPending',h.context),false);checks++;
    }
    for(const jump of [8000,9000,-1]) {
        const h=setup('headers');await h.prepare();const p=h.start();h.jump(jump);h.deliver(0);await p;
        assert.equal(h.calls.profiles,0);assert.equal(vm.runInContext('tcPending',h.context),false);
        assert.match(h.nodes['tc-msg'].textContent,/слишком много времени/);assert.equal(h.timers.size,0);checks++;
    }
    const h=setup('headers');await h.prepare();const p=h.start();h.deliver(0);await p;
    assert.equal(h.calls.profiles,1);assert.equal(h.timers.size,0);checks++;
    console.log(JSON.stringify({result:'PASS',checks}));
}
main().catch(e=>{console.error(e);process.exitCode=1;});
