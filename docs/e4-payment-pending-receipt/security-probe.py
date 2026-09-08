#!/usr/bin/env python3
"""Independent pending receipt evidence probe. Synthetic data, no application I/O."""
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

ROOT=Path('/root')
BASE='b848d6f429f5b4f79478b41849c70a73d793ce1b'
MAIN=ROOT/'relay-fastapi/main.py'
old=subprocess.run(['git','show',BASE+':relay-fastapi/main.py'],cwd=ROOT,capture_output=True,text=True,check=True).stdout
baseline='--baseline' in sys.argv
source=old if baseline else MAIN.read_text()
sys.path.insert(0,str(ROOT/'relay'))
node=next(n for n in ast.parse(source).body if isinstance(n,ast.AsyncFunctionDef) and n.name=='pay')
node.decorator_list=[]
class HTTPError(Exception):
    def __init__(self,status_code,detail=None):self.status_code=status_code
class Tags(HTMLParser):
    def __init__(self):super().__init__();self.tags=[]
    def handle_starttag(self,tag,attrs):self.tags.append((tag,dict(attrs)))
detail="7');globalThis.__securityInjected=2;//\" data-extra=\"oops"
payload='Synthetic </script><script>globalThis.__securityInjected=1</script>'
order={'order_id':101,'rub_amount':1500,'status':'pending','paid_btc_tx':'',
       'currency':'TON','network':'TON','verification_requested':''}
receipt='';dead=False
reader=SimpleNamespace(get_by_token=lambda token:{'order_id':101,'amount':1500,
    'provider_payload':repr({'requisites':{'bank_name':payload,'phone':detail}}),
    'expires_at':'','qr_payload':'','status':'invoice_created'},
    authorized_snapshot=lambda *args,**kwargs:dict(order),
    latest_active_for_authorized_order=lambda *args,**kwargs:None)
context={'Request':object,'HTTPException':HTTPError,'_payment_status_reads':reader,
 '_receipt_state':lambda *args,**kwargs:receipt,'_session_dead':lambda *args,**kwargs:dead,
 '_payout_delayed':lambda *args,**kwargs:False,'audit_log':lambda *args:None,
 'logger':SimpleNamespace(error=lambda *args:None)}
exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),str(MAIN),'exec'),context)
def page(token):
    return asyncio.run(context['pay'](token,SimpleNamespace(query_params={'proof':'synthetic-stub'},
        client=SimpleNamespace(host='synthetic-local'))))
html=page('synthetic-pending-receipt')
tags=Tags();tags.feed(html)
assert sum(tag=='script' for tag,_ in tags.tags)==1
script=html.split('<script>',1)[1].split('</script>',1)[0]
assert '\\u003c/script\\u003e' in script

