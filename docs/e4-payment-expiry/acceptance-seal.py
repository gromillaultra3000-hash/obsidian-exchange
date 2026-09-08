"""Seal the bounded independent payment-expiry acceptance against final inputs."""
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
             'tests.json', 'ops-tests.json', 'ops-review.json', 'ops-scope-proof.json',
             'preflight.json', 'rollback-rehearsal.json', 'security-probe.json',
             'security-ops-probe.json', 'payment-browser-report.json']:
    item = read(name)
    assert item['result'] == 'PASS', name
    for row in item.get('inputs', []):
        assert digest(ROOT / row['path']) == row['sha256'], (name, row['path'])
        paths.add(row['path'])
browser, isolation = read('payment-browser-report.json'), read('payment-browser-isolation.json')
assert len(browser['checks']) == 83 and all(row['result'] == 'PASS' for row in browser['checks'])
assert len(browser['timezoneInstants']) == 27
assert all(row['expectedMs'] == row['parsedMs'] for row in browser['timezoneInstants'])
assert not browser['pageErrors'] and not browser['blockedRequests']
assert len(browser['requests']) == 10 and all(row['method'] == 'GET' for row in browser['requests'])
assert browser['sourceSha256'] == isolation['sourceSha256'] == digest(OUT / 'acceptance-pages.json')
assert browser['runnerSha256'] == isolation['runnerSha256'] == digest(ROOT / 'tests/e4_payment_expiry_browser.cjs')
assert isolation['processExitCode'] == 0 and isolation['unitStopped'] is True
assert isolation['user'] == 'nobody' and isolation['chromiumSandbox'] is True
assert isolation['privateNetwork'] is True and isolation['protectHome'] is True
assert isolation['stopObservation']['MainPID'] == '0' and isolation['stopObservation']['cgroupEmpty'] is True
assert read('acceptance-probe.json')['count'] == 30 and read('acceptance-probe.json')['generatedPages'] == 30
assert read('acceptance-probe.json')['databaseWritesAllowed'] is False
assert read('acceptance-probe.json')['providerOrMoneyCalls'] == 0
assert read('acceptance-surface.json')['unchangedCount'] == 155
assert read('acceptance-surface.json')['outsideExpiryHelperTimerBytesIdentical'] is True
assert read('security-probe.json')['cases'] == 318 and read('security-probe.json')['failingCases'] == 0
assert read('security-baseline.json')['failingCases'] == 288
assert '208 passed' in read('tests.json')['summary'] and '208 passed' in (OUT / 'tests.stdout.txt').read_text()
assert read('ops-tests.json')['passed'] == 17
assert len(read('acceptance-ops-probe.json')['cases']) == 5
assert len(read('security-ops-probe.json')['cases']) == 4
assert read('ops-review.json')['targetCount'] == 1 and read('ops-review.json')['preservedCount'] == 16
assert read('secret-scan.json')['result'] == 'PASS' and read('secret-scan.json')['findings'] == 0
assert read('secret-scan.json')['suppressionUsed'] is False

next_inputs = ['relay-fastapi/main.py', 'tests/e4_payment_expiry_browser.cjs',
               'docs/e4-payment-expiry/acceptance-probe.json',
               'docs/e4-payment-expiry/acceptance-surface.json',
               'docs/e4-payment-expiry/payment-browser-report.json',
               'docs/e4-payment-expiry/payment-browser-isolation.json',
               'docs/e4-payment-expiry/contract.md']
