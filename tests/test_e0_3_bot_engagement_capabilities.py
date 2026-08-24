import hashlib,importlib.util,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];P=json.loads((ROOT/'docs/e0-3-bot-engagement-capabilities.v1.json').read_text())
spec=importlib.util.spec_from_file_location('m',ROOT/'scripts/e0_bot_method_capability_matrix.py');M=importlib.util.module_from_spec(spec);spec.loader.exec_module(M)
def test_package_covers_remaining_methods_and_source():
 relay={x['id'] for n in ('reads','writers') for x in json.loads((ROOT/f'docs/e0-3-relay-{n[:-1]}-matrix.v1.json').read_text())[n]}
 expected={x['id'] for x in M.build()['methods'] if x['repository']=='engagement_store' and x['id'] not in relay}
 assert {x['id'] for x in P['capabilities']}==expected and len(expected)==19
 assert hashlib.sha256((ROOT/'relay/repositories/engagement_store.py').read_bytes()).hexdigest()==P['sourceSha256']
def test_columns_scopes_and_privacy_debt_are_closed():
 for x in P['capabilities']:
  assert x['reads'] and x['invariants']
  for cols in list(x['reads'].values())+list(x.get('mutations',{}).values()):assert cols and len(cols)==len(set(cols)) and '*' not in cols
 referral=next(x for x in P['capabilities'] if x['id'].endswith('.referral_bonus'))
 assert {'OWNER_MODE_BINDS_EXACT_REFERRER','OPERATOR_PERIOD_MODE_REQUIRES_NULL_USER_AND_BOTH_DATES','MIXED_MODES_FAIL_CLOSED'}<=set(referral['invariants'])
 assert (ROOT/'relay/repositories/engagement_store.py').read_text().count('referral_bonus_period_is_operator_aggregate')==2
 by={x['id']:set(x['invariants']) for x in P['capabilities']}
 assert {'EXACT_ORDER_AND_OWNER','CROSS_OWNER_NO_WRITE'}<=by['engagement_store.comment_review']
 assert {'EXACT_ORDER_AND_OWNER','PENDING_COMMENT_TO_TERMINAL_CAS'}<=by['engagement_store.finalize_review']
 assert {'ACTOR_POSITIVE','ACTION_LENGTH_1_TO_80','DETAILS_OPTIONAL_MAX_500'}<=by['engagement_store.log_action']
 for name in ('broadcast_user_ids','order_customer_ids','subscribers'):
  assert {'KEYSET_PAGES_500','COMPLETE_UNTIL_EMPTY','USER_ID_ASC'}<=by[f'engagement_store.{name}']
 source=(ROOT/'relay/repositories/engagement_store.py').read_text()
 assert source.count('ORDER BY user_id LIMIT 500')==6
 assert source.count("c.execute('BEGIN IMMEDIATE')")==2
 assert source.count('SET enabled=NOT enabled')==2
 assert 'CREATE TABLE IF NOT EXISTS reviews' not in source
 assert 'CREATE UNIQUE INDEX IF NOT EXISTS idx_reviews_order' not in source
 assert {'ATOMIC_INVERT_RETURNING','CONCURRENT_TOGGLES_SERIALIZED'}<=by['engagement_store.toggle_rate']
 assert P['status']=='EXACT_PACKAGE_VERIFIED' and P['blockers']==[]
