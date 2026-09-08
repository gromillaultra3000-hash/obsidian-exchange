#!/usr/bin/env python3
"""Independent exact-source expiry checks in Node under three local timezones.

No application, database, production request, credentials or runtime mutation.
"""
import ast
import asyncio
from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

ROOT=Path('/root');MAIN=ROOT/'relay-fastapi/main.py'
BASE='73115816d41de5963d395aeaee841caf833dcdc2'
original=subprocess.run(['git','show',BASE+':relay-fastapi/main.py'],cwd=ROOT,capture_output=True,text=True,check=True).stdout
baseline='--baseline' in sys.argv
source=original if baseline else MAIN.read_text()
now=int(datetime(2026,9,8,tzinfo=timezone.utc).timestamp()*1000)

valid=[
 '2026-09-08 00:15:00','2026-09-08T00:15:00','2026-09-08T00:15:00Z',
 '2026-09-08T00:15:00+00:00','2026-09-08T03:15:00+03:00',
 '2026-09-07T17:15:00-07:00','2026-09-08T05:45:00+05:30',
 '2026-09-08T13:00:00+12:45','2026-09-08 00:15:00.123456+00:00',
 '2026-09-08T00:15:00.1Z','2026-09-08T00:15:00.000001Z',
 '2026-09-08T00:15:00.999999Z','2026-09-08T23:59:59+23:59',
 '2026-09-07T00:01:00-23:59','2026-09-08T00:15:00-00:00',
 '2024-02-29T12:00:00Z','2000-02-29T00:00:00Z','0099-12-31T23:59:59Z',
 '0001-01-01T00:00:00Z','9999-12-31T23:59:59Z','2026-09-08T00:00:00Z',
 '2026-09-07T23:59:59.999999Z',
]
invalid=[None,False,True,0,42,[],{},['2026-09-08T00:15:00Z'],
 '', '2026-09-08','2026-09-08T00:15','2026-9-08T00:15:00Z',
 '2026-09-08T24:00:00Z','2026-09-08T25:00:00Z','2026-09-08T00:60:00Z',
 '2026-09-08T00:15:60Z','2026-02-29T00:00:00Z','1900-02-29T00:00:00Z',
 '2026-02-30T00:00:00Z','2026-04-31T00:00:00Z','2026-00-08T00:00:00Z',
 '2026-13-08T00:00:00Z','2026-09-00T00:00:00Z','2026-09-32T00:00:00Z',
 '0000-01-01T00:00:00Z','10000-01-01T00:00:00Z','-001-01-01T00:00:00Z',
 '2026-09-08T00:15:00+24:00','2026-09-08T00:15:00+03:60',
 '2026-09-08T00:15:00+0300','2026-09-08T00:15:00+03:00Z',
 '2026-09-08T00:15:00.Z','2026-09-08T00:15:00.1234567Z',
 '2026-09-08T00:15:00z','2026-09-08t00:15:00Z',' 2026-09-08T00:15:00Z',
 '2026-09-08T00:15:00Z ','2026-09-08T00:15:00Z\n','2026-09-08T00:15:00Z\r',
 '2026-09-08T00:15:00Z\u2028','2026-09-08T00:15:00Z\u2029',
 '2026-09-08\t00:15:00Z','2026-09-08T00:15:00Z\x00','x'*10000,
 '</script><script>globalThis.__expiryInjected=1</script>',
 '<img src=x onerror="globalThis.__expiryInjected=2">',
]
def epoch(value):
    parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
    if parsed.tzinfo is None:parsed=parsed.replace(tzinfo=timezone.utc)
    delta=parsed-datetime(1970,1,1,tzinfo=timezone.utc)
    return delta.days*86400000+delta.seconds*1000+delta.microseconds//1000
cases=[{'name':'valid:'+value,'value':value,'expectedMs':epoch(value)} for value in valid]
cases += [{'name':'invalid:'+str(i),'value':value,'expectedMs':None} for i,value in enumerate(invalid)]

sys.path.insert(0,str(ROOT/'relay'))
pay=next(n for n in ast.parse(source).body if isinstance(n,ast.AsyncFunctionDef) and n.name=='pay')
pay.decorator_list=[]
class HTTPError(Exception):
    def __init__(self,status_code,detail=None):self.status_code=status_code
class Tags(HTMLParser):
    def __init__(self):super().__init__();self.tags=[]
    def handle_starttag(self,tag,attrs):self.tags.append((tag,dict(attrs)))
metadata={'expires':'2026-09-08T00:15:00+00:00'}
reader=SimpleNamespace(get_by_token=lambda token:{'order_id':101,'amount':1500,
 'status':'invoice_created','provider_payload':repr({'requisites':{'phone':'synthetic-detail'}}),
 'expires_at':metadata['expires'],'qr_payload':''},
 authorized_snapshot=lambda *args,**kwargs:{'order_id':101,'rub_amount':1500,
 'status':'pending','paid_btc_tx':'','currency':'TON','network':'TON','verification_requested':''})
