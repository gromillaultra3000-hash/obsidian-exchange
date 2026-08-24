import hashlib,importlib.util,json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
P=json.loads((ROOT/'docs/e0-3-bot-payment-session-capabilities.v1.json').read_text())
spec=importlib.util.spec_from_file_location('matrix',ROOT/'scripts/e0_bot_method_capability_matrix.py')
M=importlib.util.module_from_spec(spec);spec.loader.exec_module(M)

def test_payment_session_package_covers_every_reachable_method_and_source():
 matrix=M.build()
 expected={x['id'] for x in matrix['methods'] if x['repository']=='payment_session_store'}
 actual={x['id'] for x in P['capabilities']}
 assert actual==expected and len(actual)==3
 assert hashlib.sha256((ROOT/'relay/repositories/payment_session_store.py').read_bytes()).hexdigest()==P['sourceSha256']
 callers={x['id']:{c.split(':')[0] for c in x['callers']} for x in P['capabilities']}
 graph=M.graph.build()
 for item in P['capabilities']:
  method=item['id'].split('.',1)[1]
  assert callers[item['id']]=={e['caller'] for e in graph['edges'] if e['repository']=='payment_session_store' and e['method']==method}

def test_payment_session_reads_are_closed_and_remediation_is_explicit():
 for item in P['capabilities']:
  assert item['access']=='OPERATOR_READ' and item['reads'] and item['invariants']
  assert set(item['reads'])=={'payment_sessions'}
  columns=item['reads']['payment_sessions']
  assert columns and len(columns)==len(set(columns))
  assert not ({'*','ALL','UNKNOWN','TBD'}&set(columns))
 recent=next(x for x in P['capabilities'] if x['id'].endswith('.recent_for_order'))
 assert 'LIMIT_CLAMP_1_100' in recent['invariants']
 assert (ROOT/'relay/repositories/payment_session_store.py').read_text().count(
  'min(100, max(1, int(limit)))')==2
 assert P['status']=='EXACT_PACKAGE' and P['blockers']==[]
 assert P['grantPolicy']['operatorOnly'] is True
 assert P['grantPolicy']['customerCallable'] is P['grantPolicy']['unboundedLimitAllowed'] is False
