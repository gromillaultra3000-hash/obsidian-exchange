import hashlib,importlib.util,json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
P=json.loads((ROOT/'docs/e0-3-bot-admin-config-capabilities.v1.json').read_text())
spec=importlib.util.spec_from_file_location('matrix',ROOT/'scripts/e0_bot_method_capability_matrix.py')
M=importlib.util.module_from_spec(spec);spec.loader.exec_module(M)

def test_admin_package_covers_every_reachable_method_and_binds_source():
 expected={x['id'] for x in M.build()['methods'] if x['repository']=='admin_config_store'}
 actual={x['id'] for x in P['capabilities']}
 assert actual==expected and len(actual)==11
 source=ROOT/'relay/repositories/admin_config_store.py'
 assert hashlib.sha256(source.read_bytes()).hexdigest()==P['sourceSha256']
 assert P['status']=='EXACT_PACKAGE' and P['productionAuthorization'] is False

def test_admin_columns_relations_and_dynamic_allowlist_are_closed():
 allowed={'operators','workers','blocked_addresses','blocked_users','reserves'}
 assert set(P['dynamicRelationAllowlist'].values())=={'operators','workers'}
 for item in P['capabilities']:
  assert item['access'] in {'READ','WRITE'} and item['reads'] and item['invariants']
  assert set(item['reads'])<=allowed
  if item['access']=='WRITE':
   assert item['mutations'] and set(item['mutations'])<=allowed
  for columns in list(item['reads'].values())+list(item.get('mutations',{}).values()):
   assert columns and len(columns)==len(set(columns))
   assert not ({'*','ALL','UNKNOWN','TBD'}&set(columns))
 assert P['grantPolicy']=={
  'tableWideAccess':False,'functionPerMethodRequired':True,'dynamicRelationsClosed':True}
