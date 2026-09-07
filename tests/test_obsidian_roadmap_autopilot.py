"""Fail-stop lifecycle tests using real isolated Git repos and child processes."""
import importlib.util
import hashlib
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
    (repo / 'docs/ecosystem-master-roadmap.md').write_text('Synthetic roadmap fixture')
    completion = transition(repo, 'E4', 'COMPLETE', 'ROADMAP_COMPLETE')
    (repo / 'docs/completion.json').write_text(json.dumps(completion))
    git(repo, 'add', 'relay/webapp.html', 'docs/evidence.json',
        'docs/ecosystem-master-roadmap.md', 'docs/completion.json')
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
                runtime_verified=True, blocker='', transition_evidence='')


def transition(repo, source='E4', target='E5', basis='VERIFIED_GATE_ADVANCE'):
    return dict(schemaVersion='autonomy-route-transition.v1', fromStage=source,
                toStage=target, basis=basis, scope='EXISTING_AUTHORITY',
                reason='Synthetic transition fixture',
                roadmapSha256=hashlib.sha256((repo / 'docs/ecosystem-master-roadmap.md').read_bytes()).hexdigest(),
                gateAssessments=[dict(stage=stage, status='VERIFIED',
                                     evidencePaths=['docs/evidence.json']) for stage in runner.STAGES])


def attach_transition(repo, result, document):
    (repo / 'docs/transition.json').write_text(json.dumps(document))
    git(repo, 'add', 'docs/transition.json')
    git(repo, 'commit', '-qm', 'transition fixture')
    result.update(commit=git(repo, 'rev-parse', 'HEAD'), transition_evidence='docs/transition.json')
    result['evidence_paths'].append('docs/transition.json')
    return result


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
    ('active_route', 'E5', 'UNSCHEDULED_STAGE'),
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
    receipt['transition_evidence'] = 'docs/completion.json'
    receipt['evidence_paths'].append('docs/completion.json')
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


@pytest.mark.parametrize('stage', runner.STAGES)
def test_all_canonical_stages_can_continue_when_scheduled(environment, stage):
    before = git(environment.repo, 'rev-parse', 'HEAD')
    advance(environment.repo)
    result = receipt(environment.repo)
    result.update(active_route=stage + ' / bounded item', next_step=stage + ' / next item')
    assert runner.validate_receipt(result, environment.repo, before, stage) == 'VERIFIED_NEXT'


def test_unscheduled_stage_cannot_hide_in_same_stage_receipt(environment):
    before = git(environment.repo, 'rev-parse', 'HEAD')
    advance(environment.repo)
    result = receipt(environment.repo)
    result.update(active_route='E5 / unplanned work', next_step='E5 / more work')
    with pytest.raises(ValueError, match='UNSCHEDULED_STAGE'):
        runner.validate_receipt(result, environment.repo, before, 'E4')


def test_stage_change_requires_committed_transition(environment):
    before = git(environment.repo, 'rev-parse', 'HEAD')
    advance(environment.repo)
    result = receipt(environment.repo)
    result['next_step'] = 'E5 / device fixture'
    with pytest.raises(ValueError, match='TRANSITION_EVIDENCE_REQUIRED'):
        runner.validate_receipt(result, environment.repo, before)
    result['transition_evidence'] = 'docs/untracked.json'
    result['evidence_paths'].append('docs/untracked.json')
    (environment.repo / 'docs/untracked.json').write_text('{}')
    with pytest.raises(subprocess.CalledProcessError):
        runner.validate_receipt(result, environment.repo, before)


@pytest.mark.parametrize('basis', ['VERIFIED_GATE_ADVANCE', 'PREPARATION_UNDER_BLOCKER', 'RETURN_TO_EARLIEST'])
def test_evidenced_stage_transitions(environment, basis):
    before = git(environment.repo, 'rev-parse', 'HEAD')
    advance(environment.repo)
    target = 'E0' if basis == 'RETURN_TO_EARLIEST' else 'E5'
    document = transition(environment.repo, target=target, basis=basis)
    if basis != 'VERIFIED_GATE_ADVANCE':
        document['gateAssessments'][0]['status'] = 'BLOCKED_OWNER'
    if basis == 'PREPARATION_UNDER_BLOCKER':
        document.update(scope='KEYLESS_NONPRODUCTION', blocker='064A frozen', productionAllowed=False)
    result = receipt(environment.repo)
    result['next_step'] = target + ' / next canonical fixture'
    attach_transition(environment.repo, result, document)
    assert runner.validate_receipt(result, environment.repo, before) == 'VERIFIED_NEXT'
    assert runner.validate_transition(result, environment.repo) == document['scope']


@pytest.mark.parametrize('defect,reason', [
    ('unverified_earlier', 'EARLIER_GATES_NOT_VERIFIED'),
    ('changed_roadmap', 'TRANSITION_BINDING_INVALID'),
    ('missing_gate', 'ALL_GATE_ASSESSMENTS_REQUIRED'),
    ('wrong_target', 'TRANSITION_BINDING_INVALID'),
    ('self_evidence', 'TRANSITION_IS_NOT_GATE_EVIDENCE'),
    ('aliased_self_evidence', 'TRANSITION_IS_NOT_GATE_EVIDENCE'),
    ('prep_live', 'PREPARATION_BOUNDARY_INVALID'),
    ('prep_no_blocker', 'PREPARATION_BOUNDARY_INVALID'),
    ('return_skip_earliest', 'NOT_EARLIEST_UNMET_GATE'),
])
def test_invalid_transition_cannot_advance(environment, defect, reason):
    before = git(environment.repo, 'rev-parse', 'HEAD')
    advance(environment.repo)
    document = transition(environment.repo)
    result = receipt(environment.repo)
    result['next_step'] = 'E5 / fixture'
    if defect == 'unverified_earlier': document['gateAssessments'][0]['status'] = 'IN_PROGRESS'
    if defect == 'changed_roadmap': document['roadmapSha256'] = '0' * 64
    if defect == 'missing_gate': document['gateAssessments'].pop()
    if defect == 'wrong_target': document['toStage'] = 'E3'
    if defect == 'self_evidence': document['gateAssessments'][0]['evidencePaths'] = ['docs/transition.json']
    if defect == 'aliased_self_evidence': document['gateAssessments'][0]['evidencePaths'] = ['docs/./transition.json']
    if defect.startswith('prep_'):
        document.update(basis='PREPARATION_UNDER_BLOCKER', scope='KEYLESS_NONPRODUCTION',
                        blocker='064A frozen', productionAllowed=defect == 'prep_live')
        if defect != 'prep_no_blocker': document['gateAssessments'][0]['status'] = 'BLOCKED_OWNER'
    if defect == 'return_skip_earliest':
        document.update(toStage='E1', basis='RETURN_TO_EARLIEST')
        document['gateAssessments'][0]['status'] = 'BLOCKED_OWNER'
        result['next_step'] = 'E1 / fixture'
    attach_transition(environment.repo, result, document)
    with pytest.raises(ValueError, match=reason):
        runner.validate_receipt(result, environment.repo, before)


