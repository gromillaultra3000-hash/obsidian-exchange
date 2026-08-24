import hashlib,importlib.util,json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
P=json.loads((ROOT/'docs/e0-3-bot-order-capabilities.v1.json').read_text())
spec=importlib.util.spec_from_file_location('matrix',ROOT/'scripts/e0_bot_method_capability_matrix.py')
M=importlib.util.module_from_spec(spec);spec.loader.exec_module(M)

def test_bot_order_package_covers_every_reachable_method_and_source():
 expected={x['id'] for x in M.build()['methods'] if x['repository']=='bot_order_store'}
 actual={x['id'] for x in P['capabilities']}
 assert actual==expected and len(actual)==3
 assert hashlib.sha256((ROOT/'relay/repositories/bot_order_store.py').read_bytes()).hexdigest()==P['sourceSha256']
 assert P['status']=='EXACT_PACKAGE' and P['productionAuthorization'] is False

def test_bot_order_columns_and_money_invariants_are_closed():
 allowed={'orders','rate_locks','promo_codes','promo_uses'}
 for item in P['capabilities']:
  assert item['access'] in {'READ','WRITE','MONEY_WRITE'} and item['reads'] and item['invariants']
  assert set(item['reads'])<=allowed and set(item.get('mutations',{}))<=allowed
  for columns in list(item['reads'].values())+list(item.get('mutations',{}).values()):
   assert columns and len(columns)==len(set(columns))
   assert not ({'*','ALL','UNKNOWN','TBD'}&set(columns))
 create=next(x for x in P['capabilities'] if x['id']=='bot_order_store.create_order')
 assert create['access']=='MONEY_WRITE'
 assert {'LOCK_UNUSED_AND_NOT_EXPIRED_CAS','PROMO_ACTIVE_NOT_EXPIRED_CAPACITY_CAS','ORDER_LOCK_PROMO_ONE_TRANSACTION'}<=set(create['invariants'])
 assert P['grantPolicy']=={'tableWideAccess':False,'functionPerMethodRequired':True,'directSequenceAccess':False,'moneyWriterIsolated':True}
