#!/usr/bin/env python3
"""Bounded independent terminal-renderer probe; synthetic page data and Node VM.

Only the actual pay handler AST is executed. No application startup, database,
network, provider, credentials, production mutation or service operation.
"""
import ast
import asyncio
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import subprocess
import sys
from types import SimpleNamespace

ROOT = Path('/root')
BASE = '4c7882c15d6d88ff80d56d2cc160076eff929f95'
MAIN = ROOT/'relay-fastapi/main.py'
baseline = subprocess.run(['git', 'show', BASE+':relay-fastapi/main.py'], cwd=ROOT,
                          capture_output=True, text=True, check=True).stdout
baseline_mode = '--baseline' in sys.argv
source = baseline if baseline_mode else MAIN.read_text()
sys.path.insert(0, str(ROOT/'relay'))
node = next(n for n in ast.parse(source).body if isinstance(n, ast.AsyncFunctionDef) and n.name == 'pay')
node.decorator_list = []

class HTTPError(Exception):
    def __init__(self, status_code, detail=None): self.status_code = status_code

payload = 'Synthetic </script><script>globalThis.__securityInjected=1</script>'
detail = "7');globalThis.__securityInjected=2;//\" data-extra=\"oops"
reads = []
def session(value):
    reads.append('get_by_token')
    return {'order_id':101,'amount':1500,'provider_payload':repr({'requisites':{
        'bank_name':payload,'phone':detail}}),'expires_at':'','qr_payload':'','status':'invoice_created'}
def snapshot(*args, **kwargs):
    reads.append('authorized_snapshot')
    return {'order_id':101,'rub_amount':1500,'status':'pending','paid_btc_tx':'',
            'currency':'TON','network':'TON','verification_requested':''}
namespace = {'Request':object,'HTTPException':HTTPError,
    '_payment_status_reads':SimpleNamespace(get_by_token=session,authorized_snapshot=snapshot),
    '_receipt_state':lambda *a,**kw:'','_session_dead':lambda *a,**kw:False,
    '_payout_delayed':lambda *a,**kw:False,'audit_log':lambda *a:None,
    'logger':SimpleNamespace(error=lambda *a:None)}
exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),str(MAIN),'exec'),namespace)
page = asyncio.run(namespace['pay']('synthetic-terminal-review',SimpleNamespace(
    client=SimpleNamespace(host='synthetic-local'),query_params={})))
class Tags(HTMLParser):
    def __init__(self): super().__init__(); self.tags=[]
    def handle_starttag(self,tag,attrs):self.tags.append((tag,dict(attrs)))
tags=Tags();tags.feed(page)
assert sum(tag=='script' for tag,_ in tags.tags)==1
script=page.split('<script>',1)[1].split('</script>',1)[0]
assert '\\u003c/script\\u003e' in script