def test_complete_means_all_six_gates(environment):
    before = git(environment.repo, 'rev-parse', 'HEAD')
    result = receipt(environment.repo, 'COMPLETE')
    with pytest.raises(ValueError, match='TRANSITION_EVIDENCE_REQUIRED'):
        runner.validate_receipt(result, environment.repo, before)
    result['transition_evidence'] = 'docs/completion.json'
    result['evidence_paths'].append('docs/completion.json')
    assert runner.validate_receipt(result, environment.repo, before) == 'COMPLETE'
    document = transition(environment.repo, target='COMPLETE', basis='ROADMAP_COMPLETE')
    document['gateAssessments'][0]['status'] = 'BLOCKED_OWNER'
    attach_transition(environment.repo, result, document)
    with pytest.raises(ValueError, match='ROADMAP_GATES_NOT_VERIFIED'):
        runner.validate_receipt(result, environment.repo, before)


def test_keyless_scope_persists_through_same_stage_iteration(environment, monkeypatch):
    document = transition(environment.repo, basis='PREPARATION_UNDER_BLOCKER')
    document.update(scope='KEYLESS_NONPRODUCTION', blocker='fixture owner input missing', productionAllowed=False)
    document['gateAssessments'][0]['status'] = 'BLOCKED_OWNER'
    base = attach_transition(environment.repo, receipt(environment.repo), document)
    worker = environment.package / 'scope_worker.py'
    worker.write_text('''import json,pathlib,subprocess,sys
prompt=sys.stdin.read()
product=pathlib.Path('relay/webapp.html')
old=product.read_text()
result=json.loads(sys.argv[2])
if old == 'baseline':
    assert 'scheduled stage: E4.' in prompt
    result['next_step']='E5 / bounded keyless fixture'
    product.write_text('iteration-one')
else:
    assert 'scheduled stage: E5.' in prompt
    assert 'Allowed scope for this iteration: KEYLESS_NONPRODUCTION.' in prompt
    result.update(active_route='E5 / bounded keyless fixture',next_step='E5 / next fixture',transition_evidence='')
    if old == 'iteration-one':
        product.write_text('iteration-two')
    else:
        result.update(status='BLOCKED',blocker='synthetic stopping point')
if result['status'] != 'BLOCKED':
    subprocess.run(['git','add','relay/webapp.html'],check=True)
    subprocess.run(['git','commit','-qm','bounded fixture'],check=True)
result['commit']=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
pathlib.Path(sys.argv[1]).write_text(json.dumps(result))
''')
    monkeypatch.setattr(runner, 'codex_command', lambda package, output:
                        [sys.executable, str(worker), str(output), json.dumps(base)])
    runner.arm(SimpleNamespace(max_iterations=3, hours=1, start_stage='E4'))
    assert runner.run() == 0
    state = json.loads((environment.state / 'status.json').read_text())
    assert state['status'] == 'BLOCKED'
    assert state['iteration'] == 3
    assert state['scheduled_stage'] == 'E5'
    assert state['continuation_scope'] == 'KEYLESS_NONPRODUCTION'


def test_browser_prerequisite_does_not_require_cosmetic_ui_change(environment):
    before = git(environment.repo, 'rev-parse', 'HEAD')
    (environment.repo / 'scripts').mkdir()
    (environment.repo / 'scripts/run_e4_review_browser.py').write_text('# synthetic implementation fixture')
    git(environment.repo, 'add', 'scripts/run_e4_review_browser.py')
    git(environment.repo, 'commit', '-qm', 'browser prerequisite')
    assert runner.validate_receipt(receipt(environment.repo), environment.repo, before) == 'VERIFIED_NEXT'


