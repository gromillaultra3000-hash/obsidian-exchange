"""One next E4 condition: supported timestamp serialization breaks page expiry."""
import ast
from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).parent
captured_store = ROOT / 'output/manual/e4-payment-pending-receipt-20260908/baseline/relay/repositories/order_read_store.py'
value_node = next(node for node in ast.parse(captured_store.read_text()).body
                  if isinstance(node, ast.FunctionDef) and node.name == '_value')
namespace = {'date': date, 'datetime': datetime, 'Decimal': Decimal}
exec(compile(ast.fix_missing_locations(ast.Module(body=[value_node], type_ignores=[])),
             str(captured_store), 'exec'), namespace)
serialized = namespace['_value'](datetime(2099, 1, 1, tzinfo=timezone.utc))
assert serialized == '2099-01-01T00:00:00+00:00'
schema_path = ROOT / 'deploy/postgres/007_payment_sessions.sql'
assert 'expires_at TIMESTAMPTZ' in schema_path.read_text()
browser = json.loads((OUT / 'payment-browser-report.json').read_text())
assert browser['result'] == 'PASS'
assert browser['sourceSha256'] == hashlib.sha256((OUT / 'acceptance-pages.json').read_bytes()).hexdigest()
assert len(browser['expiryFormatObservations']) == 1
observed = browser['expiryFormatObservations'][0]
assert observed['serializedExpiry'] == serialized
assert observed['originalISOValid'] is True and observed['pageConstructedISOValid'] is False
assert observed['canonicalStatus'] == 'pending' and 'NaN:NaN' in observed['timerText']
fixture_report = json.loads((OUT / 'acceptance-probe.json').read_text())
assert fixture_report['awareExpiryProbe']['exactRetainedSerializerResult'] == serialized
paths = ['relay-fastapi/main.py', 'relay/repositories/payment_status_read_store.py',
         str(captured_store.relative_to(ROOT)), str(schema_path.relative_to(ROOT)),
         'docs/e4-payment-pending-receipt/acceptance-probe.py',
         'docs/e4-payment-pending-receipt/acceptance-probe.json',
         'docs/e4-payment-pending-receipt/acceptance-pages.json',
         'docs/e4-payment-pending-receipt/payment-browser-report.json',
         'docs/e4-payment-pending-receipt/payment-browser-isolation.json',
         'docs/e4-payment-pending-receipt/320-pending-receipt-aware-expiry.png',
         str(Path(__file__).relative_to(ROOT))]
report = {'schemaVersion': 'e4-next-prerequisite.v1',
    'result': 'CONFIRMED_BOUNDED_NEXT_PREREQUISITE', 'activeRoute': 'E4',
    'completedSlice': 'PAYMENT_STATUS_PENDING_RECEIPT_EVIDENCE_CONSISTENCY',
    'nextPrerequisite': 'PAYMENT_STATUS_EXPIRY_TIME_FORMAT_CONSISTENCY',
    'canonicalNeed': 'The payment-page timer must consume the timestamp format produced by the supported canonical payment-session read contract.',
    'supportedBackendProof': {'column': 'payment_sessions.expires_at TIMESTAMPTZ',
        'serializer': 'Exact captured installed order-store _value(datetime) calls isoformat()',
        'exampleResult': serialized, 'postgresOrProductionConnectionUsed': False},
    'observed': observed,
    'mechanism': 'startTimer appends Z to every expiry string that lacks Z. An already valid explicit UTC offset becomes +00:00Z; Chrome rejects this modified string and the rendered countdown contains NaN:NaN.',
    'implementationBoundary': 'Repair payment-page expiry parsing and its focused exact-render/browser tests. Preserve existing naive-UTC and Z forms, canonical status/receipt/verification precedence, polling and all API/database/writer behavior. Deliver with bounded operational evidence.',
    'acceptanceCriterion': 'Valid offset-bearing timestamps, Z timestamps and supported naive UTC timestamps represent the correct instant and never display NaN. Missing or invalid metadata must not fabricate an expiry outcome. A local timer never rewrites canonical order status or overrides known receipt/terminal outcomes.',
    'notCurrentBlocker': 'The completed receipt change acknowledges stored/delivered evidence for unavailable requisites and preserves verification/status behavior. The unchanged timestamp parser is a separate presentation dependency exposed by this acceptance matrix.',
    'limits': ['Exact serializer, canonical DDL, synthetic handler fixture and actual Chrome DOM establish a supported backend-format mismatch; no live customer incidence or current production database value was observed.',
               'This is exactly one next E4 prerequisite and does not authorize a provider/payment action or broaden the canonical route.'],
    'inputs': [{'path': path, 'sha256': hashlib.sha256((ROOT / path).read_bytes()).hexdigest()} for path in paths]}
(OUT / 'next-prerequisite.json').write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')
print(json.dumps({'result': report['result'], 'next': report['nextPrerequisite']}))
