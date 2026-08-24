import hashlib,importlib.util,json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
S=json.loads((ROOT/'docs/e0-3-bot-method-capability-matrix.v1.json').read_text())
spec=importlib.util.spec_from_file_location('matrix',ROOT/'scripts/e0_bot_method_capability_matrix.py')
M=importlib.util.module_from_spec(spec);spec.loader.exec_module(M)

def test_method_matrix_is_canonical_and_covers_every_edge():
 data=M.build()
 wire=(json.dumps(data,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode()
 assert hashlib.sha256(wire).hexdigest()==S['canonicalOutputSha256']
 assert data['status']==S['status']=='EXACT_METHOD_MATRIX_VERIFIED'
 graph=M.graph.build()
 assert {(x['repository'],x['method']) for x in data['methods']}=={
  (x['repository'],x['method']) for x in graph['edges']}

def test_method_classes_and_relation_objects_are_truthful():
 data=M.build();methods=data['methods']
 relay_read=json.loads((ROOT/'docs/e0-3-relay-read-matrix.v1.json').read_text())['reads']
 relay_write=json.loads((ROOT/'docs/e0-3-relay-writer-matrix.v1.json').read_text())['writers']
 admin=json.loads((ROOT/'docs/e0-3-bot-admin-config-capabilities.v1.json').read_text())['capabilities']
 notification=json.loads((ROOT/'docs/e0-3-bot-notification-capabilities.v1.json').read_text())['capabilities']
 bot_order=json.loads((ROOT/'docs/e0-3-bot-order-capabilities.v1.json').read_text())['capabilities']
 dca=json.loads((ROOT/'docs/e0-3-bot-dca-capabilities.v1.json').read_text())['capabilities']
 gift=json.loads((ROOT/'docs/e0-3-bot-gift-capabilities.v1.json').read_text())['capabilities']
 limit_order=json.loads((ROOT/'docs/e0-3-bot-limit-order-capabilities.v1.json').read_text())['capabilities']
 payment_session=json.loads((ROOT/'docs/e0-3-bot-payment-session-capabilities.v1.json').read_text())['capabilities']
 small=json.loads((ROOT/'docs/e0-3-bot-small-store-capabilities.v1.json').read_text())['capabilities']
 reporting=json.loads((ROOT/'docs/e0-3-bot-reporting-config-capabilities.v1.json').read_text())['capabilities']
 support=json.loads((ROOT/'docs/e0-3-bot-support-capabilities.v1.json').read_text())['capabilities']
 workflow=json.loads((ROOT/'docs/e0-3-bot-order-workflow-capabilities.v1.json').read_text())['capabilities']
 sell=json.loads((ROOT/'docs/e0-3-bot-sell-order-capabilities.v1.json').read_text())['capabilities']
 reconciliation=json.loads((ROOT/'docs/e0-3-bot-reconciliation-capabilities.v1.json').read_text())['capabilities']
 payout=json.loads((ROOT/'docs/e0-3-bot-payout-capabilities.v1.json').read_text())['capabilities']
 order_read=json.loads((ROOT/'docs/e0-3-bot-order-read-capabilities.v1.json').read_text())['capabilities']
 engagement=json.loads((ROOT/'docs/e0-3-bot-engagement-capabilities.v1.json').read_text())['capabilities']
 method_ids={x['id'] for x in methods}
 evidenced=method_ids&({x['id'] for x in relay_read}|{x['id'] for x in relay_write}|{x['id'] for x in admin}|{x['id'] for x in notification}|{x['id'] for x in bot_order}|{x['id'] for x in dca}|{x['id'] for x in gift}|{x['id'] for x in limit_order}|{x['id'] for x in payment_session}|{x['id'] for x in small}|{x['id'] for x in reporting}|{x['id'] for x in support}|{x['id'] for x in workflow}|{x['id'] for x in sell}|{x['id'] for x in reconciliation}|{x['id'] for x in payout}|{x['id'] for x in order_read}|{x['id'] for x in engagement})
 counts={
  'uniqueMethods':len(methods),
  'readOnly':sum(x['capabilityClass']=='READ_ONLY' for x in methods),
  'writerOrSchema':sum(x['capabilityClass']=='WRITER_OR_SCHEMA' for x in methods),
  'dynamicSqlMethods':sum(x['dynamicSqlPresent'] for x in methods),
  'relationObjects':len({o for x in methods for o in x['objects']}),
  'exactColumnInvariantEvidenceMethods':len(evidenced),
  'pendingColumnInvariantMethods':len(methods)-len(evidenced)}
 assert counts==S['counts']
 assert all(x['operations'] and x['objects'] and x['callers'] for x in methods)
 assert 'limit' not in {o for x in methods for o in x['objects']}