def test_account_artifacts_preserves_sources_and_excludes_existing_owner_files(environment, monkeypatch):
    import os

    repo = environment.repo
    owner_file = repo / 'owner-file'
    owner_file.write_text('owner data must not be inspected or copied')
    existing_report = repo / 'output/playwright/previous.json'
    existing_report.parent.mkdir(parents=True)
    existing_report.write_text('previous report must not be inspected or copied')
    baseline = runner.untracked(repo)
    report = repo / 'output/playwright/nested/result.json'
    report.parent.mkdir()
    report.write_bytes(b'{"passed":true}\n')
    screenshot = repo / 'output/playwright/screen.png'
    screenshot.write_bytes(b'\x89PNG\r\nfixture')
    run_dir = environment.state / 'run-artifacts'
    run_dir.mkdir(parents=True, mode=0o700)

    original_path_open, original_os_open = Path.open, os.open
    excluded = {owner_file, existing_report}

    def guarded_path_open(path, *args, **kwargs):
        assert path not in excluded, 'artifact accounting read an existing owner file'
        return original_path_open(path, *args, **kwargs)

    def guarded_os_open(path, *args, **kwargs):
        assert Path(path) not in excluded, 'artifact accounting opened an existing owner file'
        return original_os_open(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, 'open', guarded_path_open)
        patch.setattr(os, 'open', guarded_os_open)
        manifest = runner.account_artifacts(repo, baseline, run_dir)

    expected = {
        str(path.relative_to(repo)): {
            'size': path.stat().st_size,
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for path in (report, screenshot)
    }
    assert manifest['file_count'] == 2
    assert manifest['total_bytes'] == sum(item['size'] for item in expected.values())
    assert {entry['path'] for entry in manifest['files']} == set(expected)
    for entry in manifest['files']:
        assert entry['size'] == expected[entry['path']]['size']
        assert entry['sha256'] == expected[entry['path']]['sha256']
    manifest_path = run_dir / 'artifacts.json'
    assert json.loads(manifest_path.read_text()) == manifest
    assert manifest_path.stat().st_mode & 0o777 == 0o600
    blobs = [path for path in (run_dir / 'artifact-blobs').rglob('*') if path.is_file()]
    assert {hashlib.sha256(path.read_bytes()).hexdigest() for path in blobs} == {
        item['sha256'] for item in expected.values()
    }
    assert all(path.stat().st_mode & 0o777 == 0o600 for path in blobs)
    assert owner_file.read_text() == 'owner data must not be inspected or copied'
    assert existing_report.read_text() == 'previous report must not be inspected or copied'
    assert report.read_bytes() == b'{"passed":true}\n'
    assert screenshot.read_bytes() == b'\x89PNG\r\nfixture'
    assert set(runner.untracked(repo)) == set(baseline) | set(expected)


@pytest.mark.parametrize('name', [
    'relay/new_source.py',
    'output/playwright/accidental-source.py',
    'output/playwright/request.env',
    'output/other/report.json',
])
def test_account_artifacts_rejects_new_source_and_unknown_outputs(environment, name):
    path = environment.repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('must remain visible for inspection')
    run_dir = environment.state / 'run-artifacts'
    run_dir.mkdir(parents=True)
    with pytest.raises(ValueError, match='UNCOMMITTED_NEW_FILES'):
        runner.account_artifacts(environment.repo, [], run_dir)
    assert path.read_text() == 'must remain visible for inspection'


@pytest.mark.parametrize('hazard', ['symlink', 'parent_symlink', 'hardlink', 'fifo'])
def test_account_artifacts_rejects_links_and_special_files(environment, monkeypatch, hazard):
    import os

    report = environment.repo / 'output/playwright/report.json'
    report.parent.mkdir(parents=True)
    private = environment.package / 'private.json'
    private.write_text('outside artifact scope')
    if hazard == 'symlink':
        report.symlink_to(private)
    elif hazard == 'parent_symlink':
        linked = report.parent / 'linked'
        linked.symlink_to(environment.package, target_is_directory=True)
        report = linked / 'private.json'
        monkeypatch.setattr(runner, 'untracked', lambda repo: ['output/playwright/linked/private.json'])
    elif hazard == 'hardlink':
        os.link(private, report)
    else:
        os.mkfifo(report)
    run_dir = environment.state / 'run-artifacts'
    run_dir.mkdir(parents=True)
    with pytest.raises(ValueError, match='UNSAFE_ARTIFACT'):
        if hazard == 'fifo':
            # Git omits FIFOs; the artifact reader must still reject one if a
            # regular file becomes a FIFO between enumeration and opening.
            runner.artifact_bytes(environment.repo, 'output/playwright/report.json')
        else:
            runner.account_artifacts(environment.repo, [], run_dir)
    assert private.read_text() == 'outside artifact scope'
    assert report.exists()


@pytest.mark.parametrize('name,reason', [
    ('/output/playwright/report.json', 'UNCOMMITTED_NEW_FILES'),
    ('output/playwright/../../../outside.json', 'UNSAFE_ARTIFACT'),
])
def test_account_artifacts_rejects_unsafe_paths_before_reading(environment, monkeypatch, name, reason):
    monkeypatch.setattr(runner, 'untracked', lambda repo: [name])
    run_dir = environment.state / 'run-artifacts'
    run_dir.mkdir(parents=True)
    with pytest.raises(ValueError, match=reason):
        runner.account_artifacts(environment.repo, [], run_dir)


@pytest.mark.parametrize('limit,maximum,contents', [
    ('ARTIFACT_MAX_FILE_BYTES', 8, [b'x' * 9]),
    ('ARTIFACT_MAX_BYTES', 9, [b'x' * 5, b'y' * 5]),
    ('ARTIFACT_MAX_FILES', 2, [b'x', b'y', b'z']),
])
def test_account_artifacts_enforces_storage_limits(environment, monkeypatch, limit, maximum, contents):
    monkeypatch.setattr(runner, limit, maximum)
    output = environment.repo / 'output/playwright'
    output.mkdir(parents=True)
    for index, content in enumerate(contents):
        (output / f'report-{index}.json').write_bytes(content)
    run_dir = environment.state / 'run-artifacts'
    run_dir.mkdir(parents=True)
    with pytest.raises(ValueError, match='ARTIFACT_LIMIT_EXCEEDED'):
        runner.account_artifacts(environment.repo, [], run_dir)
    assert [(output / f'report-{index}.json').read_bytes() for index in range(len(contents))] == contents


def test_cli_accepts_a_24_hour_run_without_an_iteration_limit(environment, monkeypatch):
    captured = []
    monkeypatch.setattr(runner, 'arm', captured.append)
    monkeypatch.setattr(sys, 'argv', ['obsidian-roadmap-autopilot', 'arm', '--hours', '24', '--max-iterations', '0'])
    assert runner.main() == 0
    assert len(captured) == 1
    assert captured[0].hours == 24
    assert captured[0].max_iterations == 0


def test_arm_preserves_authorized_next_item_and_keyless_start_scope(environment):
    import time

    started = time.time()
    runner.arm(SimpleNamespace(max_iterations=0, hours=24, start_stage='E5',
                               next_step='E5 / bounded keyless fixture',
                               start_scope='KEYLESS_NONPRODUCTION'))
    armed = json.loads((environment.state / 'armed.json').read_text())
    assert started + 24 * 3600 <= armed['deadline'] <= time.time() + 24 * 3600
    assert armed['max_iterations'] == 0
    assert armed['next_step'] == 'E5 / bounded keyless fixture'
    assert armed['continuation_scope'] == 'KEYLESS_NONPRODUCTION'


def test_time_bounded_run_continues_past_eight_iterations_with_artifacts_and_live_heartbeat(environment, monkeypatch):
    worker = environment.package / 'long_run_worker.py'
    result = receipt(environment.repo)
    prompt_path = environment.package / 'iteration-prompt.md'
    prompt_path.write_text(prompt_path.read_text() + '\nfixture-input-delivery:4e724756\n')
    worker.write_text('''import json, os, pathlib, subprocess, sys, time
prompt = sys.stdin.read()
assert prompt.count('fixture-input-delivery:4e724756') == 1, 'prompt stdin was duplicated'
assert 'Accepted next item: E4 / browser usability' in prompt
receipt_path = pathlib.Path(sys.argv[1])
status_path = pathlib.Path(sys.argv[2])
result = json.loads(sys.argv[3])
initial = json.loads(status_path.read_text())
iteration = initial['iteration']
print('fake worker heartbeat probe', flush=True)
heartbeat_seen = False
deadline = time.monotonic() + 5
while time.monotonic() < deadline:
    state = json.loads(status_path.read_text())
    if (state.get('heartbeat_at') != initial.get('heartbeat_at')
            and state.get('child_pid') == os.getpid()
            and state.get('log_bytes', 0) >= len('fake worker heartbeat probe\\n')
            and 0 < state.get('remaining_seconds', 0) <= 24 * 3600):
        heartbeat_seen = True
        break
    time.sleep(0.01)
assert heartbeat_seen, 'durable heartbeat did not show running child and log growth'
output = pathlib.Path('output/playwright')
output.mkdir(parents=True, exist_ok=True)
(output / ('report-%02d.json' % iteration)).write_text(json.dumps({'iteration':iteration,'heartbeat_seen':True}))
if iteration == 10:
    result.update(status='BLOCKED', blocker='observed fixture needs owner input')
else:
    pathlib.Path('relay/webapp.html').write_text('verified implementation %d' % iteration)
    subprocess.run(['git', 'add', 'relay/webapp.html'], check=True)
    subprocess.run(['git', 'commit', '-qm', 'bounded verified fixture %d' % iteration], check=True)
result['commit'] = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
receipt_path.write_text(json.dumps(result))
''')
    monkeypatch.setattr(runner, 'HEARTBEAT_SECONDS', 0.05)
    monkeypatch.setattr(runner, 'codex_command', lambda package, output:
                        [sys.executable, str(worker), str(output),
                         str(environment.state / 'status.json'), json.dumps(result)])
    runner.arm(SimpleNamespace(max_iterations=0, hours=24, start_stage='E4',
                               next_step='E4 / browser usability',
                               start_scope='CURRENT_AUTHORIZED_SCOPE'))
    assert runner.run() == 0
    state = json.loads((environment.state / 'status.json').read_text())
    assert state['status'] == 'BLOCKED'
    assert state['reason'] == 'observed fixture needs owner input'
    assert state['iteration'] == 10
    assert state['last_accepted_commit'] == git(environment.repo, 'rev-parse', 'HEAD')
    assert (environment.repo / 'relay/webapp.html').read_text() == 'verified implementation 9'
    runs = list(environment.state.glob('run-*'))
    assert len(runs) == 10
    artifact_names = set()
    for run_dir in runs:
        manifest = json.loads((run_dir / 'artifacts.json').read_text())
        assert manifest['file_count'] == 1
        artifact_names.update(entry['path'] for entry in manifest['files'])
    assert artifact_names == {f'output/playwright/report-{index:02d}.json' for index in range(1, 11)}
    assert all(json.loads((environment.repo / name).read_text())['heartbeat_seen'] for name in artifact_names)


def startup_log(path, message='HTTP 503 service unavailable', extra_events=()):
    events = [
        {'type': 'thread.started', 'thread_id': 'synthetic-thread'},
        {'type': 'turn.started'},
        *extra_events,
        {'type': 'error', 'message': message},
        {'type': 'turn.failed', 'error': {'message': message}},
    ]
    path.write_text(''.join(json.dumps(event) + '\n' for event in events))


@pytest.mark.parametrize('message', [
    'HTTP 429 rate limit reached',
    'HTTP 503 service unavailable',
    'upstream connection timed out',
])
def test_safe_startup_retry_accepts_only_transient_failure_without_agent_items(environment, message):
    (environment.repo / 'owner-file').write_text('pre-existing file')
    baseline = runner.untracked(environment.repo)
    before = git(environment.repo, 'rev-parse', 'HEAD')
    log_path = environment.package / 'startup.log'
    startup_log(log_path, message)
    assert runner.safe_startup_retry(log_path, environment.repo, before, baseline) is True
    assert (environment.repo / 'owner-file').read_text() == 'pre-existing file'


@pytest.mark.parametrize('event', [
    {'type': 'item.started', 'item': {'type': 'command_execution', 'command': 'synthetic command'}},
    {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'synthetic response'}},
    {'type': 'tool.started', 'tool': 'synthetic_tool'},
    {'type': 'turn.completed'},
    {'message': 'missing type'},
    ['not', 'an', 'event'],
    None,
])
def test_safe_startup_retry_rejects_items_tools_and_nonstartup_streams(environment, event):
    before = git(environment.repo, 'rev-parse', 'HEAD')
    log_path = environment.package / 'startup.log'
    startup_log(log_path, extra_events=(event,))
    assert runner.safe_startup_retry(log_path, environment.repo, before, []) is False