js = r'''
const fs=require('node:fs'),vm=require('node:vm');
const input=JSON.parse(fs.readFileSync(0,'utf8'));
const view={innerHTML:''};let calls=[];let response=null;
const c={document:{getElementById:()=>view},setInterval:()=>0,clearInterval:()=>{},setTimeout:()=>0,
fetch:async(...args)=>{calls.push(args);return {ok:true,json:async()=>response}}};
vm.createContext(c);vm.runInContext(input.script,c);
const activeHtml=view.innerHTML;const results=[];
function configure(values){c.values=values;vm.runInContext('Object.assign(C,values);_localExpired=!!values.localExpired;render()',c);}
function inspect(name,expected){const html=view.innerHTML;
 const text=html.replace(/<[^>]*>/g,' ');const status=vm.runInContext('C.status',c);
 const reason=expected==='failed'?/Заявка не выполнена/:expected==='cancelled'?/Заявка отменена/:/Срок оплаты заявки истёк|Заявка истекла/;
 const issues=[];
 if(!reason.test(text))issues.push('canonical terminal reason absent');
 if(/Требуется подтверждение|Трейдер запросил|Проверяем ваш платёж|Заявка НЕ отменена|Обычно до 30 минут/.test(text))issues.push('verification or receipt masks terminal outcome');
 if(/class="(?:cp|qr|reqs)|Перейти к оплате|К оплате|Переведите ровно/.test(html))issues.push('payment control survives');
 if(/Отправляем|Оплата получена|Выполнено|возвращены|возврат выполнен/.test(text))issues.push('unsupported money promotion');
 if(status!==expected)issues.push('canonical state mutated');
 if(!/не (?:переводите|платите)|Повторно не|повторно не/.test(text))issues.push('no no-repeat guidance');
 if(!html.includes('https://t.me/Obsidian666999bot'))issues.push('fixed support route absent');
 const receipt=vm.runInContext('C.receipt',c);
 if(receipt && !/[Чч]ек|[Фф]айл/.test(text))issues.push('receipt fact hidden');
 if(receipt==='stored' && /Чек передан|передан на проверку/.test(text))issues.push('stored promoted to sent receipt');
 results.push({name,status,issues});
}
(async()=>{
 for(const status of ['expired','failed','cancelled'])
 for(const receipt of ['','stored','sent'])
 for(const verification of ['','pdf','video'])
 for(const dead of [false,true])
 for(const localExpired of [false,true]){
   configure({status,receipt,verification,dead,localExpired});
   inspect([status,receipt||'absent',verification||'none',dead,localExpired].join(':'),status);
 }
 for(const status of ['paid','sent'])for(const receipt of ['','stored','sent']){
   configure({status,receipt,verification:'video',dead:true,localExpired:true});
   const html=view.innerHTML;const wanted=status==='paid'?'Оплата получена':'отправлена';
   results.push({name:'precedence:'+status+':'+receipt,status,issues:
     html.includes(wanted)&&!html.includes('Трейдер запросил')?[]:['paid/sent precedence changed']});
 }
 for(const status of ['expired','failed','cancelled']){
   configure({status:'pending',receipt:'',verification:'',dead:false,localExpired:false});
   response={status,receipt:'stored',verification:'video',dead:true,tx_url:'',txid:''};
   const before=calls.length;await vm.runInContext('poll()',c);inspect('poll:'+status,status);
   await vm.runInContext('poll()',c);
   results.push({name:'terminal-poll-stops:'+status,status,issues:calls.length===before+1?[]:['terminal polling continues']});
 }
 for(const status of ['expired','failed','cancelled']){
   configure({status,receipt:'future-unknown',verification:'<script>hostile</script>',dead:true,localExpired:true});
   const html=view.innerHTML;
   results.push({name:'unknown-receipt:'+status,status,issues:
     /terminal-receipt|[Чч]ек|[Фф]айл|hostile|data-value=/.test(html)?['unknown metadata fabricated receipt or masked terminal']:[]});
 }
 configure({status:'pending',receipt:'',verification:'',dead:false,localExpired:false});
 results.push({name:'pending-retains-instructions',status:'pending',issues:view.innerHTML.includes('data-value=')?[]:['active control changed']});
 process.stdout.write(JSON.stringify({results,calls,activeHtml,injected:c.__securityInjected||null}));
})().catch(e=>{process.stderr.write(e.stack);process.exitCode=1});
'''
out=json.loads(subprocess.run(['node','-e',js],input=json.dumps({'script':script}),
                            text=True,capture_output=True,check=True).stdout)
active=Tags();active.feed(out['activeHtml'])
button=next(attrs for tag,attrs in active.tags if tag=='button' and 'data-value' in attrs)
assert button['onclick']=='cp(this.dataset.value,this)' and button['data-value']==detail
assert 'data-extra' not in button and out['injected'] is None
assert all(call[0].startswith('/api/order/101?token=') and len(call)==1 for call in out['calls'])

# Numeric fallback is the explicitly added companion scope: canonical reason
# must survive stored/sent/unknown receipt metadata there too. Stub proof only;
# authority and read call ASTs are independently protected below.
from core import order_access
order_access.verify=lambda *args,**kwargs:7
numeric_order={}
namespace['_payment_status_reads'].authorized_snapshot=lambda *args,**kwargs:numeric_order
namespace['_payment_status_reads'].latest_active_for_authorized_order=lambda *args,**kwargs:None
for status in ['expired','failed','cancelled']:
    for receipt in ['', 'stored', 'sent', 'future-unknown']:
        numeric_order.update(order_id=101,rub_amount=1500,status=status)
        namespace['_receipt_state']=lambda *args,**kwargs:receipt
        numeric_page=asyncio.run(namespace['pay']('101',SimpleNamespace(
            client=SimpleNamespace(host='synthetic-local'),query_params={'proof':'synthetic-stub'})))
        numeric_tags=Tags();numeric_tags.feed(numeric_page)
        title={'expired':'Заявка истекла','failed':'Заявка не выполнена','cancelled':'Заявка отменена'}[status]
        body=re.sub('<[^>]+>',' ',numeric_page.split('<body>',1)[1])
        issues=[]
        if '<h1>'+title+'</h1>' not in numeric_page:issues.append('canonical numeric reason absent')
        if 'Повторно не переводите' not in body and 'повторно не переводите' not in body:issues.append('numeric no-repeat guidance absent')
        if receipt in ('stored','sent') and not re.search('[Чч]ек|[Фф]айл',body):issues.append('numeric receipt fact missing')
        if receipt=='future-unknown' and re.search('[Чч]ек|[Фф]айл',body):issues.append('numeric unknown receipt fabricated')
        if any(tag in ('script','button','img') for tag,_ in numeric_tags.tags):issues.append('numeric payment/script controls present')
        if 'https://t.me/Obsidian666999bot' not in numeric_page:issues.append('numeric support absent')
        if numeric_order['status']!=status:issues.append('numeric source status mutated')
        out['results'].append({'name':'numeric:'+status+':'+(receipt or 'absent'),'status':status,'issues':issues})

