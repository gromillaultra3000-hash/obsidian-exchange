import hashlib,importlib.util,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];P=json.loads((ROOT/'docs/e0-3-bot-reconciliation-capabilities.v1.json').read_text())
spec=importlib.util.spec_from_file_location('m',ROOT/'scripts/e0_bot_method_capability_matrix.py');M=importlib.util.module_from_spec(spec);spec.loader.exec_module(M)
def test_package_covers_remaining_methods_and_source():
 relay={x['id'] for n in ('reads','writers') for x in json.loads((ROOT/f'docs/e0-3-relay-{n[:-1]}-matrix.v1.json').read_text())[n]}
 expected={x['id'] for x in M.build()['methods'] if x['repository']=='reconciliation_store' and x['id'] not in relay}
 assert {x['id'] for x in P['capabilities']}==expected and len(expected)==6
 assert hashlib.sha256((ROOT/'relay/repositories/reconciliation_store.py').read_bytes()).hexdigest()==P['sourceSha256']
 source=(ROOT/'relay/repositories/reconciliation_store.py').read_text()
 assert 'CREATE TABLE' not in source and 'executescript' not in source
def test_money_and_outbox_invariants_are_closed():
 for x in P['capabilities']:
  assert x['reads'] and x['invariants']
  for cols in list(x['reads'].values())+list(x.get('mutations',{}).values()):assert cols and len(cols)==len(set(cols)) and '*' not in cols
 by={x['id']:set(x['invariants']) for x in P['capabilities']}
 assert {'ONE_TRANSACTION','PAID_TO_SENT_CAS','OUTBOX_ATOMIC'}<=by['reconciliation_store.reconcile_order']
 assert {'SENDING_TO_SENT_CAS'}<=by['reconciliation_store.mark_notification_sent']
 assert {'LIMIT_MINIMUM_ONE','LIMIT_MAXIMUM_100'}<=by['reconciliation_store.pending_orders']
 source=(ROOT/'relay/repositories/reconciliation_store.py').read_text()
 assert source.count('limit = max(1, min(int(limit), 100))')==2
 assert P['status']=='EXACT_PACKAGE_VERIFIED' and P['blockers']==[]