@pytest.mark.parametrize('message', [
    'HTTP 401 authentication failed',
    'HTTP 403 forbidden',
    'permission denied',
    'temporary permission denied',
    'HTTP 401 authentication failed after upstream HTTP 503',
])
def test_safe_startup_retry_rejects_authentication_and_permission_failures(environment, message):
    log_path = environment.package / 'startup.log'
    startup_log(log_path, message)
    before = git(environment.repo, 'rev-parse', 'HEAD')
    assert runner.safe_startup_retry(log_path, environment.repo, before, []) is False


@pytest.mark.parametrize('defect', ['malformed', 'empty', 'oversize', 'head', 'dirty', 'new_file', 'removed_file'])
def test_safe_startup_retry_rejects_uncertain_logs_and_checkout_changes(environment, defect):
    owner_file = environment.repo / 'owner-file'
    owner_file.write_text('pre-existing file')
    baseline = runner.untracked(environment.repo)
    before = git(environment.repo, 'rev-parse', 'HEAD')
    log_path = environment.package / 'startup.log'
    startup_log(log_path)
    if defect == 'malformed':
        log_path.write_text(log_path.read_text() + 'non-JSON stderr mixed into stream\n')
    elif defect == 'empty':
        log_path.write_text('')
    elif defect == 'oversize':
        log_path.write_text(log_path.read_text() + ' ' * (2 * 1024 * 1024))
    elif defect == 'head':
        advance(environment.repo)
    elif defect == 'dirty':
        (environment.repo / 'relay/webapp.html').write_text('uncommitted change')
    elif defect == 'new_file':
        (environment.repo / 'new-source.py').write_text('new work')
    else:
        owner_file.unlink()
    assert runner.safe_startup_retry(log_path, environment.repo, before, baseline) is False


@pytest.mark.parametrize('suffix', ['.xml', '.csv', '.sarif'])
def test_account_artifacts_retains_nonbrowser_tool_reports(environment, suffix):
    output = environment.repo / 'output/autopilot/run-fixture'
    output.mkdir(parents=True)
    report = output / ('tool-report' + suffix)
    report.write_bytes(b'synthetic nonbrowser report\n')
    run_dir = environment.state / 'run-artifacts'
    run_dir.mkdir(parents=True)
    manifest = runner.account_artifacts(environment.repo, [], run_dir)
    assert manifest['file_count'] == 1
    entry = manifest['files'][0]
    assert entry['path'] == str(report.relative_to(environment.repo))
    assert entry['sha256'] == hashlib.sha256(report.read_bytes()).hexdigest()
    assert entry['size'] == report.stat().st_size
    assert (run_dir / 'artifact-blobs' / entry['sha256']).read_bytes() == report.read_bytes()


def test_autopilot_tool_report_root_does_not_hide_source_files(environment):
    source = environment.repo / 'output/autopilot/uncommitted.py'
    source.parent.mkdir(parents=True)
    source.write_text('source must be reviewed and committed')
    run_dir = environment.state / 'run-artifacts'
    run_dir.mkdir(parents=True)
    with pytest.raises(ValueError, match='UNCOMMITTED_NEW_FILES'):
        runner.account_artifacts(environment.repo, [], run_dir)
    assert source.read_text() == 'source must be reviewed and committed'


@pytest.mark.parametrize('first_attempt_effect', ['none', 'receipt', 'source'])
def test_real_child_startup_retry_is_same_iteration_and_never_replays_observed_effects(environment, monkeypatch, first_attempt_effect):
    worker = environment.package / 'retry_worker.py'
    counter = environment.package / 'attempt-count'
    result = receipt(environment.repo)
    before = git(environment.repo, 'rev-parse', 'HEAD')
    worker.write_text('''import json, pathlib, subprocess, sys
sys.stdin.read()
receipt_path = pathlib.Path(sys.argv[1])
counter = pathlib.Path(sys.argv[2])
effect = sys.argv[3]
result = json.loads(sys.argv[4])
attempt = int(counter.read_text()) + 1 if counter.exists() else 1
counter.write_text(str(attempt))
print(json.dumps({'type':'thread.started', 'thread_id':'synthetic-thread'}))
print(json.dumps({'type':'turn.started'}))
if attempt == 1:
    print(json.dumps({'type':'error', 'message':'HTTP 503 service unavailable'}))
    print(json.dumps({'type':'turn.failed', 'error':{'message':'HTTP 503 service unavailable'}}))
    if effect == 'receipt':
        result.update(status='BLOCKED', blocker='receipt already records observed effects')
        receipt_path.write_text(json.dumps(result))
    if effect == 'source':
        pathlib.Path('relay/uncommitted_source.py').write_text('uncommitted work')
    sys.exit(1)
pathlib.Path('relay/webapp.html').write_text('one verified implementation')
subprocess.run(['git', 'add', 'relay/webapp.html'], check=True)
subprocess.run(['git', 'commit', '-qm', 'one verified implementation'], check=True)
result['commit'] = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
receipt_path.write_text(json.dumps(result))
''')
    monkeypatch.setattr(runner, 'STARTUP_RETRY_DELAYS', (0.01,))
    monkeypatch.setattr(runner, 'HEARTBEAT_SECONDS', 0.005)
    monkeypatch.setattr(runner, 'codex_command', lambda package, output:
                        [sys.executable, str(worker), str(output), str(counter),
                         first_attempt_effect, json.dumps(result)])
    runner.arm(SimpleNamespace(max_iterations=1, hours=1))
    exit_code = runner.run()
    state = json.loads((environment.state / 'status.json').read_text())
    runs = list(environment.state.glob('run-*'))
    assert len(runs) == 1
    assert state['iteration'] == 1
    if first_attempt_effect == 'none':
        assert exit_code == 0
        assert state['status'] == 'LIMIT_REACHED'
        assert counter.read_text() == '2'
        assert state['startup_attempt'] == 2
        assert state['accepted_iterations'] == 1
        assert state['last_accepted_commit'] == git(environment.repo, 'rev-parse', 'HEAD')
        assert git(environment.repo, 'rev-list', '--count', before + '..HEAD') == '1'
        assert (environment.repo / 'relay/webapp.html').read_text() == 'one verified implementation'
        proof = json.loads((runs[0] / 'startup-retry-1.json').read_text())
        assert proof['reason'] == 'TRANSIENT_ENGINE_FAILURE_BEFORE_AGENT_ITEMS'
        assert proof['log_sha256'] == hashlib.sha256((runs[0] / 'codex.log').read_bytes()).hexdigest()
    else:
        assert exit_code == 1
        assert state['status'] == 'FAILED'
        assert state['reason'] == 'CODEX_EXIT_1'
        assert counter.read_text() == '1'
        assert git(environment.repo, 'rev-parse', 'HEAD') == before
        assert (environment.repo / 'relay/webapp.html').read_text() == 'baseline'
        assert not (runs[0] / 'startup-retry-1.json').exists()


