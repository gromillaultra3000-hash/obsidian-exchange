import ast,asyncio,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'relay'))
source=(ROOT/'relay-fastapi/main.py').read_text();tree=ast.parse(source)
names={'_dispatch_sell_settlement_notification','_vertu_payout_settle'}
nodes=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name in names]
module=ast.Module(body=nodes,type_ignores=[]);ast.fix_missing_locations(module)
class Log:
 def __getattr__(self,n):return lambda *a,**k:None
class Settlement:
 def __init__(self):self.items=[];self.sent=[];self.calls=[]
 def settle_vertu(self,sid,*,payout_ref):self.calls.append((sid,payout_ref));return {'action':'settled','rub_amount':2500.0}
 def claim_notification(self):return self.items.pop(0) if self.items else None
 def mark_notification_sent(self,i):self.sent.append(i);return True
class SP:
 @staticmethod
 def refresh_status(sid):return {'status':'paid'}
 @staticmethod
 def is_settled(status):return status=='paid'
 @staticmethod
 def is_rejected(status):return False
settlement=Settlement();settlement.items=[{'id':4,'sell_id':17,'recipient_id':7,'rub_amount':2500.0}]
messages=[];audits=[]
env={'_sell_settlement':settlement,'notify_telegram':lambda uid,text:messages.append((uid,text)) or True,
     'audit_log':lambda *a:audits.append(a),'logger':Log(),'asyncio':asyncio}
exec(compile(module,'main.py','exec'),env)
# Replace the imported core facade used by the function with a tiny module.
import types
core=__import__('core');old=getattr(core,'sell_payout',None);core.sell_payout=SP
try:asyncio.run(env['_vertu_payout_settle'](17,7,2500,'v-17','pending'))
finally:
 if old is not None:core.sell_payout=old
assert settlement.calls==[(17,'v-17')] and settlement.sent==[4]
assert messages==[(7,"✅ <b>Заявка #17 выполнена!</b>\n💰 2,500.00 RUB зачислены — банк подтвердил перевод.")]
assert audits[-1]==('vertu_payout_settled','sell=17 ref=v-17 2500.0')
# Uncertain send remains `sending`: dispatcher neither marks nor blindly retries.
settlement.items=[{'id':5,'sell_id':18,'recipient_id':8,'rub_amount':1000.0}]
env['notify_telegram']=lambda *a:False
assert not env['_dispatch_sell_settlement_notification']() and settlement.sent==[4]
body=ast.get_source_segment(source,next(n for n in nodes if n.name=='_vertu_payout_settle'))
assert '_sell_settlement.settle_vertu(' in body
for forbidden in ('INSERT INTO user_vip_volume','_sp.mark_settled('):assert forbidden not in body
print('Sell settlement FastAPI integration checks: OK')
