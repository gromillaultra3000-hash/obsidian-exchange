"""Fail-stop lifecycle tests using real isolated Git repos and child processes."""
import importlib.util
import json
from pathlib import Path
import shutil
import signal
import subprocess
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('roadmap_runner', ROOT / 'scripts/obsidian_roadmap_autopilot.py')
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args], text=True).strip()


@pytest.fixture
def environment(tmp_path, monkeypatch):
    repo, state, package = (tmp_path / n for n in ('repo', 'state', 'package'))
    repo.mkdir()
    package.mkdir()
    git(repo, 'init', '-q')
    git(repo, 'config', 'user.email', 'test@example.invalid')
    git(repo, 'config', 'user.name', 'Test')
    (repo / 'relay').mkdir()
    (repo / 'docs').mkdir()
    (repo / 'relay/webapp.html').write_text('baseline')
    (repo / 'docs/evidence.json').write_text('{}')
    git(repo, 'add', 'relay/webapp.html', 'docs/evidence.json')
    git(repo, 'commit', '-qm', 'baseline')
    for name in ('iteration-prompt.md', 'iteration.schema.json'):
        shutil.copyfile(ROOT / 'deploy/obsidian-roadmap-autopilot' / name, package / name)
    shutil.copyfile(ROOT / 'scripts/obsidian_roadmap_autopilot.py', package / 'obsidian_roadmap_autopilot.py')
    monkeypatch.setattr(runner, 'REPO', repo)
    monkeypatch.setattr(runner, 'STATE', state)
    monkeypatch.setattr(runner, 'PACKAGE', package)
    monkeypatch.setattr(runner, 'service_other_pids', lambda: set())
    old_handlers = {s: signal.getsignal(s) for s in (signal.SIGTERM, signal.SIGINT)}
    yield SimpleNamespace(repo=repo, state=state, package=package)
    for sig, handler in old_handlers.items():
        signal.signal(sig, handler)


def receipt(repo, status='VERIFIED_NEXT'):
    return dict(status=status, active_route='E4 / recipient review', summary='tested',
                next_step='E4 / browser usability', commit=git(repo, 'rev-parse', 'HEAD'),
                evidence_paths=['docs/evidence.json'], tests_passed=True,
                acceptance_review_passed=True, independent_review_passed=True,
                runtime_verified=True, blocker='')


def advance(repo):
    (repo / 'relay/webapp.html').write_text('updated')
    git(repo, 'add', 'relay/webapp.html')
    git(repo, 'commit', '-qm', 'update')


def arm():
    runner.arm(SimpleNamespace(max_iterations=2, hours=1))


def test_writer_lock_rejects_another_writer(environment):
    with runner.writer_lock(environment.state):
        with pytest.raises(ValueError, match='WRITER_LOCK_HELD'):
            with runner.writer_lock(environment.state):
                pytest.fail('second writer entered')


def test_arm_binds_head_and_package_and_preserves_existing_untracked(environment):
    (environment.repo / 'owner-file').write_text('keep')
    arm()
    armed = json.loads((environment.state / 'armed.json').read_text())
    assert armed['head'] == git(environment.repo, 'rev-parse', 'HEAD')
    assert armed['package_digest'] == runner.package_digest(environment.package)
    assert armed['untracked'] == ['owner-file']
    assert (environment.state / 'armed.json').stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize('status', ['RUNNING', 'STARTING', 'INTERRUPTED', 'FAILED', 'BLOCKED'])
def test_uncertain_previous_run_cannot_be_rearmed(environment, status):
    environment.state.mkdir()
    runner.atomic_json(environment.state / 'status.json', {'status': status})
    with pytest.raises(ValueError, match='INSPECT_PREVIOUS'):
        arm()


def test_changed_checkout_after_arm_stops_without_launch(environment, monkeypatch):
    arm()
    advance(environment.repo)
    monkeypatch.setattr(runner, 'codex_command', lambda *a: pytest.fail('launched'))
    assert runner.run() == 1
    assert json.loads((environment.state / 'status.json').read_text())['status'] == 'FAILED'


@pytest.mark.parametrize('key,value,reason', [
    ('runtime_verified', False, 'ACCEPTANCE_INCOMPLETE'),
    ('tests_passed', 'true', 'INVALID_RECEIPT_CHECK_TYPES'),
    ('active_route', 'E5', 'ROUTE_CHANGED'),
    ('evidence_paths', ['docs/../relay/webapp.html'], 'UNSAFE_EVIDENCE_PATH'),
    ('evidence_paths', ['/etc/passwd'], 'UNSAFE_EVIDENCE_PATH'),
    ('commit', '0' * 40, 'COMMIT_OR_EVIDENCE_MISSING'),
])
def test_bad_receipt_cannot_continue(environment, key, value, reason):
    before = git(environment.repo, 'rev-parse', 'HEAD')
    advance(environment.repo)
    result = receipt(environment.repo)
    result[key] = value
    with pytest.raises(ValueError, match=reason):
        runner.validate_receipt(result, environment.repo, before)


def test_same_commit_and_docs_only_progress_do_not_continue(environment):
    before = git(environment.repo, 'rev-parse', 'HEAD')
    with pytest.raises(ValueError, match='NO_VERIFIED_PROGRESS'):
        runner.validate_receipt(receipt(environment.repo), environment.repo, before)
    (environment.repo / 'docs/evidence.json').write_text('{"new":true}')
    git(environment.repo, 'add', 'docs/evidence.json')
    git(environment.repo, 'commit', '-qm', 'docs only')
    with pytest.raises(ValueError, match='NO_PRODUCT_CODE_PROGRESS'):
        runner.validate_receipt(receipt(environment.repo), environment.repo, before)


