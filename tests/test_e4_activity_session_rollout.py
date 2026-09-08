"""Exercise deployment interruption and rollback against disposable files only."""
import copy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def ops(tmp_path, monkeypatch):
    source = Path(__file__).resolve().parents[1] / 'deploy/e4_activity_session_rollout.py'
    spec = importlib.util.spec_from_file_location('e4_session_ops_test', source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for name, suffix in [('REPO', 'repository'), ('LIVE', 'live'),
                         ('ROOT', 'output'), ('DOCS', 'docs'), ('PREIMAGES', 'preimages')]:
        folder = tmp_path / suffix
        folder.mkdir()
        monkeypatch.setattr(module, name, folder)
    monkeypatch.setattr(module, 'STATE', module.ROOT / 'deployment-state.json')
    monkeypatch.setattr(module, 'MANIFEST', module.DOCS / 'ops-release-manifest.json')
    old = {module.MAIN: b'value = 1\n', module.HTML: b'old template\n', module.MODULE: None}
    new = {module.MAIN: b'value = 2\n', module.HTML: b'new template\n', module.MODULE: b'value = 3\n'}
    monkeypatch.setattr(module, 'BASELINE', {
        path: None if value is None else module.sha(value) for path, value in old.items()})
    for path in module.FILES:
        candidate = module.REPO / path
        candidate.parent.mkdir(parents=True, exist_ok=True)
        candidate.write_bytes(new[path])
        target = module.LIVE / path
        target.parent.mkdir(parents=True, exist_ok=True)
        if old[path] is not None:
            target.write_bytes(old[path])
            target.chmod(0o640)
            baseline = module.ROOT / 'baseline' / path
            baseline.parent.mkdir(parents=True, exist_ok=True)
            baseline.write_bytes(old[path])
    recipe = module.REPO / module.RECIPE
    recipe.parent.mkdir(parents=True, exist_ok=True)
    recipe.write_bytes(source.read_bytes())
    preserved = module.LIVE / 'preserved.py'
    preserved.write_bytes(b'unchanged')
    monkeypatch.setattr(module, 'PRESERVED', {'preserved.py': module.sha(b'unchanged')})
    snapshots = {name: {'MainPID': str(100 + index), 'ActiveState': 'active',
                       'SubState': 'running', 'NRestarts': '0',
                       'ExecMainStartTimestamp': '2026-09-01 00:00:00 UTC'}
                 for index, name in enumerate(module.SERVICES)}
    monkeypatch.setattr(module, 'services', lambda require_active=True: copy.deepcopy(snapshots))
    monkeypatch.setattr(module, 'autopilot_stopped', lambda: {'ActiveState': 'failed', 'MainPID': '0'})
    monkeypatch.setattr(module, 'gates', lambda candidate: None)
    monkeypatch.setattr(module, 'public_check', lambda template: [{'digest': module.sha(template)}])
    calls = []

    def run(command, **kwargs):
        assert command == ['systemctl', 'restart', '--no-block', 'relay-fastapi.service']
        calls.append(command)
        relay = snapshots[module.SERVICES[0]]
        relay['MainPID'] = str(int(relay['MainPID']) + 10)
        relay['ExecMainStartTimestamp'] = 'restart ' + str(len(calls))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(module.subprocess, 'run', run)
    module.bind()
    module.preflight()
    return SimpleNamespace(module=module, calls=calls, snapshots=snapshots, old=old, new=new)


def test_complete_deploy_reconcile_and_exact_rollback(ops):
    m = ops.module
    before = {path: m.metadata(m.LIVE / path) for path in (m.MAIN, m.HTML)}
    assert m.rehearse()['result'] == 'PASS'
    assert m.deploy()['state'] == 'VERIFIED'
    assert len(ops.calls) == 1
    assert all((m.LIVE / path).read_bytes() == ops.new[path] for path in m.FILES)
    assert m.reconcile()['next'] == 'Terminal state verified; no runtime action.'
    assert len(ops.calls) == 1
    assert m.rollback()['state'] == 'ROLLED_BACK'
    assert len(ops.calls) == 2
    assert not (m.LIVE / m.MODULE).exists()
    for path in (m.MAIN, m.HTML):
        assert (m.LIVE / path).read_bytes() == ops.old[path]
        after = m.metadata(m.LIVE / path)
        assert all(after[key] == before[path][key] for key in ('uid', 'gid', 'mode', 'mtimeNs', 'xattrs'))
    assert m.reconcile()['journalState'] == 'ROLLED_BACK'
    with pytest.raises(RuntimeError, match='already_terminal'):
        m.rollback()


@pytest.mark.parametrize('boundary', [0, 1, 2, 3])
def test_interrupted_deployment_is_observed_and_can_be_explicitly_rolled_back(ops, monkeypatch, boundary):
    m = ops.module
    original = m.replace
    original_restart = m.restart_relay
    applied = 0

    def interrupted(*args, **kwargs):
        nonlocal applied
        if applied == boundary:
            raise RuntimeError('synthetic interruption')
        original(*args, **kwargs)
        applied += 1

    monkeypatch.setattr(m, 'replace', interrupted)
    if boundary == 3:
        monkeypatch.setattr(m, 'restart_relay', lambda *args: (_ for _ in ()).throw(RuntimeError('synthetic interruption')))
    with pytest.raises(RuntimeError, match='synthetic interruption'):
        m.deploy()
    before = {path: m.file_state(m.LIVE / path) for path in m.FILES}
    assert m.reconcile()['result'] == 'OBSERVED_NO_REPLAY'
    assert before == {path: m.file_state(m.LIVE / path) for path in m.FILES}
    assert not ops.calls
    with pytest.raises(RuntimeError, match='never_repeat_deployment'):
        m.deploy()
    monkeypatch.setattr(m, 'replace', original)
    monkeypatch.setattr(m, 'restart_relay', original_restart)
    assert m.rollback()['state'] == 'ROLLED_BACK'
    assert len(ops.calls) == 1


def test_candidate_changed_after_preflight_is_rejected_before_runtime_change(ops):
    m = ops.module
    (m.REPO / m.MAIN).write_bytes(b'value = 99\n')
    with pytest.raises(RuntimeError, match='input_changed'):
        m.deploy()
    assert not m.STATE.exists()
    assert not ops.calls


def test_preserved_live_drift_rejects_deploy(ops):
    m = ops.module
    (m.LIVE / 'preserved.py').write_bytes(b'changed')
    with pytest.raises(RuntimeError, match='preserved_file_drift'):
        m.deploy()
    assert not m.STATE.exists()
    assert not ops.calls


def test_unrelated_service_change_rejects_deploy_before_mutation(ops):
    m = ops.module
    ops.snapshots['exchange-bot.service']['MainPID'] = '999'
    with pytest.raises(RuntimeError, match='service_changed_since_preflight'):
        m.deploy()
    assert not m.STATE.exists()
    assert not ops.calls


def test_unknown_runtime_bytes_refuse_reconciliation_and_rollback(ops):
    m = ops.module
    m.deploy()
    (m.LIVE / m.MAIN).write_bytes(b'unknown bytes')
    for action in (m.reconcile, m.rollback):
        with pytest.raises(RuntimeError, match='unknown_runtime_bytes'):
            action()
    assert len(ops.calls) == 1


def test_changed_preimage_refuses_rollback(ops):
    m = ops.module
    report = m.deploy()
    (Path(report['rollbackDirectory']) / m.MAIN).write_bytes(b'unknown bytes')
    with pytest.raises(RuntimeError, match='preimage_changed'):
        m.rollback()
    assert len(ops.calls) == 1


def test_interrupted_rollback_is_never_blindly_replayed(ops, monkeypatch):
    m = ops.module
    m.deploy()
    monkeypatch.setattr(m, 'replace', lambda *args: (_ for _ in ()).throw(RuntimeError('synthetic interruption')))
    with pytest.raises(RuntimeError, match='synthetic interruption'):
        m.rollback()
    reconciliation = m.reconcile()
    assert reconciliation['journalState'] == 'ROLLBACK_PREPARED'
    assert 'independent inspection and manual completion' in reconciliation['next']
    with pytest.raises(RuntimeError, match='independent_reconciliation_no_replay'):
        m.rollback()
    assert len(ops.calls) == 1


def test_new_module_is_retained_until_old_main_restart_succeeds(ops, monkeypatch):
    m = ops.module
    m.deploy()

    def interrupted_restart(report, state):
        assert (m.LIVE / m.MAIN).read_bytes() == ops.old[m.MAIN]
        assert (m.LIVE / m.MODULE).read_bytes() == ops.new[m.MODULE]
        raise RuntimeError('synthetic restart interruption')

    monkeypatch.setattr(m, 'restart_relay', interrupted_restart)
    with pytest.raises(RuntimeError, match='synthetic restart interruption'):
        m.rollback()
    assert (m.LIVE / m.MODULE).exists()
    assert len(ops.calls) == 1


def test_symlink_and_wrong_expected_digest_are_refused(ops, tmp_path):
    m = ops.module
    target = m.LIVE / m.MAIN
    link = tmp_path / 'link'
    link.symlink_to(target)
    with pytest.raises(RuntimeError, match='symlink_refused'):
        m.file_state(link)
    with pytest.raises(RuntimeError, match='target_changed'):
        m.replace(target, 'wrong', b'new', m.metadata(target))
    assert target.read_bytes() == ops.old[m.MAIN]


def test_active_autopilot_rejected_without_service_mutation(ops, monkeypatch):
    m = ops.module
    # Use the real guard while retaining fake systemd data.
    spec = importlib.util.spec_from_file_location('e4_session_ops_guard', Path(__file__).resolve().parents[1] / m.RECIPE)
    original = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(original)
    monkeypatch.setattr(original, 'unit_state', lambda _: {'ActiveState': 'active', 'MainPID': '10'})
    with pytest.raises(RuntimeError, match='autopilot_is_writer'):
        original.autopilot_stopped()
    assert not ops.calls
