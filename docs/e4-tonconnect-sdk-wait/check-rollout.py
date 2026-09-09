#!/usr/bin/env python3
"""Local-only scope guards and apply/reconcile/rollback rehearsal."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('buy_rollout', HERE / 'rollout.py')
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)
s = r.shared
baseline = subprocess.check_output(['git', 'show', json.loads((HERE / 'ops-baseline.json').read_text())['baselineRevision'] + ':relay/webapp.html'], cwd=r.ROOT)
candidate = (r.ROOT / 'relay/webapp.html').read_bytes()
plan = json.loads((HERE / 'plan.json').read_text())
assert s.sha(baseline) == plan['baseline_sha']
assert s.sha(candidate) == plan['candidate_sha']
checks = []

def reject(name, fn):
    try:
        fn()
    except RuntimeError:
        checks.append(name)
    else:
        raise AssertionError(name + ' accepted')

r.bounded(baseline, candidate)
checks.append('bounded_ton_sdk_wait_scope_accepted')
reject('callback_guard_removal_rejected', lambda: r.bounded(baseline, candidate.replace(b'            if (window.__oeTonConnectFailed) return;\n', b'', 1)))
reject('callback_body_mutation_rejected', lambda: r.bounded(baseline, candidate.replace(b'            const preparing = tcPreparation;', b'            const preparing = null;', 1)))
reject('unrelated_bytes_rejected', lambda: r.bounded(baseline, candidate + b'\n'))
reject('submitBuyOrder_mutation_rejected', lambda: r.bounded(baseline, candidate.replace(b'async function submitBuyOrder(', b'async function changedSubmitBuyOrder(')))
reject('shared_review_mutation_rejected', lambda: r.bounded(baseline, candidate.replace(b'function openExchangeReview(', b'function changedOpenExchangeReview(')))
reject('submitSellOrder_mutation_rejected', lambda: r.bounded(baseline, candidate.replace(b'async function submitSellOrder(', b'async function changedSubmitSellOrder(')))
reject('verification_mutation_rejected', lambda: r.bounded(baseline, candidate.replace(b'async function tcHandleWallet(', b'async function changedTcHandleWallet(')))
reject('buy_refresh_logic_mutation_rejected', lambda: r.bounded(baseline, candidate.replace(b'function applyOfferings(', b'function changedApplyOfferings(')))
reject('recipient_generation_listener_mutation_rejected', lambda: r.bounded(baseline, candidate.replace(b'tcRecipientGeneration += 1;', b'tcRecipientGeneration += 2;')))
reject('empty_candidate_rejected', lambda: r.bounded(baseline, baseline))
with tempfile.TemporaryDirectory(prefix='e4-tonconnect-sdk-wait-rehearsal-') as directory:
    root = Path(directory)
    target, staged, unrelated = root / 'webapp.html', root / 'candidate.html', root / 'unrelated.txt'
    target.write_bytes(baseline)
    target.chmod(0o640)
    staged.write_bytes(candidate)
    unrelated.write_bytes(b'unrelated runtime input')
    fixture_state = {'MainPID': '123', 'ActiveState': 'active', 'SubState': 'running'}
    p = dict(target=str(target), candidate=str(staged), candidate_sha=s.sha(candidate), baseline_sha=s.sha(baseline), metadata=s.metadata(target), scope=s.SCOPE,
             inputs=[{'path': str(target), 'sha256': s.sha(baseline)}, {'path': str(unrelated), 'sha256': s.sha(unrelated.read_bytes())}],
             units=[{'unit': 'fixture.service', 'state': fixture_state}])
    s.unit_state = lambda unit: {'MainPID': '0', 'ActiveState': 'failed'} if unit == 'obsidian-roadmap-autopilot.service' else fixture_state.copy()
    def public_fixture(plan, template):
        assert template == target.read_bytes()
        return s.sha(template)
    s.public = public_fixture
    staged.write_bytes(candidate + b'\n')
    reject('candidate_digest_tamper_rejected', lambda: r.original_execute(p, 'apply', root / 'tamper'))
    staged.write_bytes(candidate)
    unrelated.write_bytes(b'drift')
    reject('unrelated_live_drift_rejected', lambda: r.original_execute(p, 'apply', root / 'drift'))
    unrelated.write_bytes(b'unrelated runtime input')
    target.chmod(0o600)
    reject('target_metadata_drift_rejected', lambda: r.original_execute(p, 'apply', root / 'metadata'))
    target.chmod(0o640)
    original_unit_state = s.unit_state
    s.unit_state = lambda unit: {'MainPID': '99', 'ActiveState': 'active'}
    reject('active_autopilot_rejected', lambda: r.original_execute(p, 'apply', root / 'writer'))
    s.unit_state = lambda unit: original_unit_state(unit) if unit == 'obsidian-roadmap-autopilot.service' else dict(fixture_state, MainPID='124')
    reject('service_state_drift_rejected', lambda: r.original_execute(p, 'apply', root / 'service'))
    s.unit_state = original_unit_state
    applied = r.original_execute(p, 'apply', root / 'backup')
    assert target.read_bytes() == candidate and s.metadata(target) == p['metadata']
    reconciled = r.original_execute(p, 'reconcile', root / 'backup')
    rolled_back = r.original_execute(p, 'rollback', root / 'backup')
    assert target.read_bytes() == baseline and s.metadata(target) == p['metadata']
    assert unrelated.read_bytes() == b'unrelated runtime input'
    checks.extend(['local_atomic_apply_metadata_pass', 'local_reconcile_pass', 'local_exact_rollback_metadata_pass'])
result = dict(result='PASS', checks=checks, baseline_sha=s.sha(baseline), candidate_sha=s.sha(candidate),
              rehearsal={'target':'temporary directory only', 'runtime':'fixture unit states; real drift guards', 'public':'local fixture; real public GET checked separately in prepare', 'production_mutated':False})
(HERE / 'rollout-checks.json').write_text(json.dumps(result, indent=2)+'\n')
print(json.dumps(result, indent=2))
