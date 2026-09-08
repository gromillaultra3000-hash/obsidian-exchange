"""Seal the bounded independent pending-receipt acceptance against frozen inputs."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).parent


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(name):
    return json.loads((OUT / name).read_text())


paths = set()
for name in ['acceptance-probe.json', 'acceptance-surface.json', 'acceptance-ops-probe.json',
             'tests.json', 'ops-tests.json', 'ops-scope-proof.json', 'preflight.json',
             'rollback-rehearsal.json', 'security-probe.json', 'security-ops-probe.json']:
    item = read(name)
    assert item['result'] == 'PASS', name
    for row in item.get('inputs', []):
        assert digest(ROOT / row['path']) == row['sha256'], (name, row['path'])
        paths.add(row['path'])
browser, isolation = read('payment-browser-report.json'), read('payment-browser-isolation.json')
assert browser['result'] == 'PASS' and len(browser['checks']) == 142
assert not browser['pageErrors'] and not browser['blockedRequests']
assert len(browser['requests']) == 14 and all(row['method'] == 'GET' for row in browser['requests'])
assert browser['sourceSha256'] == isolation['sourceSha256'] == digest(OUT / 'acceptance-pages.json')
assert browser['runnerSha256'] == isolation['runnerSha256'] == digest(ROOT / 'tests/e4_payment_pending_receipt_browser.cjs')
assert isolation['processExitCode'] == 0 and isolation['unitStopped'] is True
assert isolation['chromiumSandbox'] is True and isolation['privateNetwork'] is True
assert isolation['stopObservation']['MainPID'] == '0' and isolation['stopObservation']['cgroupEmpty'] is True
assert read('acceptance-probe.json')['count'] == 49 and read('acceptance-probe.json')['generatedPages'] == 34
assert read('acceptance-probe.json')['numericStoredReceiptMismatches'] == []
assert len(read('acceptance-baseline.json')['numericStoredReceiptMismatches']) == 1
assert read('acceptance-surface.json')['unchangedCount'] == 155
assert read('acceptance-surface.json')['outsidePayModuleAstIdentical'] is True
assert read('security-probe.json')['passingCases'] == 122
assert read('security-baseline.json')['failingCases'] == 12
assert '141 passed' in read('tests.json')['summary'] and '141 passed' in (OUT / 'tests.stdout.txt').read_text()
assert read('ops-tests.json')['passed'] == 17
assert read('secret-scan.json')['result'] == 'PASS' and read('secret-scan.json')['findings'] == 0
assert read('next-prerequisite.json')['nextPrerequisite'] == 'PAYMENT_STATUS_EXPIRY_TIME_FORMAT_CONSISTENCY'
for row in read('next-prerequisite.json')['inputs']:
    assert digest(ROOT / row['path']) == row['sha256'], row['path']
    paths.add(row['path'])
for path in OUT.iterdir():
    if (path.is_file() and path.suffix in {'.json', '.py', '.md', '.png', '.txt'}
            and path.name not in {'acceptance-review.json', 'security-review.json', 'secret-scan.json',
                                  'gitleaks-report.json', 'deployment.json', 'ops-reconciliation.json', 'rollback.json'}):
        paths.add(str(path.relative_to(ROOT)))
paths.update(['scripts/run_e4_review_browser.py', 'tests/e4_payment_pending_receipt_browser.cjs'])
for row in read('ops-release-manifest.json')['inputs']:
    assert digest(ROOT / row['path']) == row['sha256']
    paths.add(row['path'])
report = {'schemaVersion': 'e4-pending-receipt-independent-acceptance.v1', 'result': 'PASS',
    'reviewedAt': datetime.now(timezone.utc).isoformat(),
    'route': 'E4 / PAYMENT_STATUS_PENDING_RECEIPT_EVIDENCE_CONSISTENCY',
    'reviewer': 'Independent acceptance agent; authored fixture/browser/probe evidence, not product or rollout recipe. No browser launch or production mutation by reviewer.',
    'decision': 'Accept the bounded single-file pay-presentation change for the existing gated reversible Relay rollout. Independent security and operational deployment gates remain separate.',
    'acceptedBehavior': [
        'Numeric pending+stored+unavailable acknowledges the received file, says it has not yet been delivered to the partner and retains no-repeat/support advice.',
        'Opaque pending+unavailable retains stored receipt evidence even when a video/PDF verification request occupies the main view. Delivered receipt fact appears with verification when otherwise hidden. Verification instructions remain visible.',
        'Evidence never asserts confirmed payment, payout, an active staff assignment or a review deadline. Repeated render does not duplicate the evidence block.',
        'No-receipt and normal delivered-receipt branches keep their distinct behavior. Active payment instructions keep their existing availability rules, and terminal/paid/sent outcomes retain precedence.',
        'An unknown nonempty receipt value on local expiry does not fabricate a stored file. Canonical pending status remains unchanged.'],
    'evidence': {
        'focusedTests': '141 focused tests PASS; raw stdout and source/test bindings verified.',
        'operationsTests': '17 ops tests PASS; publication/restart observations use disposable fixtures.',
        'exactHandlers': '49 independent exact-handler/auth/backend checks PASS on real query_only in-memory SQLite through the exact retained installed class and unchanged adapter.34 current pages; baseline emits no duplicate page bundle. Numeric omission is1 on captured baseline and0 on candidate.',
        'actualBrowser': '142 grouped checks PASS at320/390, including unavailable/active × absent/stored/sent × verification × local timer, repeated-render idempotence, numeric acknowledgement, terminal/paid/sent controls and14 GET poll transitions. No page errors or blocked requests; non-root sandbox/private-network unit stopped with empty cgroup.',
        'independentSecurity': '122 exact inline-JavaScript/security cases PASS;12 failures on captured baseline establish sensitivity. Existing script escaping/literal clipboard, auth/read/redirect/serialization boundaries are preserved.',
        'sourceBoundary': 'Only pay changes;155 other top-level functions, whole module outside pay, protected read/auth/redirect call ASTs and imports are identical. Adapter/proof/Mini App bytes remain unchanged.',
        'operationalReview': 'Single-file recipe manually inspected. New presentation_scope validates byte identity outside numeric display/inline script, identical remaining Python interpolations and pure numeric local display operations; it runs in preflight and deploy. Own5 inert reconciliation/no-replay checks and separate4 disposable rollback/lost-acknowledgement scenarios PASS. Current manifest, preflight and3 file/journal rehearsal checks are bound.',
        'initialSecretScan': 'Observed staged scan PASS with0 findings and no suppression. Final staging/scan after review creation remains independently checked by primary/security; mutable scan output is excluded from recursive input bindings.',
        'visualInspection': ['320-pending-stored-unavailable-video.png', '320-numeric-pending-stored-unavailable-none.png', '320-pending-receipt-aware-expiry.png']},
    'databaseRehearsalDecision': 'No repeated PostgreSQL/container run: queries, repository binding, API/auth/read calls and all nonpresentation Python remain unchanged. Prior database acceptance stays context, while this slice verifies the exact current presentation.',
    'nextPrerequisite': {'id': 'PAYMENT_STATUS_EXPIRY_TIME_FORMAT_CONSISTENCY',
        'artifact': 'docs/e4-payment-pending-receipt/next-prerequisite.json',
        'observed': 'Canonical TIMESTAMPTZ-compatible aware datetime serializes to a valid +00:00 ISO string. The unchanged page appends Z, producing an invalid date and actual NaN:NaN countdown. Exact captured serializer, canonical DDL, generated HTML and Chrome screenshot establish one supported-format mismatch.'},
    'limitations': ['No real customer/order/bearer/proof/provider/wallet/money action or production database was used.',
        'Exact handler AST probes use declared exception/redirect wrappers and false payout-delay fixture rather than the whole ASGI runtime.',
        'The timezone observation is a synthetic supported backend-format proof, not a production customer-incidence claim; it is outside this receipt fix.',
        'No real Telegram/iOS/WebKit, assistive technology or human-comprehension claim, and no claim that the entire historical repository suite passes.',
        'No production deployment or real restart/rollback rehearsal is claimed. Authorized Relay restart resumes ordinary preexisting background work.'],
    'inputs': [{'path': path, 'sha256': digest(ROOT / path)} for path in sorted(paths)]}
(OUT / 'acceptance-review.json').write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')
print(json.dumps({'result': 'PASS', 'inputs': len(paths), 'sha256': digest(OUT / 'acceptance-review.json')}))
