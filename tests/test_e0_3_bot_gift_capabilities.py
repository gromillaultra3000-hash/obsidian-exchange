import hashlib,importlib.util,json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
P=json.loads((ROOT/'docs/e0-3-bot-gift-capabilities.v1.json').read_text())
spec=importlib.util.spec_from_file_location('matrix',ROOT/'scripts/e0_bot_method_capability_matrix.py')
M=importlib.util.module_from_spec(spec);spec.loader.exec_module(M)

def test_gift_package_covers_every_reachable_method_and_source():
 expected={x['id'] for x in M.build()['methods'] if x['repository']=='gift_store'}
 actual={x['id'] for x in P['capabilities']}
 assert actual==expected and len(actual)==4
 assert hashlib.sha256((ROOT/'relay/repositories/gift_store.py').read_bytes()).hexdigest()==P['sourceSha256']
 assert P['status']=='EXACT_PACKAGE' and P['productionAuthorization'] is False

def test_gift_columns_and_single_winner_money_transitions_are_closed():
 allowed={'gift_vouchers','orders'}
 for item in P['capabilities']:
  assert item['access'] in {'READ','MONEY_WRITE'} and item['reads'] and item['invariants']
  assert set(item['reads'])<=allowed and set(item.get('mutations',{}))<=allowed
  for columns in list(item['reads'].values())+list(item.get('mutations',{}).values()):
   assert columns and len(columns)==len(set(columns))
   assert not ({'*','ALL','UNKNOWN','TBD'}&set(columns))
 by_id={x['id']:set(x['invariants']) for x in P['capabilities']}
 assert {'ORDER_AND_VOUCHER_ONE_TRANSACTION','CODE_CONFLICT_ROLLS_BACK_ORDER'}<=by_id['gift_store.issue']
 assert {'PAID_TO_REDEEMED_CAS','SINGLE_WINNER','ORDER_FAILURE_ROLLS_BACK_REDEMPTION'}<=by_id['gift_store.redeem']