def test_startup_retry_backoff_at_deadline_never_launches_a_second_child(environment, monkeypatch):
    import time

    worker = environment.package / 'deadline_retry_worker.py'
    worker.write_text('''import json, sys
sys.stdin.read()
print(json.dumps({'type':'thread.started', 'thread_id':'synthetic-thread'}))
print(json.dumps({'type':'turn.started'}))
print(json.dumps({'type':'error', 'message':'HTTP 503 service unavailable'}))
sys.exit(1)
''')
    launches = []

    def command(package, output):
        launches.append(str(output))
        return [sys.executable, str(worker)]

    monkeypatch.setattr(runner, 'codex_command', command)
    monkeypatch.setattr(runner, 'STARTUP_RETRY_DELAYS', (2,))
    monkeypatch.setattr(runner, 'HEARTBEAT_SECONDS', 0.01)
    arm()
    armed_path = environment.state / 'armed.json'
    armed = json.loads(armed_path.read_text())
    armed['deadline'] = time.time() + 0.5
    runner.atomic_json(armed_path, armed)
    assert runner.run() == 1
    state = json.loads((environment.state / 'status.json').read_text())
    assert state['status'] == 'INTERRUPTED'
    assert state['iteration'] == 1
    assert len(launches) == 1
    run_dir = Path(state['run_dir'])
    assert (run_dir / 'startup-retry-1.json').exists()
    assert (environment.repo / 'relay/webapp.html').read_text() == 'baseline'


def test_artifact_archive_directory_symlink_is_rejected_before_external_write(environment):
    report = environment.repo / 'output/playwright/report.json'
    report.parent.mkdir(parents=True)
    report.write_bytes(b'synthetic report')
    run_dir = environment.state / 'run-artifacts'
    run_dir.mkdir(parents=True)
    outside_archive = environment.package / 'outside-archive'
    outside_archive.mkdir()
    (run_dir / 'artifact-blobs').symlink_to(outside_archive, target_is_directory=True)
    with pytest.raises(ValueError, match='UNSAFE_ARTIFACT_ARCHIVE'):
        runner.account_artifacts(environment.repo, [], run_dir)
    assert list(outside_archive.iterdir()) == []
    assert report.read_bytes() == b'synthetic report'


@pytest.mark.parametrize('hazard', ['symlink', 'fifo', 'hardlink', 'oversized', 'directory', 'public_mode'])
def test_artifact_archive_rejects_unsafe_existing_digest_without_reading_it(environment, monkeypatch, hazard):
    import os

    report = environment.repo / 'output/playwright/report.json'
    report.parent.mkdir(parents=True)
    report.write_bytes(b'report')
    run_dir = environment.state / 'run-artifacts'
    blobs = run_dir / 'artifact-blobs'
    blobs.mkdir(parents=True)
    digest = hashlib.sha256(report.read_bytes()).hexdigest()
    target = blobs / digest
    private = environment.package / 'private-data'
    private.write_bytes(b'secret')
    private.chmod(0o600)
    if hazard == 'symlink':
        target.symlink_to(private)
    elif hazard == 'fifo':
        os.mkfifo(target, mode=0o600)
    elif hazard == 'hardlink':
        os.link(private, target)
    elif hazard == 'directory':
        target.mkdir()
    elif hazard == 'public_mode':
        target.write_bytes(b'secret')
        target.chmod(0o644)
    else:
        target.write_bytes(b'x' * 1024)
        target.chmod(0o600)
    unsafe_stat = target.stat()
    unsafe_inode = (unsafe_stat.st_dev, unsafe_stat.st_ino)
    original_fdopen = os.fdopen

    class GuardedStream:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            self.stream.__enter__()
            return self

        def __exit__(self, *args):
            return self.stream.__exit__(*args)

        def __getattr__(self, name):
            return getattr(self.stream, name)

        def read(self, *args, **kwargs):
            info = os.fstat(self.stream.fileno())
            assert (info.st_dev, info.st_ino) != unsafe_inode, 'unsafe archive inode was read'
            return self.stream.read(*args, **kwargs)

    monkeypatch.setattr(os, 'fdopen', lambda *args, **kwargs: GuardedStream(original_fdopen(*args, **kwargs)))
    with pytest.raises(ValueError, match='UNSAFE_ARTIFACT_ARCHIVE'):
        runner.account_artifacts(environment.repo, [], run_dir)
    assert not (run_dir / 'artifacts.json').exists()
    assert private.read_bytes() == b'secret'
    assert report.read_bytes() == b'report'


def reconciliation_fixture(environment, monkeypatch, scope='CURRENT_AUTHORIZED_SCOPE', runtime_matches=True):
    arm()
    before = git(environment.repo, 'rev-parse', 'HEAD')
    source = environment.repo / 'relay/webapp.html'
    source.write_bytes(b'verified deployed fixture')
    runtime_path = Path('/opt/obsidian-exchange/relay/webapp.html')
    evidence = {'target': str(runtime_path), 'deployedSha256': hashlib.sha256(source.read_bytes()).hexdigest()}
    (environment.repo / 'docs/evidence.json').write_text(json.dumps(evidence))
    git(environment.repo, 'add', 'relay/webapp.html', 'docs/evidence.json')
    git(environment.repo, 'commit', '-qm', 'verified deployed fixture')
    original = receipt(environment.repo)
    report = environment.repo / 'output/playwright/rollout.json'
    report.parent.mkdir(parents=True)
    report.write_text('{"synthetic":true}')
    run_dir = environment.state / 'run-failed'
    run_dir.mkdir()
    runner.atomic_json(run_dir / 'receipt.json', original)
    old = json.loads((environment.state / 'armed.json').read_text())
    old.update(status='FAILED', reason='UNCOMMITTED_NEW_FILES', before=before,
               run_dir=str(run_dir), scheduled_stage='E4', continuation_scope=scope)
    runner.atomic_json(environment.state / 'status.json', old)
    original_read_bytes = Path.read_bytes
    original_is_symlink = Path.is_symlink

    def isolated_runtime_read(path):
        if path == runtime_path:
            return original_read_bytes(source) if runtime_matches else b'different deployed bytes'
        return original_read_bytes(path)

    monkeypatch.setattr(Path, 'read_bytes', isolated_runtime_read)
    monkeypatch.setattr(Path, 'is_symlink', lambda path:
                        False if path == runtime_path else original_is_symlink(path))
    monkeypatch.setattr(runner, 'codex_command', lambda *args: pytest.fail('recovery replayed agent work'))
    return SimpleNamespace(original=original, old=old, report=report)