context={'Request':object,'HTTPException':HTTPError,'_payment_status_reads':reader,
 '_receipt_state':lambda *args,**kwargs:'','_session_dead':lambda *args,**kwargs:False,
 '_payout_delayed':lambda *args,**kwargs:False,'audit_log':lambda *args:None,
 'logger':SimpleNamespace(error=lambda *args:None)}
exec(compile(ast.fix_missing_locations(ast.Module(body=[pay],type_ignores=[])),str(MAIN),'exec'),context)
def page():return asyncio.run(context['pay']('synthetic-expiry',SimpleNamespace(
    query_params={},client=SimpleNamespace(host='synthetic-local'))))
html=page();tags=Tags();tags.feed(html)
assert sum(t=='script' for t,_ in tags.tags)==1
script=html.split('<script>',1)[1].split('</script>',1)[0]
metadata['expires']='</script><script>globalThis.__expiryInjected=1</script>'
hostile=page();tags=Tags();tags.feed(hostile)
assert sum(t=='script' for t,_ in tags.tags)==1 and '\\u003c/script\\u003e' in hostile

program=r'''
const fs=require('node:fs'),vm=require('node:vm');const input=JSON.parse(fs.readFileSync(0,'utf8'));
let now=input.now,parsed=[],html='',timer=null,nextId=1;const timers=new Map(),requests=[];
class ControlledDate extends Date {
 static now(){return now;}
 static parse(value){const ms=Date.parse(value);parsed.push(ms);return ms;}
 getTime(){const ms=super.getTime();parsed.push(ms);return ms;}
}
class Element {
 constructor(){this.content='';}
 set innerHTML(value){this.content=String(value);}get innerHTML(){return this.content;}
 set textContent(value){this.content=String(value);}get textContent(){return this.content.replace(/<[^>]*>/g,'');}
}
const view={get innerHTML(){return html;},set innerHTML(value){html=String(value);timer=html.includes('id="timer"')?new Element():null;}};
const c={Date:ControlledDate,document:{getElementById:id=>id==='view'?view:id==='timer'?timer:null},
 setInterval:(fn,ms)=>{const id=nextId++;timers.set(id,{fn,ms});return id;},clearInterval:id=>timers.delete(id),
 setTimeout:()=>0,fetch:async(...args)=>{requests.push(args);return {ok:false}}};
vm.createContext(c);vm.runInContext(input.script,c);timers.clear();const checks=[];
const unknown='Срок действия реквизитов уточняется.';
function setup(values){timers.clear();parsed=[];now=input.now;c.values=values;
 vm.runInContext('_localExpired=false;_timer=null;Object.assign(C,values)',c);}
function finish(name,issues){checks.push({name,issues});}
for(const item of input.cases){
 setup({status:'pending',receipt:'',verification:'',dead:false,expiresAt:item.value});
 const snapshot=vm.runInContext('JSON.stringify(C)',c),issues=[];let error=null;
 try{vm.runInContext('render()',c,{timeout:500});}catch(e){error=e.name;}
 if(error)issues.push('exception:'+error);
 if(vm.runInContext('JSON.stringify(C)',c)!==snapshot)issues.push('canonical data mutated');
 if(item.expectedMs===null){
   if(!timer||timer.textContent!==unknown)issues.push('unknown-time fallback missing');
   if(vm.runInContext('_localExpired',c))issues.push('invalid metadata invented expiry');
   if(timers.size)issues.push('invalid metadata installed interval');
   if(html.includes('__expiryInjected')||c.__expiryInjected)issues.push('invalid metadata reached executable HTML');
 }else{
   if(parsed.at(-1)!==item.expectedMs)issues.push('wrong parsed instant');
   const seconds=Math.floor((item.expectedMs-now)/1000);
   if(seconds<=0){
     if(!vm.runInContext('_localExpired',c))issues.push('elapsed instant not locally expired');
     if(timers.size)issues.push('already elapsed timer reinstalled');
   }else{
     const expected=String(Math.floor(seconds/60)).padStart(2,'0')+':'+String(seconds%60).padStart(2,'0');
     if(!timer||!timer.textContent.includes(expected))issues.push('incorrect countdown');
     if(timers.size!==1)issues.push('future timer not singular');
   }
 }
 finish(item.name,issues);
}
// Explicit refresh cancels a prior valid timer when metadata becomes invalid.
setup({status:'pending',receipt:'',verification:'',dead:false,expiresAt:'2026-09-08T00:15:00Z'});
vm.runInContext('render()',c);const priorId=vm.runInContext('_timer',c);
vm.runInContext('C.expiresAt="bad";startTimer()',c);
finish('invalid-refresh-clears-prior-timer',!timers.has(priorId)&&timers.size===0&&timer.textContent===unknown?[]:['old timer retained']);
// Advance an actual captured interval to the deadline; local expiry never
// changes the canonical pending or stored receipt values.
for(const receipt of ['','stored']){
 setup({status:'pending',receipt,verification:'',dead:false,expiresAt:'2026-09-08T00:00:02Z'});
 vm.runInContext('render()',c);const interval=[...timers.values()][0];now+=2000;
 const issues=[];if(!interval)issues.push('future interval absent');else interval.fn();
 if(vm.runInContext('C.status',c)!=='pending'||vm.runInContext('C.receipt',c)!==receipt)issues.push('deadline changed canonical data');
 if(!vm.runInContext('_localExpired',c)||timers.size)issues.push('deadline did not settle timer');
 finish('elapsed-interval:'+receipt,issues);
}
for(const status of ['pending','paid','sent','expired','failed','cancelled'])
for(const receipt of ['','stored','sent'])for(const verification of ['','video']){
 if(status==='pending'&&!verification&&receipt!=='sent')continue;
 setup({status,receipt,verification,dead:true,expiresAt:'<script>invalid</script>'});
 const snapshot=vm.runInContext('JSON.stringify(C)',c);vm.runInContext('render()',c);
 const before=html;vm.runInContext('startTimer()',c);
 const issues=[];
 if(html!==before||vm.runInContext('JSON.stringify(C)',c)!==snapshot)issues.push('timer disturbed higher precedence view');
 if(timers.size)issues.push('missing timer element still installed interval');
 finish('precedence:'+status+':'+receipt+':'+verification,issues);
}
// Unknown metadata does not stop status polling; no writer method is supplied.
setup({status:'pending',receipt:'',verification:'',dead:false,expiresAt:'bad'});vm.runInContext('render()',c);
(async()=>{await vm.runInContext('poll()',c);
finish('status-poll-remains-read-only',requests.length===1&&requests[0].length===1&&requests[0][0].startsWith('/api/order/101?token=')?[]:['status poll changed']);
process.stdout.write(JSON.stringify({checks,timezone:Intl.DateTimeFormat().resolvedOptions().timeZone}));
})().catch(e=>{process.stderr.write(e.stack);process.exitCode=1});
'''
results=[]
for zone in ['UTC','America/Los_Angeles','Asia/Kolkata']:
    result=subprocess.run(['/usr/bin/node','-e',program],input=json.dumps({'script':script,'now':now,'cases':cases}),
        capture_output=True,text=True,check=True,env={'TZ':zone})
    results.append(json.loads(result.stdout))