def test_uncommitted_evidence_cannot_continue(environment):
    before = git(environment.repo, 'rev-parse', 'HEAD')
    advance(environment.repo)
    (environment.repo / 'docs/new.json').write_text('{}')
    result = receipt(environment.repo)
    result['evidence_paths'] = ['docs/new.json']
    with pytest.raises(subprocess.CalledProcessError):
        runner.validate_receipt(result, environment.repo, before)


def test_blocked_receipt_stops_with_reason(environment):
    result = receipt(environment.repo, 'BLOCKED')
    with pytest.raises(ValueError, match='BLOCKED_WITHOUT_REASON'):
        runner.validate_receipt(result, environment.repo, result['commit'])
    result['blocker'] = 'sandbox unavailable'
    assert runner.validate_receipt(result, environment.repo, result['commit']) == 'BLOCKED'


@pytest.mark.parametrize('mode,expected', [('blocked', 'BLOCKED'), ('malformed', 'FAILED'), ('exit', 'FAILED')])
def test_real_child_failure_never_starts_a_second_iteration(environment, monkeypatch, mode, expected):
    worker = environment.package / 'fake_worker.py'
    result = receipt(environment.repo, 'BLOCKED')
    result['blocker'] = 'observed fixture blocker'
    worker.write_text('''import json, pathlib, sys
sys.stdin.read()
pathlib.Path(sys.argv[2]).write_text('launched')
if sys.argv[3] == 'exit': sys.exit(7)
pathlib.Path(sys.argv[1]).write_text('broken' if sys.argv[3] == 'malformed' else sys.argv[4])
''')
    def command(package, output):
        return [sys.executable, str(worker), str(output), str(output.parent / 'started'), mode, json.dumps(result)]
    monkeypatch.setattr(runner, 'codex_command', command)
    arm()
    runner.run()
    state = json.loads((environment.state / 'status.json').read_text())
    assert state['status'] == expected
    assert state['iteration'] == 1
    assert len(list(environment.state.glob('run-*'))) == 1
    with pytest.raises(ValueError, match='NOT_FRESHLY_ARMED'):
        runner.run()


def test_codex_command_preserves_sandbox_and_automatic_approval(environment):
    command = runner.codex_command(environment.package, environment.state / 'out.json')
    assert '--approve-for-me' in command
    assert '--ignore-rules' not in command
    assert '--ignore-user-config' not in command
    assert not any('bypass' in arg or 'danger-full-access' in arg for arg in command)


def test_detached_descendant_blocks_next_iteration(environment, monkeypatch):
    import os
    worker = environment.package / 'detached_worker.py'
    pidfile = environment.package / 'descendant.pid'
    result = receipt(environment.repo, 'BLOCKED')
    result['blocker'] = 'fixture'
    worker.write_text('''import pathlib, subprocess, sys
sys.stdin.read()
child = subprocess.Popen(['sleep', '60'], start_new_session=True)
pathlib.Path(sys.argv[2]).write_text(str(child.pid))
pathlib.Path(sys.argv[1]).write_text(sys.argv[3])
''')
    monkeypatch.setattr(runner, 'codex_command', lambda package, output:
                        [sys.executable, str(worker), str(output), str(pidfile), json.dumps(result)])
    # The real host uses the dedicated systemd cgroup, including setsid children.
    monkeypatch.setattr(runner, 'service_other_pids', lambda:
                        {int(pidfile.read_text())} if pidfile.exists() else set())
    arm()
    try:
        assert runner.run() == 1
        state = json.loads((environment.state / 'status.json').read_text())
        assert state['reason'] == 'DETACHED_ITERATION_DESCENDANTS_REMAIN'
        assert state['iteration'] == 1
    finally:
        # In production systemd KillMode=control-group performs this cleanup.
        if pidfile.exists():
            os.kill(int(pidfile.read_text()), signal.SIGTERM)


def test_verified_iteration_can_continue_once_then_complete(environment, monkeypatch):
    worker = environment.package / 'successful_worker.py'
    result = receipt(environment.repo)
    worker.write_text('''import json, pathlib, subprocess, sys
sys.stdin.read()
repo = pathlib.Path.cwd()
product = repo / 'relay/webapp.html'
receipt = json.loads(sys.argv[2])
if product.read_text() == 'baseline':
    product.write_text('tested implementation')
    subprocess.run(['git', 'add', 'relay/webapp.html'], check=True)
    subprocess.run(['git', 'commit', '-qm', 'bounded slice'], check=True)
else:
    receipt['status'] = 'COMPLETE'
receipt['commit'] = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
pathlib.Path(sys.argv[1]).write_text(json.dumps(receipt))
''')
    monkeypatch.setattr(runner, 'codex_command', lambda package, output:
                        [sys.executable, str(worker), str(output), json.dumps(result)])
    arm()
    assert runner.run() == 0
    state = json.loads((environment.state / 'status.json').read_text())
    assert state['status'] == 'COMPLETE'
    assert state['iteration'] == 2


def test_timeout_stops_child_and_requires_inspection(environment, monkeypatch):
    import time
    worker = environment.package / 'slow_worker.py'
    worker.write_text('import sys,time\nsys.stdin.read()\ntime.sleep(60)\n')
    monkeypatch.setattr(runner, 'codex_command', lambda *a: [sys.executable, str(worker)])
    arm()
    armed_path = environment.state / 'armed.json'
    armed = json.loads(armed_path.read_text())
    armed['deadline'] = time.time() + 0.5
    runner.atomic_json(armed_path, armed)
    assert runner.run() == 1
    assert json.loads((environment.state / 'status.json').read_text())['status'] == 'INTERRUPTED'
    with pytest.raises(ValueError, match='INSPECT_PREVIOUS'):
        arm()