js=r'''
const fs=require('node:fs'),vm=require('node:vm');const source=JSON.parse(fs.readFileSync(0,'utf8'));
const view={innerHTML:''},calls=[];let response=null;
const c={document:{getElementById:()=>view},setInterval:()=>0,clearInterval:()=>{},setTimeout:()=>0,
 fetch:async(...args)=>{calls.push(args);return {ok:true,json:async()=>response}}};
vm.createContext(c);vm.runInContext(source,c);const initial=view.innerHTML;const cases=[];
const received=/[Фф]айл(?: чека)? (?:получен|сохранён)|[Вв]аш файл у нас|[Чч]ек (?:получен|у нас)/;
const hasControls=html=>/class="(?:cp|qr|reqs)|Перейти к оплате|К оплате/.test(html);
function set(values){c.values=values;vm.runInContext('Object.assign(C,values);_localExpired=!!values.localExpired;render()',c);}
function examine(name,values){const html=view.innerHTML,text=html.replace(/<[^>]*>/g,' '),issues=[];
 const status=vm.runInContext('C.status',c);
 if(status!==values.status)issues.push('canonical state mutated');
 if(values.status==='pending'){
   if(values.receipt==='stored'&&values.dead){
     if(!received.test(text))issues.push('stored receipt evidence hidden');
     if(!/не передан|передача[^.]*не подтвержд|проверки[^.]*не подтвержд/.test(text))issues.push('stored versus delivered distinction absent');
     if(/Проверяем ваш платёж|занимается сотрудник|Разбираем вручную|Обычно до|уйдёт на ваш адрес|Оплата получена/.test(text))issues.push('unproved payment review or payout promise');
     if(!/[Пп]овторно не|не[^.]*повторно/.test(text))issues.push('no-repeat guidance absent');
     if(!html.includes('https://t.me/Obsidian666999bot'))issues.push('fixed support route absent');
   }
   if(values.receipt==='future-unknown'&&received.test(text))issues.push('unknown receipt fabricated received-file evidence');
   if(values.dead&&hasControls(html))issues.push('unavailable requisites retain payment controls');
   if(values.verification){
     const instruction=values.verification==='video'?'Трейдер запросил видео':'Трейдер запросил PDF-чек';
     if(!text.includes(instruction))issues.push('verification instructions masked');
   }
   if(values.receipt==='sent'&&!values.verification&&!/[Чч]ек получен/.test(text))issues.push('sent receipt precedence lost');
 }
 if(['expired','failed','cancelled'].includes(values.status)){
   const reason=values.status==='failed'?/Заявка не выполнена/:values.status==='cancelled'?/Заявка отменена/:/Срок оплаты заявки истёк/;
   if(!reason.test(text)||/Требуется подтверждение/.test(text))issues.push('canonical terminal reason masked');
   if(hasControls(html))issues.push('terminal payment controls');
 }
 if(values.status==='paid'&&!text.includes('Оплата получена'))issues.push('paid precedence lost');
 if(values.status==='sent'&&!text.includes('отправлена'))issues.push('sent precedence lost');
 cases.push({name,issues});
}
(async()=>{
 for(const receipt of ['','stored','sent','future-unknown'])
 for(const verification of ['','pdf','video'])for(const dead of [false,true])for(const localExpired of [false,true]){
   const values={status:'pending',receipt,verification,dead,localExpired};set(values);
   examine(['pending',receipt||'absent',verification||'none',dead,localExpired].join(':'),values);
 }
 for(const status of ['expired','failed','cancelled','paid','sent'])
 for(const receipt of ['','stored','sent'])for(const verification of ['','pdf','video']){
   const values={status,receipt,verification,dead:true,localExpired:true};set(values);examine('precedence:'+status+':'+receipt+':'+verification,values);
 }
 for(const values of [
  {status:'pending',receipt:'stored',verification:'',dead:true},
  {status:'pending',receipt:'stored',verification:'video',dead:true},
  {status:'pending',receipt:'sent',verification:'',dead:true},
  {status:'paid',receipt:'stored',verification:'video',dead:true},
  {status:'cancelled',receipt:'stored',verification:'pdf',dead:true}]){
   set({status:'pending',receipt:'',verification:'',dead:false,localExpired:false});
   response={...values,txid:'',tx_url:''};await vm.runInContext('poll()',c);examine('poll:'+values.status+':'+values.receipt+':'+values.verification,values);
 }
 process.stdout.write(JSON.stringify({cases,initial,calls,injected:c.__securityInjected||null}));
})().catch(e=>{process.stderr.write(e.stack);process.exitCode=1});
'''
out=json.loads(subprocess.run(['node','-e',js],input=json.dumps(script),capture_output=True,text=True,check=True).stdout)
tags=Tags();tags.feed(out['initial'])
button=next(attrs for tag,attrs in tags.tags if tag=='button' and 'data-value' in attrs)
assert button['data-value']==detail and button['onclick']=='cp(this.dataset.value,this)' and 'data-extra' not in button
assert out['injected'] is None
assert all(len(call)==1 and call[0].startswith('/api/order/101?token=') for call in out['calls'])

from core import order_access
order_access.verify=lambda *args,**kwargs:7
for receipt in ['', 'stored', 'sent', 'future-unknown']:
    for verification in ['', 'pdf', 'video']:
        for dead in [False,True]:
            order['verification_requested']=verification
            rendered=page('101');body=re.sub('<[^>]+>',' ',rendered.split('<body>',1)[1]);issues=[]
            received=bool(re.search('[Фф]айл(?: чека)? (?:получен|сохранён)|[Вв]аш файл у нас|[Чч]ек (?:получен|у нас)',body))
            if receipt=='stored' and dead:
                if not received:issues.append('numeric stored receipt evidence hidden')
                if not re.search('не передан|передача[^.]*не подтвержд|проверки[^.]*не подтвержд',body):issues.append('numeric stored distinction absent')
                if re.search('проверяем|занимается сотрудник|Разбираем вручную|Обычно до|уйдёт на ваш адрес|Оплата получена',body):issues.append('numeric unproved promise')
                if not re.search('[Пп]овторно не|не[^.]*повторно',body):issues.append('numeric no-repeat absent')
            if receipt=='future-unknown' and received:issues.append('numeric unknown receipt fabricated')
            if 'https://t.me/Obsidian666999bot' not in rendered:issues.append('numeric support absent')
            parsed=Tags();parsed.feed(rendered)
            if any(tag in ('button','script','img') for tag,_ in parsed.tags):issues.append('numeric payment controls')
            out['cases'].append({'name':'numeric:pending:'+receipt+':'+verification+':'+str(dead),'issues':issues})

