import hashlib,importlib.util,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];P=json.loads((ROOT/'docs/e0-3-bot-support-capabilities.v1.json').read_text())
spec=importlib.util.spec_from_file_location('matrix',ROOT/'scripts/e0_bot_method_capability_matrix.py');M=importlib.util.module_from_spec(spec);spec.loader.exec_module(M)
def test_support_package_covers_remaining_reachable_methods_and_source():
 relay={x['id'] for name in ('reads','writers') for x in json.loads((ROOT/f'docs/e0-3-relay-{name[:-1]}-matrix.v1.json').read_text())[name]}
 expected={x['id'] for x in M.build()['methods'] if x['repository']=='support_store' and x['id'] not in relay}
 assert {x['id'] for x in P['capabilities']}==expected and len(expected)==7
 assert hashlib.sha256((ROOT/'relay/repositories/support_store.py').read_bytes()).hexdigest()==P['sourceSha256']
def test_support_owner_scopes_columns_and_debt_are_explicit():
 for item in P['capabilities']:
  assert item['reads'] and item['invariants']
  for cols in list(item['reads'].values())+list(item.get('mutations',{}).values()):assert cols and len(cols)==len(set(cols)) and '*' not in cols
 owner=[x for x in P['capabilities'] if x['access'].startswith('OWNER')]
 assert all(any('OWNER' in v for v in x['invariants']) for x in owner)
 assert not {v for x in P['capabilities'] for v in x['invariants'] if v.endswith('REMEDIATION_REQUIRED')}
 by={x['id']:set(x['invariants']) for x in P['capabilities']}
 for name in ('list_for_telegram_user','staff_new_tickets','staff_open_tickets'):
  assert 'LIMIT_MAXIMUM_100' in by[f'support_store.{name}']
 assert 'LATEST_500_MESSAGES' in by['support_store.thread_for_telegram_user']
 assert P['status']=='EXACT_PACKAGE_VERIFIED' and P['blockers']==[]
