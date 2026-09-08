"""Exactly one subsequent E4 item from real generated-page browser observations."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).parent
pages = json.loads((OUT / 'acceptance-pages.json').read_text())
browser = json.loads((OUT / 'payment-browser-report.json').read_text())
assert browser['result'] == 'PASS'
assert browser['sourceSha256'] == hashlib.sha256((OUT / 'acceptance-pages.json').read_bytes()).hexdigest()
observed = browser['pendingReceiptObservations']
assert len(observed) == 2 and {row['surface'] for row in observed} == {'numeric', 'opaque'}
for row in observed:
    fixture = next(item for item in pages['pages']
                   if item['name'] == ('numeric-' if row['surface'] == 'numeric' else '') + 'pending-stored-unavailable')
    assert fixture['expected']['status'] == row['canonicalStatus'] == 'pending'
    assert fixture['expected']['receipt'] == row['receipt'] == 'stored'
    assert fixture['expected']['dead'] is row['dead'] is True
    assert row['receiptAcknowledged'] is False and row['noPaymentInstructions'] is True
paths = ['relay-fastapi/main.py', 'relay/repositories/payment_status_read_store.py',
         'docs/e4-payment-terminal/acceptance-probe.py',
         'docs/e4-payment-terminal/acceptance-probe.json',
         'docs/e4-payment-terminal/acceptance-pages.json',
         'docs/e4-payment-terminal/payment-browser-report.json',
         'docs/e4-payment-terminal/payment-browser-isolation.json',
         'docs/e4-payment-terminal/320-terminal-pending-stored-unavailable.png',
         'docs/e4-payment-terminal/320-terminal-numeric-pending-stored-unavailable.png',
         str(Path(__file__).relative_to(ROOT))]
report = {'schemaVersion': 'e4-next-prerequisite.v1',
    'result': 'CONFIRMED_BOUNDED_NEXT_PREREQUISITE', 'activeRoute': 'E4',
    'completedSlice': 'PAYMENT_STATUS_TERMINAL_REASON_CONSISTENCY',
    'nextPrerequisite': 'PAYMENT_STATUS_PENDING_RECEIPT_EVIDENCE_CONSISTENCY',
    'canonicalNeed': 'A customer payment-status page should retain known receipt evidence alongside the canonical order state and payment-instruction availability.',
    'observed': observed,
    'mechanism': "For a database-valid pending order with receipt='stored' and unavailable latest session, API preserves the receipt fact but opaque viewDead and numeric _session_closed omit it. Both correctly suppress payment instructions. Receipt presence is acknowledged for terminal orders by the completed slice.",
    'implementationBoundary': 'Change only pending payment-page receipt presentation for unavailable requisites on opaque and numeric pages, with focused exact-render/browser tests and bounded operational evidence. Preserve canonical pending, unavailable-instruction suppression and API/database/writer behavior.',
    'acceptanceCriterion': 'Given pending+stored+unavailable, both page forms explicitly acknowledge the received file without claiming payment confirmation, sent-to-partner delivery or an active review assignment. Payment instructions remain absent. No receipt and sent receipt retain their distinct facts.',
    'notCurrentBlocker': 'The completed terminal slice preserves expired/failed/cancelled outcomes and their receipt evidence. This independently reproduced pending-state omission is outside that terminal rendering boundary.',
    'limits': ['Exact synthetic query_only SQLite fixtures and real Chrome output prove behavior; no customer incidence or production account request was observed.',
               'This is the only next E4 prerequisite; it neither replaces the canonical route nor authorizes payment/provider actions.'],
    'inputs': [{'path': path, 'sha256': hashlib.sha256((ROOT / path).read_bytes()).hexdigest()} for path in paths]}
(OUT / 'next-prerequisite.json').write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')
print(json.dumps({'result': report['result'], 'next': report['nextPrerequisite']}))