# Permit only opaque HTML plus the numeric state/copy presentation block.
# Protect every other Python statement, including all authorization/read calls,
# numeric HTML structure, JSON escaping and every function outside pay.
def excluding_terminal_presentation(text):
    tree=ast.parse(text)
    pay=next(n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='pay')
    assigns=sorted([n for n in ast.walk(pay) if isinstance(n,ast.Assign)
                    and any(isinstance(t,ast.Name) and t.id=='html' for t in n.targets)
                    and isinstance(n.value,ast.JoinedStr)],key=lambda n:n.lineno)
    assert len(assigns)==2
    assigns[1].value=ast.Constant(value='opaque HTML reviewed separately')
    numeric=next(n for n in pay.body if isinstance(n,ast.If) and ast.unparse(n.test)=='token.isascii() and token.isdigit()')
    start=next(i for i,n in enumerate(numeric.body) if isinstance(n,ast.If) and ast.unparse(n.test)=="_rcpt == 'sent'")
    end=next(i for i,n in enumerate(numeric.body) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='html' for t in n.targets))
    block=numeric.body[start:end]
    for statement in block:
        for item in ast.walk(statement):
            if isinstance(item,ast.Call):
                assert isinstance(item.func,ast.Attribute) and item.func.attr in {'get','strip'}
                assert isinstance(item.func.value,(ast.Dict,ast.JoinedStr)) or isinstance(item.func.value,ast.Name) and item.func.value.id=='_titles'
            if isinstance(item,ast.Name) and isinstance(item.ctx,ast.Store):
                assert item.id in {'o_status','_titles','_t','_d','receipt_note','repeat_advice'}
            assert not isinstance(item,(ast.Import,ast.ImportFrom,ast.Await,ast.Raise))
    numeric.body[start:end]=[ast.Expr(value=ast.Constant(value='bounded numeric terminal presentation'))]
    return ast.dump(tree,include_attributes=False)
assert excluding_terminal_presentation(source)==excluding_terminal_presentation(baseline)
unchanged=['relay/repositories/payment_status_read_store.py','relay/core/order_access.py','relay/webapp.html']
for path in unchanged:
    previous=subprocess.run(['git','show',BASE+':'+path],cwd=ROOT,capture_output=True,check=True).stdout
    assert hashlib.sha256(previous).hexdigest()==hashlib.sha256((ROOT/path).read_bytes()).hexdigest(),path
failures=[row for row in out['results'] if row['issues']]
if baseline_mode:assert failures,'baseline defect was not reproduced'
else:assert not failures,json.dumps(failures[:4],ensure_ascii=False)
paths=[Path(__file__),MAIN,ROOT/'relay/core/requisites.py',ROOT/'relay/services/requisite_origin.py',ROOT/'relay/core/txid.py']
if baseline_mode:paths.remove(MAIN)
report={'schemaVersion':'e4-payment-terminal-independent-security-probe.v1',
 'result':'EXPECTED_BASELINE_FAILURE' if baseline_mode else 'PASS','baselineHead':BASE,
 'inputs':[{'path':str(p.relative_to(ROOT)),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in paths],
 'executedSourceSha256':hashlib.sha256(source.encode()).hexdigest(),
 'cases':len(out['results']),'passingCases':len(out['results'])-len(failures),
 'failingCases':len(failures),'failures':failures,'securityChecks':{
 'scriptBreakoutBlocked':True,'copyHandlerUsesLiteralData':True,
 'hostileProviderPayloadExecuted':False,'onlyStatusGetRequests':True,
 'pythonAuthReadsSerializationAndOtherFunctionsASTUnchanged':True,
 'numericChangesLimitedToPureStatusCopyPresentation':True,'adapterProofAndMiniAppBytesUnchanged':True},
 'scope':'Exact AST-isolated pay page with synthetic provider payload; actual inline JavaScript in Node VM; terminal/receipt/verification/dead/timer permutations and poll transitions.',
 'productionReadsWritesNetworkRestarts':False,
 'limits':['No database/provider/live HTTP/real credentials are used. Browser layout is covered by the separate acceptance reviewer.']}
print(json.dumps(report,ensure_ascii=False,indent=2))
