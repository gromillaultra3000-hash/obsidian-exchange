"""Seal an independent, bounded terminal-presentation acceptance review."""
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
             'tests.json', 'ops-tests.json', 'preflight.json', 'rollback-rehearsal.json',
             'security-probe.json', 'security-ops-probe.json']:
    report = read(name)
    assert report['result'] == 'PASS', name
    for row in report.get('inputs', []):
        assert digest(ROOT / row['path']) == row['sha256'], (name, row['path'])
        paths.add(row['path'])
browser, isolation = read('payment-browser-report.json'), read('payment-browser-isolation.json')
assert browser['result'] == 'PASS' and len(browser['checks']) == 336
assert not browser['pageErrors'] and not browser['blockedRequests']
assert len(browser['requests']) == 54 and all(row['method'] == 'GET' for row in browser['requests'])
assert browser['sourceSha256'] == isolation['sourceSha256'] == digest(OUT / 'acceptance-pages.json')
assert browser['runnerSha256'] == isolation['runnerSha256'] == digest(ROOT / 'tests/e4_payment_terminal_browser.cjs')
assert isolation['processExitCode'] == 0 and isolation['unitStopped'] is True
assert isolation['chromiumSandbox'] is True and isolation['privateNetwork'] is True
assert isolation['stopObservation']['MainPID'] == '0' and isolation['stopObservation']['cgroupEmpty'] is True
assert read('acceptance-probe.json')['count'] == 59
assert read('acceptance-probe.json')['generatedPages'] == 60
assert read('acceptance-probe.json')['numericTerminalReasonMismatches'] == []
assert len(read('acceptance-baseline-probe.json')['numericTerminalReasonMismatches']) == 18
assert read('acceptance-surface.json')['unchangedCount'] == 155
assert read('acceptance-surface.json')['outsidePayModuleAstIdentical'] is True
assert read('security-probe.json')['passingCases'] == 136
assert read('security-baseline.json')['failingCases'] == 126
assert '122 passed' in read('tests.json')['summary']
assert '122 passed' in (OUT / 'tests-output.txt').read_text()
assert read('next-prerequisite.json')['nextPrerequisite'] == 'PAYMENT_STATUS_PENDING_RECEIPT_EVIDENCE_CONSISTENCY'
for row in read('next-prerequisite.json')['inputs']:
    assert digest(ROOT / row['path']) == row['sha256'], row['path']
    paths.add(row['path'])
for path in OUT.iterdir():
    if (path.is_file() and path.suffix in {'.json', '.py', '.md', '.png', '.txt'}
            and path.name not in {'acceptance-review.json', 'security-review.json', 'secret-scan.json',
                                  'gitleaks-report.json', 'deployment.json', 'ops-reconciliation.json', 'rollback.json'}):
        paths.add(str(path.relative_to(ROOT)))
paths.update(['scripts/run_e4_review_browser.py', 'tests/e4_payment_terminal_browser.cjs'])
manifest = read('ops-release-manifest.json')
for row in manifest['inputs']:
    assert digest(ROOT / row['path']) == row['sha256']
    paths.add(row['path'])
