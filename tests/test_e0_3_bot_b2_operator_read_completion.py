import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
expected=set()
for path in sorted((ROOT/'docs').glob('e0-3-bot-*-capabilities.v1.json')):
 data=json.loads(path.read_text())
 for item in data.get('capabilities',[]):
  access=item.get('access','')
  if 'OPERATOR' in access and 'READ' in access: expected.add(item['id'])
evidence=set()
for name in (
 'e0-3-bot-b2-2a-operator-engagement-reads-rehearsal.v1.json',
 'e0-3-bot-b2-2b-operator-order-reads-rehearsal.v1.json',
 'e0-3-bot-b2-2c1-operator-payment-payout-reads-rehearsal.v1.json',
 'e0-3-bot-b2-2c2a-operator-config-sell-support-reads-rehearsal.v1.json',
 'e0-3-bot-b2-2c2b-operator-reporting-reads-rehearsal.v1.json'):
 data=json.loads((ROOT/'docs'/name).read_text()); assert data['result']=='PASS'
 covered=set(data['methodCoverage']); assert evidence.isdisjoint(covered); evidence|=covered
assert len(expected)==33 and evidence==expected,(sorted(expected-evidence),sorted(evidence-expected))
print('E0.3 bot B2 operator-read coverage: 33/33 exact')