# Only opaque inline HTML and the existing numeric presentation block may
# change. Authorization/read/redirect/serialization and numeric HTML stay exact.
def normalized(text):
    tree=ast.parse(text)
    pay=next(n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='pay')
    htmls=sorted([n for n in ast.walk(pay) if isinstance(n,ast.Assign) and isinstance(n.value,ast.JoinedStr)
                 and any(isinstance(t,ast.Name) and t.id=='html' for t in n.targets)],key=lambda n:n.lineno)
    assert len(htmls)==2
    htmls[1].value=ast.Constant(value='opaque presentation')
    numeric=next(n for n in pay.body if isinstance(n,ast.If) and ast.unparse(n.test)=='token.isascii() and token.isdigit()')
    first=next(i for i,n in enumerate(numeric.body) if isinstance(n,ast.If) and ast.unparse(n.test)=="_rcpt == 'sent'")
    last=next(i for i,n in enumerate(numeric.body) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='html' for t in n.targets))
    for statement in numeric.body[first:last]:
        for item in ast.walk(statement):
            if isinstance(item,ast.Call):
                assert isinstance(item.func,ast.Attribute) and item.func.attr in {'get','strip'}
                assert isinstance(item.func.value,(ast.Dict,ast.JoinedStr)) or isinstance(item.func.value,ast.Name) and item.func.value.id=='_titles'
            if isinstance(item,ast.Name) and isinstance(item.ctx,ast.Store):
                assert item.id in {'o_status','_titles','_t','_d','receipt_note','repeat_advice'}
            assert not isinstance(item,(ast.Import,ast.ImportFrom,ast.Await,ast.Raise))
    numeric.body[first:last]=[ast.Expr(value=ast.Constant(value='pure numeric presentation'))]
    return ast.dump(tree,include_attributes=False)
assert normalized(source)==normalized(old)
for path in ['relay/repositories/payment_status_read_store.py','relay/core/order_access.py','relay/webapp.html']:
    data=subprocess.run(['git','show',BASE+':'+path],cwd=ROOT,capture_output=True,check=True).stdout
    assert hashlib.sha256(data).hexdigest()==hashlib.sha256((ROOT/path).read_bytes()).hexdigest()
failures=[r for r in out['cases'] if r['issues']]
if baseline:assert failures
else:assert not failures,json.dumps(failures[:8],ensure_ascii=False)
paths=[Path(__file__),ROOT/'relay/core/requisites.py',ROOT/'relay/services/requisite_origin.py',ROOT/'relay/core/txid.py',ROOT/'relay/core/order_access.py']
if not baseline:paths.append(MAIN)
print(json.dumps({'schemaVersion':'e4-pending-receipt-independent-security-probe.v1',
 'result':'EXPECTED_BASELINE_FAILURE' if baseline else 'PASS','baselineHead':BASE,
 'inputs':[{'path':str(p.relative_to(ROOT)),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in paths],
 'executedSourceSha256':hashlib.sha256(source.encode()).hexdigest(),
 'cases':len(out['cases']),'passingCases':len(out['cases'])-len(failures),'failingCases':len(failures),
 'failures':failures,'securityChecks':{'scriptJSONEscapingPreserved':True,
 'copyUsesQuotedLiteralDataAndConstantHandler':True,'injectedCodeExecuted':False,
 'pollsOnlyStatusGET':True,'authReadRedirectSerializationAndOtherFunctionsASTUnchanged':True,
 'numericPresentationPureLocalOperationsOnly':True,'adapterProofMiniAppBytesUnchanged':True},
 'scope':'Exact AST-isolated pay page with synthetic provider data, actual inline JavaScript in Node VM, numeric proof replaced by an inert verifier. No application import, database, provider, host credentials, production request or service operation.',
 'productionReadsWritesNetworkRestarts':False},ensure_ascii=False,indent=2))
