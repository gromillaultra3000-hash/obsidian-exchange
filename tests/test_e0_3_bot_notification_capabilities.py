import hashlib,importlib.util,json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
P=json.loads((ROOT/'docs/e0-3-bot-notification-capabilities.v1.json').read_text())
spec=importlib.util.spec_from_file_location('matrix',ROOT/'scripts/e0_bot_method_capability_matrix.py')
M=importlib.util.module_from_spec(spec);spec.loader.exec_module(M)

def test_notification_package_covers_every_reachable_method_and_source():
 expected={x['id'] for x in M.build()['methods'] if x['repository']=='bot_notification_store'}
 actual={x['id'] for x in P['capabilities']}
 assert actual==expected and len(actual)==8
 assert hashlib.sha256((ROOT/'relay/repositories/bot_notification_store.py').read_bytes()).hexdigest()==P['sourceSha256']
 assert P['status']=='EXACT_PACKAGE' and P['productionAuthorization'] is False

def test_notification_columns_and_outbox_transitions_are_closed():
 allowed={'orders','payment_sessions','order_receipts','sent_notifications','blocked_users','promo_codes','bot_notification_jobs'}
 for item in P['capabilities']:
  assert item['access']=='WRITE' and item['reads'] and item['mutations'] and item['invariants']
  assert set(item['reads'])<=allowed and set(item['mutations'])<=allowed
  for columns in list(item['reads'].values())+list(item['mutations'].values()):
   assert columns and len(columns)==len(set(columns))
   assert not ({'*','ALL','UNKNOWN','TBD'}&set(columns))
 by_id={x['id']:set(x['invariants']) for x in P['capabilities']}
 assert {'PENDING_TO_SENDING_CAS','FOR_UPDATE_SKIP_LOCKED_POSTGRES','RETURNING_ATOMIC'}<=by_id['bot_notification_store.claim_notification']
 assert {'SENDING_TO_SENT_CAS'}<=by_id['bot_notification_store.mark_notification_sent']
 assert {'SENDING_TO_PENDING_CAS','CLAIM_CLEARED'}<=by_id['bot_notification_store.retry_notification']
 assert P['grantPolicy']=={'tableWideAccess':False,'functionPerMethodRequired':True,'directSequenceAccess':False}