@pytest.mark.parametrize('scope', ['CURRENT_AUTHORIZED_SCOPE', 'KEYLESS_NONPRODUCTION'])
def test_reconcile_verified_artifact_failure_without_replay_preserves_scope(environment, monkeypatch, scope):
    fixture = reconciliation_fixture(environment, monkeypatch, scope=scope)
    before_recovery = git(environment.repo, 'rev-parse', 'HEAD')
    runner.reconcile_artifacts('docs/evidence.json')
    state = json.loads((environment.state / 'status.json').read_text())
    assert state['status'] == 'RECONCILED'
    assert state['replayed'] is False
    assert state['continuation_scope'] == scope
    assert state['accepted_commit'] == fixture.original['commit']
    assert state['next_step'] == fixture.original['next_step']
    assert state['artifact_count'] == 1
    assert git(environment.repo, 'rev-parse', 'HEAD') == before_recovery
    archive = Path(state['archive'])
    assert json.loads((archive / 'status.json').read_text()) == fixture.old
    assert json.loads((archive / 'receipt.json').read_text()) == fixture.original
    assert json.loads((archive / 'reconciliation.json').read_text()) == state
    assert fixture.report.read_text() == '{"synthetic":true}'


def test_reconcile_runtime_mismatch_preserves_failed_status_and_never_replays(environment, monkeypatch):
    fixture = reconciliation_fixture(environment, monkeypatch, runtime_matches=False)
    with pytest.raises(ValueError, match='RUNTIME_RECONCILIATION_FAILED'):
        runner.reconcile_artifacts('docs/evidence.json')
    assert json.loads((environment.state / 'status.json').read_text()) == fixture.old
    assert not list(environment.state.glob('reconciled-artifacts-*'))
    assert fixture.report.exists()


def test_reconcile_retains_keyless_scope_across_stage_transition(environment, monkeypatch):
    fixture = reconciliation_fixture(environment, monkeypatch, scope='KEYLESS_NONPRODUCTION')
    fixture.original['next_step'] = 'E5 / bounded fixture'
    attach_transition(environment.repo, fixture.original, transition(environment.repo))
    runner.atomic_json(Path(fixture.old['run_dir']) / 'receipt.json', fixture.original)
    runner.reconcile_artifacts('docs/evidence.json')
    state = json.loads((environment.state / 'status.json').read_text())
    assert state['status'] == 'RECONCILED'
    assert state['scheduled_stage'] == 'E5'
    assert state['continuation_scope'] == 'KEYLESS_NONPRODUCTION'
    assert state['replayed'] is False


def usage_limit_fixture(environment, monkeypatch, scope='CURRENT_AUTHORIZED_SCOPE', max_iterations=0):
    runner.arm(SimpleNamespace(max_iterations=max_iterations, hours=24))
    before = git(environment.repo, 'rev-parse', 'HEAD')
    run_dir = environment.state / 'run-quota-3'
    run_dir.mkdir()
    log_path = run_dir / 'codex.log'
    log_path.write_text(json.dumps({'type': 'item.completed', 'item': {'type': 'command_execution'}})
                        + '\n' + json.dumps({'type': 'turn.failed', 'error': {
                            'message': "You've hit your usage limit. Try again later."}}) + '\n')
    old = json.loads((environment.state / 'armed.json').read_text())
    old.update(status='FAILED', reason='CODEX_EXIT_1', child_pid=0, before=before,
               run_dir=str(run_dir), log_path=str(log_path), accepted_iterations=2,
               next_step='E4 / PAYMENT_INSTRUCTION_ISOLATION / finish interrupted work',
               scheduled_stage='E4', continuation_scope=scope, last_accepted_commit=before)
    runner.atomic_json(environment.state / 'status.json', old)
    (environment.repo / 'relay/webapp.html').write_text('unfinished candidate')
    services = {unit: {'ActiveState': 'active', 'MainPID': str(100 + index),
                       'ExecMainStartTimestampMonotonic': str(10000 + index)}
                for index, unit in enumerate(runner.RECOVERY_SERVICES)}
    evidence = {
        'schemaVersion': 'autopilot-usage-limit-recovery.v1',
        'restartAuthorization': 'OWNER_REQUEST_2026_09_07', 'productStatus': 'IN_PROGRESS',
        'previousStatusSha256': hashlib.sha256((environment.state / 'status.json').read_bytes()).hexdigest(),
        'failureLogSha256': hashlib.sha256(log_path.read_bytes()).hexdigest(), 'beforeCommit': before,
        'candidateSha256': hashlib.sha256(b'unfinished candidate').hexdigest(),
        'target': str(runner.RECOVERY_TARGET), 'deployedSha256': hashlib.sha256(b'baseline').hexdigest(),
        'services': services,
    }
    evidence_path = environment.repo / 'docs/recovery.json'
    evidence_path.write_text(json.dumps(evidence))
    git(environment.repo, 'add', 'relay/webapp.html', 'docs/recovery.json')
    git(environment.repo, 'commit', '-qm', 'checkpoint unfinished candidate with recovery evidence')
    original_read = runner.ordinary_bytes
    monkeypatch.setattr(runner, 'ordinary_bytes', lambda path, *args:
                        b'baseline' if path == runner.RECOVERY_TARGET else original_read(path, *args))
    monkeypatch.setattr(runner, 'recovery_service_stopped', lambda: None)
    monkeypatch.setattr(runner, 'service_identity', lambda unit: dict(services[unit]))
    monkeypatch.setattr(runner, 'codex_command', lambda *args: pytest.fail('recovery launched a child'))
    return SimpleNamespace(old=old, run_dir=run_dir, log=log_path, evidence=evidence,
                           evidence_path=evidence_path, services=services)


@pytest.mark.parametrize('scope', ['CURRENT_AUTHORIZED_SCOPE', 'KEYLESS_NONPRODUCTION'])
def test_usage_recovery_preserves_incomplete_work_and_original_budget(environment, monkeypatch, scope):
    fixture = usage_limit_fixture(environment, monkeypatch, scope)
    previous = (environment.state / 'status.json').read_bytes()
    armed = (environment.state / 'armed.json').read_bytes()
    original_log = fixture.log.read_bytes()
    runner.reconcile_usage_limit('docs/recovery.json')
    state = json.loads((environment.state / 'status.json').read_text())
    assert state['status'] == 'RECONCILED'
    assert state['product_status'] == 'IN_PROGRESS'
    assert state['replayed'] is False
    assert state['recovery_evidence'] == 'docs/recovery.json'
    assert not (fixture.run_dir / 'receipt.json').exists()
    archive = Path(state['archive'])
    assert (archive / 'status.json').read_bytes() == previous
    assert (archive / 'armed.json').read_bytes() == armed
    assert (archive / 'runtime-evidence.json').read_bytes() == fixture.evidence_path.read_bytes()
    assert fixture.log.read_bytes() == original_log
    assert list(fixture.run_dir.iterdir()) == [fixture.log]
    assert 'receipt' not in state and 'accepted_commit' not in state
    runner.arm(SimpleNamespace(max_iterations=0, hours=24))
    armed = json.loads((environment.state / 'armed.json').read_text())
    for key in ('deadline', 'max_iterations', 'duration_hours', 'accepted_iterations',
                'next_step', 'continuation_scope', 'last_accepted_commit'):
        assert armed[key] == fixture.old[key]


