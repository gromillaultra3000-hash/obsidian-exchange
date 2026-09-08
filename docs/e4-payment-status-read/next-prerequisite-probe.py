"""Bind one next E4 condition to exact API fixtures and real browser output."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).parent
pages = json.loads((OUT / 'acceptance-pages.json').read_text())
browser = json.loads((OUT / 'payment-browser-report.json').read_text())
assert browser['result'] == 'PASS'
assert browser['sourceSha256'] == hashlib.sha256((OUT / 'acceptance-pages.json').read_bytes()).hexdigest()
observations = browser['terminalObservations']
assert {row['canonicalStatus'] for row in observations} == {'failed', 'cancelled'}
for row in observations:
    fixture = next(item for item in pages['pages'] if item['name'] == row['canonicalStatus'] + '-absent')
    assert fixture['expected']['status'] == row['canonicalStatus']
    assert fixture['expected']['receipt'] == '' and not fixture['expected']['dead']
    assert row['visiblePill'] == 'Время истекло'
    assert row['visibleLabel'] == 'Срок оплаты заявки истёк'
    assert row['noPaymentInstructions'] is True
paths = ['relay-fastapi/main.py', 'relay/repositories/payment_status_read_store.py',
         'docs/e4-payment-status-read/acceptance-probe.py',
         'docs/e4-payment-status-read/acceptance-probe.json',
         'docs/e4-payment-status-read/acceptance-pages.json',
         'docs/e4-payment-status-read/payment-browser-report.json',
         'docs/e4-payment-status-read/payment-browser-isolation.json',
         'docs/e4-payment-status-read/320-pay-failed-absent.png',
         str(Path(__file__).relative_to(ROOT))]
report = {'schemaVersion': 'e4-next-prerequisite.v1',
    'result': 'CONFIRMED_BOUNDED_NEXT_PREREQUISITE',
    'activeRoute': 'E4', 'completedSlice': 'PAYMENT_STATUS_RUNTIME_READ_CONTRACT',
    'nextPrerequisite': 'PAYMENT_STATUS_TERMINAL_REASON_CONSISTENCY',
    'canonicalNeed': 'The E4 customer payment-status surface must explain the canonical order outcome consistently across the API, opaque page and numeric fallback.',
    'observed': observations,
    'mechanism': "The exact opaque pay render computes closed for expired/failed/cancelled, then invokes viewExpired() for every closed order without receipt. The repaired reader faithfully returns failed/cancelled; the page labels both as a time expiry. Numeric fallback now distinguishes those states.",
    'implementationBoundary': 'Change only the payment-page terminal rendering and its focused behavior/browser tests; preserve terminal action suppression, receipt precedence, canonical API status and existing writer behavior. Deliver with bounded operational evidence.',
    'acceptanceCriterion': 'Actual browser fixtures for expired, failed and cancelled show their own canonical terminal meaning; failed/cancelled do not claim expiry. Receipts remain acknowledged and no terminal state exposes payment requisites.',
    'notCurrentBlocker': 'Current read-contract repair returns authorized canonical state and prevents unsafe transfer actions; this remaining presentation mismatch does not invalidate the restored read/auth boundary.',
    'limits': ['Synthetic database-valid fixtures and exact generated HTML establish behavior; no customer incidence or loaded production-page observation is claimed.',
               'This is exactly one next E4 prerequisite, not a replacement product route or permission for provider/payment actions.'],
    'inputs': [{'path': path, 'sha256': hashlib.sha256((ROOT / path).read_bytes()).hexdigest()} for path in paths]}
(OUT / 'next-prerequisite.json').write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')
print(json.dumps({'result': report['result'], 'next': report['nextPrerequisite']}))
