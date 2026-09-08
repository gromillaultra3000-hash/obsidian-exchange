"""Seal the bounded independent review after all referenced evidence is frozen."""
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


checks = ['acceptance-probe.json', 'acceptance-surface.json', 'acceptance-ops-probe.json',
          'tests.json', 'isolated-postgres.json', 'live-dependency-rehearsal.json',
          'rollback-rehearsal.json', 'preflight.json', 'security-probe.json', 'security-ops-probe.json']
paths = set()
for name in checks:
    item = read(name)
    assert item['result'] == 'PASS', name
    for row in item.get('inputs', []):
        assert digest(ROOT / row['path']) == row['sha256'], (name, row['path'])
        paths.add(row['path'])
for report_name, isolation_name, source_path, runner_path, count in [
        ('browser-report.json', 'browser-isolation.json', 'relay/webapp.html', 'tests/e4_review_browser.cjs', 186),
        ('payment-browser-report.json', 'payment-browser-isolation.json',
         'docs/e4-payment-status-read/acceptance-pages.json', 'tests/e4_payment_status_browser.cjs', 92)]:
    report, isolation = read(report_name), read(isolation_name)
    assert report['result'] == 'PASS' and len(report['checks']) == count
    assert not report['pageErrors']
    assert report['sourceSha256'] == isolation['sourceSha256'] == digest(ROOT / source_path)
    assert report['runnerSha256'] == isolation['runnerSha256'] == digest(ROOT / runner_path)
    assert isolation['processExitCode'] == 0 and isolation['unitStopped'] is True
    assert isolation['chromiumSandbox'] is True and isolation['privateNetwork'] is True
    assert isolation['stopObservation']['MainPID'] == '0' and isolation['stopObservation']['cgroupEmpty'] is True
    paths.update([source_path, runner_path])
assert read('acceptance-probe.json')['count'] == 69
assert read('acceptance-surface.json')['unchangedCount'] == 152
assert '174 passed' in read('tests.json')['summary']
assert '174 passed' in (OUT / 'tests-output.txt').read_text()
assert read('isolated-postgres.json')['cases'] == read('live-dependency-rehearsal.json')['cases'] == 26
assert read('isolated-postgres.json')['containerRemoved'] is True
assert read('isolated-postgres.json')['temporaryDirectoryRemoved'] is True
assert read('isolated-postgres.json')['readOnlyQuerySession'] is True
assert read('next-prerequisite.json')['nextPrerequisite'] == 'PAYMENT_STATUS_TERMINAL_REASON_CONSISTENCY'
for row in read('next-prerequisite.json')['inputs']:
    assert digest(ROOT / row['path']) == row['sha256'], row['path']
    paths.add(row['path'])
for path in OUT.iterdir():
    if (path.is_file() and path.suffix in {'.json', '.py', '.md', '.png', '.txt'}
            and path.name not in {'acceptance-review.json', 'security-review.json', 'gitleaks-report.json', 'secret-scan.json',
                                  'deployment.json', 'ops-reconciliation.json', 'rollback.json'}):
        paths.add(str(path.relative_to(ROOT)))
paths.add('scripts/run_e4_review_browser.py')
manifest = read('ops-release-manifest.json')
for row in manifest['inputs']:
    assert digest(ROOT / row['path']) == row['sha256']
    paths.add(row['path'])