# Strip only the opaque HTML value. Every Python statement/interpolation and
# numeric fallback must retain its exact AST; outside timer code, HTML is exact.
def normalized(text):
    tree=ast.parse(text);pay=next(n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='pay')
    values=sorted([n for n in ast.walk(pay) if isinstance(n,ast.Assign) and isinstance(n.value,ast.JoinedStr)
                   and any(isinstance(t,ast.Name) and t.id=='html' for t in n.targets)],key=lambda n:n.lineno)
    assert len(values)==2
    interpolations=[ast.dump(n,include_attributes=False) for n in ast.walk(values[1]) if isinstance(n,ast.FormattedValue)]
    values[1].value=ast.Constant(value='opaque HTML')
    return ast.dump(tree,include_attributes=False),interpolations
assert normalized(source)==normalized(original)
def outside_timer(text):
    a=text.index('function paymentExpiryMs(') if 'function paymentExpiryMs(' in text else text.index('function startTimer()')
    b=text.index('async function poll()',a)
    return text[:a]+'timer-reviewed-separately\n'+text[b:]
assert outside_timer(source)==outside_timer(original)
failures=[{'timezone':r['timezone'],**case} for r in results for case in r['checks'] if case['issues']]
if baseline:assert failures
else:assert not failures,json.dumps(failures[:5],ensure_ascii=False)
paths=[Path(__file__),ROOT/'relay/core/requisites.py',ROOT/'relay/services/requisite_origin.py',ROOT/'relay/core/txid.py']
if not baseline:paths.append(MAIN)
print(json.dumps({'schemaVersion':'e4-expiry-independent-security-probe.v1',
 'result':'EXPECTED_BASELINE_FAILURE' if baseline else 'PASS','baselineHead':BASE,
 'inputs':[{'path':str(p.relative_to(ROOT)),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in paths],
 'executedSourceSha256':hashlib.sha256(source.encode()).hexdigest(),
 'validTimestampCases':len(valid),'invalidTimestampCases':len(invalid),
 'timezones':[r['timezone'] for r in results],'cases':sum(len(r['checks']) for r in results),
 'failingCases':len(failures),'failures':failures,
 'securityChecks':{'timestampMarkupCannotBreakOutOfScript':True,
 'PythonAuthReadAPIReceiptVerificationMoneyAndNumericFallbackASTUnchanged':True,
 'allPythonInterpolationsIdentical':True,'sourceOutsideExpiryHelperAndTimerByteExact':True},
 'scope':'Exact AST-isolated pay HTML and actual inline JS with controlled Date.now/intervals in three process-local timezones. Expected valid epochs computed independently with Python datetime.',
 'productionDatabaseRequestsCredentialsWritesRestarts':False},ensure_ascii=False,indent=2))
