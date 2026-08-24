import hashlib,importlib.util,json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
P=json.loads((ROOT/'docs/e0-3-bot-limit-order-capabilities.v1.json').read_text())
spec=importlib.util.spec_from_file_location('matrix',ROOT/'scripts/e0_bot_method_capability_matrix.py')
M=importlib.util.module_from_spec(spec);spec.loader.exec_module(M)

def test_limit_order_package_covers_every_reachable_method_and_source():
 expected={x['id'] for x in M.build()['methods'] if x['repository']=='limit_order_store'}
 actual={x['id'] for x in P['capabilities']}
 assert actual==expected and len(actual)==4
 assert hashlib.sha256((ROOT/'relay/repositories/limit_order_store.py').read_bytes()).hexdigest()==P['sourceSha256']
 assert P['status']=='EXACT_PACKAGE' and P['productionAuthorization'] is False

def test_limit_order_columns_and_single_winner_trigger_are_closed():
 allowed={'limit_orders','orders'}
 for item in P['capabilities']:
  assert item['access'] in {'READ','WRITE','MONEY_WRITE'} and item['reads'] and item['invariants']
  assert set(item['reads'])<=allowed and set(item.get('mutations',{}))<=allowed
  for columns in list(item['reads'].values())+list(item.get('mutations',{}).values()):
   assert columns and len(columns)==len(set(columns))
   assert not ({'*','ALL','UNKNOWN','TBD'}&set(columns))
 by_id={x['id']:set(x['invariants']) for x in P['capabilities']}
 assert {'SINGLE_WINNER','ORDER_AND_TRIGGER_ONE_TRANSACTION','TRIGGER_FAILURE_ROLLS_BACK_ORDER'}<=by_id['limit_order_store.trigger']
 assert {'OPTIONAL_USER_OWNER_SCOPE','UNSCOPED_FORM_OPERATOR_ONLY'}<=by_id['limit_order_store.cancel']
 assert {'BULK_ALL_DUE_ROWS'}<=by_id['limit_order_store.expire']
