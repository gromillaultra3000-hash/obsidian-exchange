#!/usr/bin/env python3
"""Inert rehearsal of exact two-file bot rollout and failed/partial rollback."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('website_rollout', HERE / 'rollout.py')
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)
s = r.s
checks = []


def reject(name, callback):
    try:
        callback()
    except RuntimeError:
        checks.append(name)
    else:
        raise AssertionError(name + ' accepted')


plan = json.loads((HERE / 'plan.json').read_text())
r.validate(plan)
checks.append('real_plan_validation')
for key in ('inventory_sha', 'helper_sha', 'rollout_sha', 'inputs', 'units'):
    changed = copy.deepcopy(plan)
    changed[key] = 'tampered'
    reject(key + '_tamper_rejected', lambda: r.validate(changed))
changed = copy.deepcopy(plan)
changed['targets'][1]['target'] = '/tmp/outside-scope'
reject('target_scope_tamper_rejected', lambda: r.validate(changed))
with tempfile.TemporaryDirectory(prefix='e4-site-rollout-') as directory:
    root = Path(directory)
    live, candidates = root / 'live', root / 'candidates'
    live.mkdir(); candidates.mkdir()
    unrelated = root / 'unrelated'
    unrelated.write_bytes(b'unrelated')
    fixture = copy.deepcopy(plan)
    fixture['inputs'] = [{'path': str(unrelated), 'sha256': s.sha(b'unrelated')}]
    for i, entry in enumerate(fixture['targets']):
        name = Path(entry['target']).name
        before = None if i == 0 else Path(entry['target']).read_bytes()
        after = Path(entry['candidate']).read_bytes()
        target, candidate = live / name, candidates / name
        if before is not None:
            target.write_bytes(before); target.chmod(0o640)
        candidate.write_bytes(after)
        entry.update(target=str(target), candidate=str(candidate), metadata=dict(mode=0o640, uid=root.stat().st_uid, gid=root.stat().st_gid, xattrs={}))
    # Production path/hash binding above; only fixture location binding bypassed here.
    r.validate = lambda p: None
    real_state = {e['unit']: e['state'] for e in fixture['units']}
    s.unit_state = lambda unit: {'MainPID': '0', 'ActiveState': 'failed'} if unit == 'obsidian-roadmap-autopilot.service' else real_state[unit].copy()
    r.public = lambda: [{'fixture': True}]
    r.candidate_check = lambda: None  # Actual compile/Jinja checks run in prepare.
    restarts = []
    def fake_restart(command, **kwargs):
        assert command == ['systemctl', 'restart', r.UNIT]
        if not restarts:
            assert all(r.digest(Path(e['target'])) == e['candidate_sha'] for e in fixture['targets'])
        restarts.append(command)
        state = real_state[r.UNIT].copy()
        state['MainPID'] = str(int(state['MainPID']) + 1)
        state.update(ActiveState='active', SubState='running')
        real_state[r.UNIT] = state
    r.subprocess.run = fake_restart
    candidate = Path(fixture['targets'][1]['candidate'])
    saved = candidate.read_bytes(); candidate.write_bytes(saved + b'tamper')
    reject('candidate_digest_tamper_rejected', lambda: r.execute(fixture, 'apply', root / 'bad-candidate'))
    candidate.write_bytes(saved)
    unrelated.write_bytes(b'drift')
    reject('unrelated_input_drift_rejected', lambda: r.execute(fixture, 'apply', root / 'bad-unrelated'))
    unrelated.write_bytes(b'unrelated')
    target = Path(fixture['targets'][1]['target']); target.chmod(0o600)
    reject('metadata_drift_rejected', lambda: r.execute(fixture, 'apply', root / 'bad-metadata'))
    target.chmod(0o640)
    unit_state = s.unit_state
    s.unit_state = lambda unit: {'MainPID': '99', 'ActiveState': 'active'}
    reject('active_autopilot_rejected', lambda: r.execute(fixture, 'apply', root / 'bad-writer'))
    s.unit_state = lambda unit: unit_state(unit) if unit == 'obsidian-roadmap-autopilot.service' else dict(unit_state(unit), MainPID='999')
    reject('runtime_identity_drift_rejected', lambda: r.execute(fixture, 'apply', root / 'bad-runtime'))
    s.unit_state = unit_state
    r.execute(fixture, 'apply', root / 'backup')
    r.execute(fixture, 'reconcile', root / 'backup')
    assert len(restarts) == 1
    checks.extend(['two_file_apply_metadata_pass', 'reconcile_pass_without_restart', 'only_bot_restarted_once', 'both_files_installed_before_bot_restart'])
    saved_backup = root / 'backup' / target.name
    saved = saved_backup.read_bytes(); saved_backup.write_bytes(b'bad')
    reject('corrupt_backup_rejected', lambda: r.execute(fixture, 'rollback', root / 'backup'))
    saved_backup.write_bytes(saved)
    real_state[r.UNIT] = dict(real_state[r.UNIT], MainPID='0', ActiveState='failed', SubState='failed')
    r.execute(fixture, 'rollback', root / 'backup')
    assert all(not (live / Path(n).name).exists() for n in r.NAMES[:1])
    assert len(restarts) == 2
    checks.append('failed_bot_rollback_removes_helper_preserves_metadata_restarts_bot')
    next(u for u in fixture['units'] if u['unit'] == r.UNIT)['state'] = real_state[r.UNIT].copy()
    atomic = s.atomic
    for fail_after in (1,):
        calls = []
        def fail(path, data, meta):
            if len(calls) == fail_after:
                raise RuntimeError('Injected between-file interruption')
            calls.append(str(path)); atomic(path, data, meta)
        s.atomic = fail
        backup = root / ('partial-' + str(fail_after))
        reject('interruption_after_' + str(fail_after), lambda: r.execute(fixture, 'apply', backup))
        s.atomic = atomic
        r.execute(fixture, 'rollback', backup)
        next(u for u in fixture['units'] if u['unit'] == r.UNIT)['state'] = real_state[r.UNIT].copy()
        checks.append('partial_' + str(fail_after) + '_rollback_pass')
    assert unrelated.read_bytes() == b'unrelated'
result = dict(result='PASS', checks=checks, production_mutated=False,
              limitations='Temporary filesystem; fixture service identities and public responses. Real plan binding checked separately; single bot PID checked in prepare.')
s.write_json(HERE / 'rollout-checks.json', result)
print(json.dumps(result, indent=2))
