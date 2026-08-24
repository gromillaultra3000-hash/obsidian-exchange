import hashlib,importlib.util,json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
P=json.loads((ROOT/'docs/e0-3-bot-dca-capabilities.v1.json').read_text())
spec=importlib.util.spec_from_file_location('matrix',ROOT/'scripts/e0_bot_method_capability_matrix.py')
M=importlib.util.module_from_spec(spec);spec.loader.exec_module(M)

def test_dca_package_covers_every_reachable_method_and_source():
 expected={x['id'] for x in M.build()['methods'] if x['repository']=='dca_store'}
 actual={x['id'] for x in P['capabilities']}
 assert actual==expected and len(actual)==3
 assert hashlib.sha256((ROOT/'relay/repositories/dca_store.py').read_bytes()).hexdigest()==P['sourceSha256']
 assert P['status']=='EXACT_PACKAGE' and P['productionAuthorization'] is False

def test_dca_columns_and_money_transition_are_closed():
 allowed={'dca_schedules','orders'}
 for item in P['capabilities']:
  assert item['access'] in {'READ','WRITE','MONEY_WRITE'} and item['reads'] and item['invariants']
  assert set(item['reads'])<=allowed and set(item.get('mutations',{}))<=allowed
  for columns in list(item['reads'].values())+list(item.get('mutations',{}).values()):
   assert columns and len(columns)==len(set(columns))
   assert not ({'*','ALL','UNKNOWN','TBD'}&set(columns))
 run=next(x for x in P['capabilities'] if x['id']=='dca_store.run_due')
 assert {'EXACT_SCHEDULE_AND_EXPECTED_NEXT_RUN_CAS','ORDER_AND_SCHEDULE_ADVANCE_ONE_TRANSACTION','ADVANCE_FAILURE_ROLLS_BACK_ORDER'}<=set(run['invariants'])
 cancel=next(x for x in P['capabilities'] if x['id']=='dca_store.cancel')
 assert {'OPTIONAL_USER_OWNER_SCOPE','UNSCOPED_FORM_OPERATOR_ONLY'}<=set(cancel['invariants'])
 assert P['grantPolicy']['unscopedCancelOperatorOnly'] is True