@pytest.mark.parametrize('second_product_change', [False, True])
def test_usage_recovery_accepts_checkpoint_completion_once_then_requires_new_code(
        environment, monkeypatch, second_product_change):
    fixture = usage_limit_fixture(environment, monkeypatch)
    runner.reconcile_usage_limit('docs/recovery.json')
    runner.arm(SimpleNamespace(max_iterations=0, hours=24))
    checkpoint = git(environment.repo, 'rev-parse', 'HEAD')
    worker = environment.package / 'recovered_worker.py'
    counter = environment.package / 'recovered_worker_count'
    result = receipt(environment.repo)
    worker.write_text('''import json, pathlib, subprocess, sys
prompt = sys.stdin.read()
output, counter = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
iteration = int(counter.read_text()) + 1 if counter.exists() else 1
counter.write_text(str(iteration))
(output.parent / 'received-prompt.txt').write_text(prompt)
receipt = json.loads(sys.argv[3])
if iteration <= 2:
    pathlib.Path('docs/evidence.json').write_text(json.dumps({'completedIteration': iteration}))
    paths = ['docs/evidence.json']
    if iteration == 2 and sys.argv[4] == 'True':
        pathlib.Path('relay/webapp.html').write_text('next bounded product implementation')
        paths.append('relay/webapp.html')
    subprocess.run(['git', 'add', *paths], check=True)
    subprocess.run(['git', 'commit', '-qm', 'finish recovered evidence' if iteration == 1 else 'next slice'], check=True)
else:
    receipt['status'] = 'BLOCKED'
    receipt['blocker'] = 'synthetic stop after verifying subsequent code-first iteration'
receipt['commit'] = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
output.write_text(json.dumps(receipt))
''')
    monkeypatch.setattr(runner, 'codex_command', lambda package, output: [
        sys.executable, str(worker), str(output), str(counter), json.dumps(result),
        str(second_product_change)])
    original_validate = runner.validate_receipt
    validations = []

    def capture_validation(received, repo, before, expected_stage):
        validations.append((before, received['commit']))
        return original_validate(received, repo, before, expected_stage)

    monkeypatch.setattr(runner, 'validate_receipt', capture_validation)
    assert runner.run() == (0 if second_product_change else 1)
    state = json.loads((environment.state / 'status.json').read_text())
    assert validations[0][0] == fixture.old['before']
    assert validations[0][0] != checkpoint
    assert validations[1][0] == validations[0][1]
    assert state['deadline'] == fixture.old['deadline']
    assert state['max_iterations'] == fixture.old['max_iterations']
    assert state['duration_hours'] == fixture.old['duration_hours']
    assert state['scheduled_stage'] == fixture.old['scheduled_stage']
    assert state['continuation_scope'] == fixture.old['continuation_scope']
    assert state['accepted_iterations'] == (4 if second_product_change else 3)
    assert state['status'] == ('BLOCKED' if second_product_change else 'FAILED')
    assert not any(key in state for key in (
        'recovery_kind', 'recovery_before', 'recovery_evidence', 'recovery_evidence_sha256',
        'product_status', 'archive'))
    if not second_product_change:
        assert state['reason'] == 'NO_PRODUCT_CODE_PROGRESS'
    first_run = next(path for path in environment.state.glob('run-*-3') if path != fixture.run_dir)
    prompt = (first_run / 'received-prompt.txt').read_text()
    assert 'docs/recovery.json' in prompt
    assert fixture.old['before'] in prompt


def test_usage_recovery_retains_iteration_limit_then_allows_fresh_explicit_arm(environment, monkeypatch):
    fixture = usage_limit_fixture(environment, monkeypatch, max_iterations=3)
    runner.reconcile_usage_limit('docs/recovery.json')
    runner.arm(SimpleNamespace(max_iterations=3, hours=24))
    worker = environment.package / 'finish_recovered_worker.py'
    result = receipt(environment.repo)
    worker.write_text('''import json, pathlib, subprocess, sys
sys.stdin.read()
pathlib.Path('docs/evidence.json').write_text('{"recoveredCompletion":true}')
subprocess.run(['git', 'add', 'docs/evidence.json'], check=True)
subprocess.run(['git', 'commit', '-qm', 'complete recovered validation and rollout'], check=True)
receipt = json.loads(sys.argv[2])
receipt['commit'] = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
pathlib.Path(sys.argv[1]).write_text(json.dumps(receipt))
''')
    monkeypatch.setattr(runner, 'codex_command', lambda package, output:
                        [sys.executable, str(worker), str(output), json.dumps(result)])
    assert runner.run() == 0
    state = json.loads((environment.state / 'status.json').read_text())
    assert state['status'] == 'LIMIT_REACHED'
    assert state['reason'] == 'explicit iteration limit'
    assert state['iteration'] == state['accepted_iterations'] == 3
    assert state['deadline'] == fixture.old['deadline']
    assert 'recovery_kind' not in state and 'recovery_before' not in state
    assert len(list(environment.state.glob('run-*'))) == 2
    monkeypatch.setattr(runner.time, 'time', lambda: fixture.old['deadline'] + 10)
    runner.arm(SimpleNamespace(max_iterations=1, hours=1))
    armed = json.loads((environment.state / 'armed.json').read_text())
    assert armed['status'] == 'ARMED'
    assert armed['accepted_iterations'] == 0
    assert armed['max_iterations'] == 1 and armed['duration_hours'] == 1
    assert armed['deadline'] > fixture.old['deadline']
    assert 'recovery_kind' not in armed and 'recovery_before' not in armed


@pytest.mark.parametrize('mutation,reason', [
    ('wrong_cause', 'NOT_A_USAGE_LIMIT_FAILURE'),
    ('child_present', 'NOT_A_USAGE_LIMIT_FAILURE'),
    ('receipt', 'FAILED_ITERATION_HAS_RECEIPT'),
    ('log_symlink', 'UNSAFE_RECOVERY_RUN_PATH'),
    ('run_escape', 'UNSAFE_RECOVERY_RUN_PATH'),
    ('log_nonterminal', 'NO_TERMINAL_USAGE_LIMIT_FAILURE'),
    ('log_wrong_cause', 'NO_TERMINAL_USAGE_LIMIT_FAILURE'),
    ('dirty', 'TRACKED_CHECKOUT_DIRTY'),
    ('wrong_product_path', 'RECOVERY_PRODUCT_SCOPE_CHANGED'),
    ('deployed_candidate', 'USAGE_LIMIT_RUNTIME_RECONCILIATION_FAILED'),
    ('service_restart', 'RECOVERY_SERVICE_IDENTITY_DRIFT'),
    ('service_inactive', 'RECOVERY_SERVICE_IDENTITY_DRIFT'),
    ('expired', 'ORIGINAL_RUN_DEADLINE_EXPIRED_OR_CHANGED'),
])
def test_usage_recovery_rejects_uncertain_effects_without_state_change(environment, monkeypatch, mutation, reason):
    fixture = usage_limit_fixture(environment, monkeypatch)
    if mutation in ('wrong_cause', 'child_present', 'run_escape', 'expired'):
        key, value = {
            'wrong_cause': ('reason', 'CODEX_EXIT_2'), 'child_present': ('child_pid', 123),
            'run_escape': ('run_dir', str(environment.repo)), 'expired': ('deadline', 0),
        }[mutation]
        fixture.old[key] = value
        runner.atomic_json(environment.state / 'status.json', fixture.old)
    elif mutation == 'receipt':
        (fixture.run_dir / 'receipt.json').write_text('{}')
    elif mutation == 'log_symlink':
        fixture.log.unlink()
        fixture.log.symlink_to(fixture.evidence_path)
    elif mutation == 'log_nonterminal':
        with fixture.log.open('a') as stream:
            stream.write('{"type":"turn.started"}\n')
    elif mutation == 'log_wrong_cause':
        fixture.log.write_text('{"type":"turn.failed","error":{"message":"approval required"}}\n')
    elif mutation == 'dirty':
        (environment.repo / 'relay/webapp.html').write_text('uncommitted')
    elif mutation == 'wrong_product_path':
        (environment.repo / 'relay/server.py').write_text('new unrelated code')
        git(environment.repo, 'add', 'relay/server.py')
        git(environment.repo, 'commit', '-qm', 'outside recovery scope')
    elif mutation == 'deployed_candidate':
        original_read = runner.ordinary_bytes
        monkeypatch.setattr(runner, 'ordinary_bytes', lambda path, *args:
                            b'unfinished candidate' if path == runner.RECOVERY_TARGET else original_read(path, *args))
    elif mutation.startswith('service_'):
        key, value = ('MainPID', '999') if mutation == 'service_restart' else ('ActiveState', 'inactive')
        fixture.services[runner.RECOVERY_SERVICES[0]][key] = value
    before = (environment.state / 'status.json').read_bytes()
    with pytest.raises(ValueError, match=reason):
        runner.reconcile_usage_limit('docs/recovery.json')
    assert (environment.state / 'status.json').read_bytes() == before
    assert not list(environment.state.glob('reconciled-usage-limit-*'))