next_evaluation = {
    'schemaVersion': 'e4-expiry-next-acceptance-evaluation.v1',
    'result': 'NO_ADDITIONAL_CONCRETE_PRODUCT_DEFECT_IDENTIFIED',
    'route': 'E4 / PAYMENT_STATUS_EXPIRY_TIME_FORMAT_CONSISTENCY',
    'canonicalSource': 'docs/ecosystem-master-roadmap.md, E4 gate section',
    'canonicalGate': 'Before confirmation the user understands the executor, custody, KYC, fees and irreversibility; dangerous actions cannot happen by an accidental tap.',
    'scope': 'This expiry-format audit establishes its bounded behavior and does not establish the whole E4 gate.',
    'nextPrerequisite': None,
    'nextBoundedWork': {
        'id': 'MONEY_FLOW_ACCEPTANCE_COVERAGE',
        'route': 'E4 / MONEY_FLOW_ACCEPTANCE_COVERAGE',
        'purpose': 'Assess cross-surface money-flow coverage against the canonical E4 gate using existing executable tests and deployed evidence.',
        'acceptance': [
            'Map each canonical gate claim to its concrete site, bot, Mini App or payment-page flow and existing executable/deployment evidence; distinguish covered behavior from unverified claims.',
            'Add meaningful executable coverage for a demonstrated gap that can be verified without customer data, credentials, provider or money actions.',
            'Name the next actual code fix only if a reproducible failure establishes it; do not invent a defect from an absent test.',
            'Keep real Telegram/iOS/WebKit, assistive-technology and human-comprehension/usability checks explicitly unverified until corresponding evidence exists.'
        ]
    },
    'evidence': 'The current 30 exact generated pages and 83 actual Chrome checks pass, including 27 timezone comparisons. No additional expiry, receipt, verification, canonical-status or poll defect was reproduced by this bounded matrix.',
    'notAnE4Closure': True,
    'currentDeploymentBlockedByThisEvaluation': False,
    'limits': 'Chrome synthetic fixtures establish the exercised DOM and timer behavior, not human understanding, platform completeness or live money outcomes.',
    'inputs': [{'path': path, 'sha256': digest(ROOT / path)} for path in next_inputs]
}
(OUT / 'acceptance-next-evaluation.json').write_text(json.dumps(next_evaluation, indent=2, ensure_ascii=False) + '\n')

for path in OUT.iterdir():
    if (path.is_file() and path.suffix in {'.json', '.py', '.md', '.png', '.txt'}
            and path.name not in {'acceptance-review.json', 'security-review.json', 'secret-scan.json',
                                  'gitleaks-report.json', 'deployment.json', 'ops-reconciliation.json', 'rollback.json'}):
        paths.add(str(path.relative_to(ROOT)))
paths.update(['scripts/run_e4_review_browser.py', 'tests/e4_payment_expiry_browser.cjs'])
for row in read('ops-release-manifest.json')['inputs']:
    assert digest(ROOT / row['path']) == row['sha256']
    paths.add(row['path'])

