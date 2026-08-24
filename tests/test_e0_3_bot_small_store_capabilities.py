import hashlib,importlib.util,json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
P=json.loads((ROOT/'docs/e0-3-bot-small-store-capabilities.v1.json').read_text())
spec=importlib.util.spec_from_file_location('matrix',ROOT/'scripts/e0_bot_method_capability_matrix.py')
M=importlib.util.module_from_spec(spec);spec.loader.exec_module(M)
REPOS={'swap_store','status_notification_store','user_profile_store'}

def test_small_packages_cover_all_reachable_methods_and_sources():
 relay={x['id'] for name in ('reads','writers') for x in json.loads(
  (ROOT/f'docs/e0-3-relay-{name[:-1]}-matrix.v1.json').read_text())[name]}
 expected={x['id'] for x in M.build()['methods'] if x['repository'] in REPOS and x['id'] not in relay}
 actual={x['id'] for x in P['capabilities']}
 assert actual==expected and len(actual)==5
 for repo,digest in P['sourceSha256'].items():
  assert hashlib.sha256((ROOT/f'relay/repositories/{repo}.py').read_bytes()).hexdigest()==digest
 assert 'CREATE TABLE' not in (ROOT/'relay/repositories/status_notification_store.py').read_text()

def test_columns_invariants_and_boundedness_debt_are_explicit():
 for item in P['capabilities']:
  assert item['reads'] and item['invariants']
  for columns in list(item['reads'].values())+list(item.get('mutations',{}).values()):
   assert columns and len(columns)==len(set(columns))
   assert not ({'*','ALL','UNKNOWN','TBD'}&set(columns))
 debt={v for x in P['capabilities'] for v in x['invariants'] if v.endswith('REMEDIATION_REQUIRED')}
 assert debt==set()
 by={x['id']:set(x['invariants']) for x in P['capabilities']}
 assert {'STATUS_LIST_MAXIMUM_32','RESULT_MAXIMUM_500'}<=by['swap_store.unfinished']
 assert {'HOURS_MAXIMUM_168','LIMIT_MAXIMUM_100'}<=by['status_notification_store.payout_candidates']
 assert P['status']=='EXACT_PACKAGES_VERIFIED' and P['blockers']==[]