@pytest.mark.parametrize('key', ['restartAuthorization', 'productStatus', 'previousStatusSha256',
                               'failureLogSha256', 'beforeCommit', 'candidateSha256', 'deployedSha256'])
def test_usage_recovery_requires_committed_bound_evidence(environment, monkeypatch, key):
    fixture = usage_limit_fixture(environment, monkeypatch)
    del fixture.evidence[key]
    fixture.evidence_path.write_text(json.dumps(fixture.evidence))
    git(environment.repo, 'add', 'docs/recovery.json')
    git(environment.repo, 'commit', '-qm', 'incomplete evidence fixture')
    before = (environment.state / 'status.json').read_bytes()
    with pytest.raises(ValueError, match='USAGE_LIMIT_RUNTIME_RECONCILIATION_FAILED'):
        runner.reconcile_usage_limit('docs/recovery.json')
    assert (environment.state / 'status.json').read_bytes() == before


@pytest.mark.parametrize('mutation', ['expired', 'new_head', 'new_next', 'new_budget'])
def test_usage_recovery_arm_cannot_extend_or_change_reconciled_run(environment, monkeypatch, mutation):
    fixture = usage_limit_fixture(environment, monkeypatch)
    runner.reconcile_usage_limit('docs/recovery.json')
    args = SimpleNamespace(max_iterations=0, hours=24)
    if mutation == 'expired':
        monkeypatch.setattr(runner.time, 'time', lambda: fixture.old['deadline'] + 1)
    elif mutation == 'new_head':
        advance(environment.repo)
    elif mutation == 'new_next':
        args.next_step = 'E4 / something else'
    else:
        args.hours = 1
    before = (environment.state / 'status.json').read_bytes()
    with pytest.raises(ValueError, match='ORIGINAL_RUN_DEADLINE|RECOVERY_ARM_MUST_PRESERVE'):
        runner.arm(args)
    assert (environment.state / 'status.json').read_bytes() == before


def test_usage_recovery_archive_failure_does_not_publish_reconciled(environment, monkeypatch):
    usage_limit_fixture(environment, monkeypatch)
    before = (environment.state / 'status.json').read_bytes()
    original_atomic = runner.atomic_json

    def fail_archive(path, value):
        if path.name == 'reconciliation.json':
            raise OSError('simulated disk failure')
        original_atomic(path, value)

    monkeypatch.setattr(runner, 'atomic_json', fail_archive)
    with pytest.raises(OSError, match='simulated disk failure'):
        runner.reconcile_usage_limit('docs/recovery.json')
    assert (environment.state / 'status.json').read_bytes() == before


@pytest.mark.parametrize('state,pid', [('active', '123'), ('activating', '0'), ('failed', '123')])
def test_usage_recovery_requires_stopped_systemd_service(monkeypatch, state, pid):
    monkeypatch.setattr(runner, 'service_identity', lambda unit: {'ActiveState': state, 'MainPID': pid})
    with pytest.raises(ValueError, match='AUTOPILOT_SERVICE_NOT_STOPPED'):
        runner.recovery_service_stopped()


@pytest.mark.parametrize('hazard', ['stdout', 'fast_stdout', 'stderr', 'combined_logs', 'state_disk', 'repo_disk'])
def test_running_child_resource_failure_stops_without_replaying_effects(environment, monkeypatch, hazard):
    import os

    worker = environment.package / 'resource_worker.py'
    started = environment.package / 'child-started'
    worker.write_text('''import os, pathlib, sys, time
sys.stdin.read()
pathlib.Path(sys.argv[1]).write_text(str(os.getpid()))
hazard = sys.argv[2]
if hazard in ('stdout', 'fast_stdout'):
    print('x' * 120, flush=True)
elif hazard == 'stderr':
    print('x' * 120, file=sys.stderr, flush=True)
elif hazard == 'combined_logs':
    print('x' * 60, flush=True)
    print('y' * 60, file=sys.stderr, flush=True)
if hazard == 'fast_stdout':
    sys.exit(0)
time.sleep(60)
''')
    launches = []

    def command(package, output):
        launches.append(str(output))
        return [sys.executable, str(worker), str(started), hazard]

    original_disk_usage = shutil.disk_usage

    def disk_usage(path):
        failing_path = environment.state if hazard == 'state_disk' else environment.repo
        if hazard.endswith('_disk') and Path(path) == failing_path and started.exists():
            return SimpleNamespace(free=0)
        return original_disk_usage(path)

    monkeypatch.setattr(runner, 'codex_command', command)
    monkeypatch.setattr(runner, 'HEARTBEAT_SECONDS', 0.01)
    monkeypatch.setattr(runner, 'MAX_CHILD_LOG_BYTES', 100)
    monkeypatch.setattr(shutil, 'disk_usage', disk_usage)
    arm()
    assert runner.run() == 1
    state = json.loads((environment.state / 'status.json').read_text())
    assert state['status'] == 'FAILED'
    assert state['reason'] == ('INSUFFICIENT_DISK_SPACE' if hazard.endswith('_disk') else 'LOG_SIZE_LIMIT_EXCEEDED')
    assert state['iteration'] == 1
    assert state['child_pid'] == 0
    assert len(launches) == 1
    assert started.exists()
    with pytest.raises(ProcessLookupError):
        os.kill(int(started.read_text()), 0)
    assert (environment.repo / 'relay/webapp.html').read_text() == 'baseline'
    assert not list(environment.state.glob('run-*/startup-retry-*.json'))


@pytest.mark.parametrize('name', ['deploy/tool.py', 'scripts/prereq.py'])
def test_operational_prerequisite_code_counts_as_verified_progress(environment, name):
    before = git(environment.repo, 'rev-parse', 'HEAD')
    prerequisite = environment.repo / name
    prerequisite.parent.mkdir(parents=True)
    prerequisite.write_text('def preflight():\n    return "synthetic verified operational fixture"\n')
    git(environment.repo, 'add', name)
    git(environment.repo, 'commit', '-qm', 'verified operational prerequisite')
    assert runner.validate_receipt(receipt(environment.repo), environment.repo, before) == 'VERIFIED_NEXT'