report = {
    'schemaVersion': 'e4-payment-expiry-independent-acceptance.v1',
    'result': 'PASS',
    'reviewedAt': datetime.now(timezone.utc).isoformat(),
    'route': 'E4 / PAYMENT_STATUS_EXPIRY_TIME_FORMAT_CONSISTENCY',
    'reviewer': 'Independent acceptance agent; authored fixture/browser/probe evidence, not product or rollout recipe. Primary launched the isolated browser. Reviewer made no production mutation.',
    'decision': 'Accept the bounded single-file inline expiry-helper/timer change for the existing gated reversible Relay rollout. Independent security and operational deployment gates remain separate.',
    'acceptedBehavior': [
        'Supported Z, positive/negative offset and timezone-naive UTC strings identify the same instant in UTC, Asia/Kolkata and America/Los_Angeles. T/space forms and one through six fractional digits are supported by the combined exact-script and browser evidence.',
        'Invalid or missing timestamps show the neutral expiry clarification using textContent. They do not create NaN, Invalid Date, a local expiry, or a countdown interval; existing payment-control policy is preserved.',
        'Invalid calendar dates, hour 24, invalid offsets, excess fraction digits and trailing newline are rejected. The parser bounds type, length and complete-string grammar.',
        'A valid timer reaches zero, removes its interval and retains canonical pending status while existing expired-instruction and receipt behavior renders. A replacement invalid timer clears the old interval.',
        'Canonical terminal/paid/sent states and receipt/verification precedence are unchanged. Polling continues after local expiry; a 503 preserves current state, and stored/sent receipt then paid/sent updates retain existing precedence.'
    ],
    'evidence': {
        'focusedTests': '208 focused tests PASS with exact source/test bindings and raw stdout.',
        'operationsTests': '17 ops tests PASS using disposable fixtures.',
        'exactHandlers': '30 exact current pay outputs from real query_only in-memory SQLite through the exact retained installed read class and unchanged adapter; exact API status/receipt/verification/dead-state cross-check. Synthetic HMAC only, 200 SELECT queries, no provider or money calls.',
        'actualBrowser': '83 grouped checks PASS at 320/390 widths; 27 same-instant comparisons across three timezones. Controlled real Chrome clock exercises countdown and transition behavior. Ten synthetic GET polls, no page errors or blocked requests; non-root sandbox/private-network unit stopped with MainPID 0 and empty cgroup.',
        'independentSecurity': '318 exact-script/security cases PASS; 288 failures on captured baseline establish sensitivity. Independent Python datetime expected epochs cover 22 valid and 46 invalid timestamp cases across three process-local timezones.',
        'sourceBoundary': 'Every main.py byte outside the inline expiry-helper/timer block is identical to captured baseline. All 155 other top-level functions, numeric pay fallback, API/auth/read/redirect/serialization, render/poll logic, callbacks and writers remain unchanged.',
        'operationalReview': 'Single-file recipe independently inspected: 16 retained dependencies remain exact; inline-script scope and Python interpolation identity run in preflight and deploy. Own five inert reconciliation/no-replay cases and separate four disposable rollback/lost-acknowledgement scenarios PASS. Manifest, preflight and three file/journal rollback cases are current and bound.',
        'initialSecretScan': 'Observed staged scan PASS with zero findings and no suppression. Final staging/scan after review creation is independently checked by primary/security; mutable scan output is excluded from recursive input bindings.',
        'visualInspection': ['320-expiry-utc-offset.png', '320-expiry-positive-offset.png', '320-expiry-invalid-calendar.png'],
        'visualFindings': 'At 320 px both aware timestamps display 05:00; invalid February date displays the exact neutral clarification. Countdown and clarification are readable within the payment card without horizontal overflow.'
    },
    'databaseRehearsalDecision': 'No repeated PostgreSQL/container rehearsal: every byte outside inline expiry helper/timer is identical, including query/API/auth/serialization and numeric fallback. No database contract changes are introduced.',
    'nextEvaluation': {
        'artifact': 'docs/e4-payment-expiry/acceptance-next-evaluation.json',
        'additionalConcreteProductDefect': None,
        'nextBoundedWork': 'E4 / MONEY_FLOW_ACCEPTANCE_COVERAGE',
        'entireE4GateClosed': False
    },
    'limitations': [
        'No real customer/order/bearer/proof/provider/wallet/money action or production database was used by the acceptance probes.',
        'Exact handler AST probes use declared exception/redirect wrappers and a false payout-delay fixture rather than the entire ASGI runtime.',
        'Invalid timestamp guidance preserves existing control availability; this slice does not redefine payment-session or money authority.',
        'No real Telegram/iOS/WebKit, assistive-technology or human-comprehension claim, and no claim that the whole historical repository suite passes.',
        'No production deployment or real restart/rollback rehearsal is claimed here. An authorized Relay restart resumes ordinary preexisting background work.'
    ],
    'inputs': [{'path': path, 'sha256': digest(ROOT / path)} for path in sorted(paths)]
}
(OUT / 'acceptance-review.json').write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')
print(json.dumps({'result': 'PASS', 'inputs': len(paths), 'sha256': digest(OUT / 'acceptance-review.json')}))
