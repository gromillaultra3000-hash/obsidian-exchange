import hashlib,importlib.util,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];P=json.loads((ROOT/'docs/e0-3-bot-sell-order-capabilities.v1.json').read_text())
spec=importlib.util.spec_from_file_location('m',ROOT/'scripts/e0_bot_method_capability_matrix.py');M=importlib.util.module_from_spec(spec);spec.loader.exec_module(M)
def test_package_covers_remaining_reachable_methods_and_source():
 relay={x['id'] for n in ('reads','writers') for x in json.loads((ROOT/f'docs/e0-3-relay-{n[:-1]}-matrix.v1.json').read_text())[n]}
 expected={x['id'] for x in M.build()['methods'] if x['repository']=='sell_order_store' and x['id'] not in relay}
 assert {x['id'] for x in P['capabilities']}==expected and len(expected)==5
 assert hashlib.sha256((ROOT/'relay/repositories/sell_order_store.py').read_bytes()).hexdigest()==P['sourceSha256']
def test_columns_and_money_cas_are_closed():
 for x in P['capabilities']:
  assert x['reads'] and x['invariants']
  for cols in list(x['reads'].values())+list(x.get('mutations',{}).values()):assert cols and len(cols)==len(set(cols)) and '*' not in cols
 money=[x for x in P['capabilities'] if x['access']=='MONEY_WRITE'];assert all(any('CAS' in v for v in x['invariants']) for x in money)
 assert P['blockers']==[]