report = {'schemaVersion': 'e4-payment-status-independent-acceptance.v1', 'result': 'PASS',
    'reviewedAt': datetime.now(timezone.utc).isoformat(),
    'route': 'E4 / PAYMENT_STATUS_RUNTIME_READ_CONTRACT',
    'reviewer': 'Independent acceptance agent; did not author product or deployment recipe and did not launch browser or change runtime.',
    'decision': 'Accept this bounded read-contract repair for the existing gated, reversible four-file Relay release. Security review and recipe deployment gates remain separate requirements.',
    'context': {
        'observedBaseline': 'Exact installed order/session/receipt classes lack six read methods. Synthetic query_only SQLite proves existing sent receipt became empty and failed session became not-dead through swallowed helper failures. Public baseline separately observed proofless status/page 500; no actual customer incidence claimed.',
        'minimumDependencyRepair': 'Separate adapter supplies scoped order/session/receipt SELECTs via the retained installed order connection policy; additive proof module restores numeric ownership verification. Provider invoice lookup is excluded because the former status GET branch performed provider calls and payment transitions.',
        'authority': 'Exact Telegram verifier and numeric proof code use synthetic HMAC keys in independent probes. Verified user wins over simultaneous token, including internal subject; foreign/missing/malformed/oversize/expired authority and orphan sessions deny without disclosure.',
        'lifecycle': 'Highest-id sole latest session supplies requisites only in created/invoice_created/awaiting_payment. Stale, unknown, absent, failed, expired and post-payment session states do not authorize another transfer. None promotes the canonical order to paid. Receipt/read failure becomes 503.',
        'compatibility': 'Shared installed order/session/receipt stores are preserved despite checkout drift; the actual installed connection-policy flag is bound disabled. Pure normalization/auth/tx dependencies are pinned. Existing callbacks, workers and all152 other top-level functions retain installed ASTs.'},
    'evidence': {
        'focusedTests': '174 PASS; raw stdout verified; current source/recipe/test bindings checked.',
        'independentHandlers': '69 exact handler/auth/error/receipt/state checks PASS on real SQLite query_only using exact retained installed class;40 exact generated payment pages.',
        'actualDatabases': '26 cases each PASS on retained installed SQLite dependency and PostgreSQL17.11, networkless disposable container, read-only queries and verified cleanup.',
        'actualBrowsers': '186 existing Mini App checks plus92 exact payment-page checks PASS. 320/390 payment layouts, canonical/receipt precedence, stale links, polling,503 preservation, malicious literal clipboard and script-context escaping; no page errors. Both non-root sandboxed private-network units stopped with empty cgroups.',
        'visualInspection': ['320-pay-pending-stored.png', '320-pay-stale.png', '320-pay-failed-absent.png', '320-pay-attack.png'],
        'operations': 'Recipe independently read;5 inert reconciliation/no-replay cases PASS. Separate security operations6 scenarios exercise partial publication and lost restart acknowledgement on disposable files.9 file/journal rollback rehearsal cases PASS; preflight is current and runtimeMutated=false.',
        'sourceBoundary': 'Only _receipt_state, _session_dead, api_order and pay function ASTs changed;152 others unchanged. No provider import or _mark_order_paid call in the two restored public handlers.'},
    'resolvedFindings': [
        'Numeric Unicode digit/proof errors now reject404; internal non-ASCII/oversized key cannot raise an unhandled compare error.',
        'Numeric terminal fallbacks retain final outcomes; closed session with receipt no longer receives an unsupported review-time promise.',
        'Provider JSON cannot close the script context and malicious detail copy remains literal data. Initial trailing-whitespace fixture mismatch was corrected to interior separators; final exact browser PASS is used.',
        'Post-payment session states are excluded from transferable states; neither older active session nor stale bearer revives payment instructions.',
        'Retained pure requisites/origin/freshness dependencies were compared to installed bytes and added to deployment preservation checks.'],
    'historicalTestDisposition': 'Not a claim that the entire historical suite passes. Exact baseline/candidate triage identifies3 existing archived assertion failures and1 candidate stale inventory mismatch after removing old GET provider/read callsites. Archived factory-only capability graph does not model the additive direct adapter; its design authority is not rewritten. Current authority/SQL boundaries are independently exercised by this slice. Frozen historical builder also rejects both baselines before runtime.',
    'nextPrerequisite': {'id': 'PAYMENT_STATUS_TERMINAL_REASON_CONSISTENCY',
        'artifact': 'docs/e4-payment-status-read/next-prerequisite.json',
        'observation': 'Backend-valid canonical failed/cancelled without receipt renders expiry wording on opaque pay. Actual DOM and screenshot prove it. Terminal actions stay suppressed; it is the one bounded subsequent E4 presentation item.'},
    'limitations': ['No live authenticated API/customer/session/provider/wallet/money action or real proof/key was used.',
        'Payment handler probes execute exact ASTs without the whole ASGI runtime; exception/redirect wrappers and payout delay are declared fixtures.',
        'No real iOS/WebKit, assistive technology or human comprehension claim.',
        'Production restart/rollback is not rehearsed. Existing background workers may resume ordinary configured effects after the authorized Relay restart.',
        'No production deployment is claimed by this pre-deployment review.'],
    'inputs': [{'path': path, 'sha256': digest(ROOT / path)} for path in sorted(paths)]}
(OUT / 'acceptance-review.json').write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')
print(json.dumps({'result': 'PASS', 'inputs': len(paths), 'sha256': digest(OUT / 'acceptance-review.json')}))
