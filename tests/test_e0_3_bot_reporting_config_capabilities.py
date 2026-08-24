import hashlib,importlib.util,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
P=json.loads((ROOT/'docs/e0-3-bot-reporting-config-capabilities.v1.json').read_text())
spec=importlib.util.spec_from_file_location('matrix',ROOT/'scripts/e0_bot_method_capability_matrix.py');M=importlib.util.module_from_spec(spec);spec.loader.exec_module(M)
REPOS={'promo_admin_store','provider_health_store','reporting_store'}
def test_group_covers_all_reachable_methods_and_sources():
 relay={x['id'] for name in ('reads','writers') for x in json.loads((ROOT/f'docs/e0-3-relay-{name[:-1]}-matrix.v1.json').read_text())[name]}
 assert {x['id'] for x in P['capabilities']}=={x['id'] for x in M.build()['methods'] if x['repository'] in REPOS and x['id'] not in relay}
 assert len(P['capabilities'])==10
 for repo,digest in P['sourceSha256'].items():assert hashlib.sha256((ROOT/f'relay/repositories/{repo}.py').read_bytes()).hexdigest()==digest
def test_group_columns_and_debt_are_closed():
 for item in P['capabilities']:
  assert item['reads'] and item['invariants']
  for cols in list(item['reads'].values())+list(item.get('mutations',{}).values()):
   assert cols and len(cols)==len(set(cols)) and not ({'*','ALL','UNKNOWN','TBD'}&set(cols))
 debt={v for x in P['capabilities'] for v in x['invariants'] if v.endswith('REMEDIATION_REQUIRED')}
 assert not debt and P['status']=='EXACT_PACKAGES_VERIFIED' and not P['blockers']
