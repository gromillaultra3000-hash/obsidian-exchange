import ast
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"relay"))
source=(ROOT/"relay-fastapi/main.py").read_text()
tree=ast.parse(source)
nodes=[node for node in tree.body if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef))
       and node.name in {"_dispatch_lifecycle_work","handle_dead_session","cleanup_expired_orders"}]
module=ast.Module(body=nodes,type_ignores=[]);ast.fix_missing_locations(module)

class Log:
 def __getattr__(self,name):return lambda *a,**k:None
class Store:
 def __init__(self,jobs):self.jobs=list(jobs);self.completed=[];self.retried=[]
 def claim_work(self,kind=None):
  for i,item in enumerate(self.jobs):
   if kind is None or item['kind']==kind:return self.jobs.pop(i)
  return None
 def complete_work(self,ident):self.completed.append(ident);return True
 def retry_work(self,ident):self.retried.append(ident);return True
 def fail_session(self,*args,**kwargs):return {'action':'failed','claimed':True}

sent=[];admins=[];audits=[]
expired={'id':1,'kind':'order_expired_notify','order_id':41,'user_id':7,'rub_amount':2500.0,'currency':'BTC'}
customer={'id':2,'kind':'session_dead_customer','order_id':42,'user_id':8,'rub_amount':1000.0,
          'currency':'BTC','has_receipt':True,'provider':'vertu','detail':'declined'}
admin={**customer,'id':3,'kind':'session_dead_admin'}
store=Store([expired,customer,admin])
env={'_order_lifecycle':store,'notify_telegram':lambda uid,text,reply_markup=None:sent.append((uid,text,reply_markup)) or True,
     'notify_admins_tg':lambda text:admins.append(text),'audit_log':lambda *a:audits.append(a),
     'logger':Log(),'asyncio':__import__('asyncio')}
exec(compile(module,'main.py','exec'),env)
assert env['_dispatch_lifecycle_work'](kind='order_expired_notify')==1
assert sent[0][1]==("⌛ <b>Заявка #41 истекла</b>\n\n2500 ₽ → BTC. Курс больше не действует — "
                    "средства по старым реквизитам не переводите.\nСоздайте новую заявку, это займёт минуту.")
env['handle_dead_session'](42,'token','vertu','declined')
assert "Чек от клиента: <b>ЕСТЬ</b>" in admins[0]
assert sent[1][1]==("🔍 <b>Заявка #42 — разбираем вручную</b>\n\n"
                    "Платёжная сессия закрылась на стороне партнёра, а ваш чек у нас. "
                    "Заявкой уже занимается сотрудник.\n\n"
                    "<b>Повторно не переводите и новую заявку не создавайте.</b> "
                    "Мы напишем сюда, как только будет решение.")
assert store.completed==[1,3,2]

# A failed/uncertain Telegram call stays claimed and is not auto-retried.
store=Store([{**expired,'id':9}]);env['_order_lifecycle']=store
env['notify_telegram']=lambda *a,**k:False
assert env['_dispatch_lifecycle_work'](kind='order_expired_notify')==0
assert store.completed==[] and store.retried==[]

cleanup=ast.get_source_segment(source,next(n for n in nodes if n.name=='cleanup_expired_orders'))
dead=ast.get_source_segment(source,next(n for n in nodes if n.name=='handle_dead_session'))
assert "_order_lifecycle.expire_due(" in cleanup and "_order_lifecycle.fail_session(" in dead
for forbidden in ("CREATE TABLE","datetime('now', '-15 minutes')","c.execute","db_conn("):
 assert forbidden not in cleanup+dead,forbidden
print('Order lifecycle FastAPI integration checks: OK')