report = {'schemaVersion': 'e4-payment-terminal-independent-acceptance.v1', 'result': 'PASS',
    'reviewedAt': datetime.now(timezone.utc).isoformat(),
    'route': 'E4 / PAYMENT_STATUS_TERMINAL_REASON_CONSISTENCY',
    'reviewer': 'Independent acceptance agent; authored fixture/browser/probe evidence, not product or rollout recipe. No browser launch or production mutation by reviewer.',
    'decision': 'Accept the bounded single-file pay-presentation change for the existing gated reversible Relay rollout. Independent security approval and operational deployment gates remain separate.',
    'context': {
        'baseline': 'Backend-valid failed/cancelled orders were presented as expiry; stale verification could hide terminal outcomes, and receipt metadata replaced distinct reasons with a generic closed caption. Exact installed/baseline probes and prior actual-browser evidence establish this without inferring customer incidence.',
        'opaquePage': 'Canonical expired/failed/cancelled selects its own terminal renderer before receipt/verification. Received-file/delivered-receipt facts are additional text; they do not alter the outcome or promise payment, payout, active staff assignment or a review deadline.',
        'numericPage': 'Terminal status stays intact instead of being overwritten with _receipt_closed. Existing distinct terminal headings receive the corresponding receipt/no-repeat/support text.',
        'precedence': 'Paid/sent remain above terminal branches. Terminal outcome wins stale verification, dead-session metadata and local timer. No terminal page exposes payment, copy or QR controls.',
        'boundary': 'Only pay function changes. All 155 other functions, module wiring/imports, protected read/auth/redirect calls, adapter/proof/Mini App bytes retain their previous behavior.'},
    'evidence': {
        'focusedTests': read('tests.json')['summary'],
        'exactHandlers': '59 independent exact-handler/backend/auth checks PASS; 60 generated opaque/numeric pages. Real in-memory SQLite is query_only, with retained installed repository class and unchanged adapter; synthetic HMAC keys only.',
        'baselineSensitivity': '18 numeric terminal-reason mismatches reproduced on exact previous main and 0 on candidate. Independent security Node-VM terminal matrix has 126 baseline failures and 136 candidate passes.',
        'actualBrowser': '336 grouped checks PASS across 320/390 viewports: 27 terminal status/receipt/verification combinations, 4 stale dead/local-timer combinations, numeric parity, 54 pending-to-terminal poll transitions and preserved pending/paid/sent controls. 54 synthetic GET requests; zero blocked requests/page errors. Sandbox/private-network unit cleaned to MainPID 0/empty cgroup.',
        'visualInspection': ['320-terminal-failed-sent-video.png', '320-terminal-cancelled-stored-pdf.png',
                             '320-terminal-numeric-failed-sent-video.png', '320-terminal-pending-stored-unavailable.png'],
        'sourceBoundary': 'Independent whole-module AST comparison excludes only pay and is identical; protected reads/auth/redirect calls and pay imports are also identical. No new SQL or API behavior.',
        'operations': 'Single-file recipe independently inspected. Own 5 inert reconciliation/no-replay states PASS. Security 4 disposable filesystem scenarios cover normal round trip, interruption before/after publication and lost restart acknowledgement; known bytes/metadata restored and unrelated preserved file unchanged. Current ops tests, file/journal rollback rehearsal and preflight pass.'},
    'databaseRehearsalDecision': 'No repeated PostgreSQL/container run: query implementations, repository binding, auth, API and read call ASTs are unchanged. Prior read-contract database proof remains context; this slice adds exact current rendering/browser evidence.',
    'resolvedFindings': ['Numeric receipt fallback originally still hid expired/failed/cancelled reason; final implementation preserves the canonical terminal heading and adds receipt facts.',
                         'Stale verification prompt no longer outranks a terminal outcome; final actual browser permutations and poll transitions demonstrate the correction.'],
    'nextPrerequisite': {'id': 'PAYMENT_STATUS_PENDING_RECEIPT_EVIDENCE_CONSISTENCY',
        'artifact': 'docs/e4-payment-terminal/next-prerequisite.json',
        'observed': 'Both page forms omit a known stored receipt for pending+unavailable requisites. Exact API fixture and actual DOM/screens establish this remaining pending presentation omission while confirming payment controls are suppressed.'},
    'limitations': ['No real customer/order/bearer/proof/provider/wallet/money action or production database was used.',
        'Exact handler AST probes use declared exception/redirect wrappers and a false payout-delay fixture rather than importing the entire ASGI application.',
        'No real Telegram/iOS/WebKit, assistive technology or human-comprehension claim.',
        'Review is scoped acceptance, not a claim that the entire historical repository suite passes.',
        'No production deployment or real restart/rollback rehearsal is claimed. An authorized Relay restart resumes ordinary preexisting background work.'],
    'inputs': [{'path': path, 'sha256': digest(ROOT / path)} for path in sorted(paths)]}
(OUT / 'acceptance-review.json').write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')
print(json.dumps({'result': 'PASS', 'inputs': len(paths), 'sha256': digest(OUT / 'acceptance-review.json')}))
