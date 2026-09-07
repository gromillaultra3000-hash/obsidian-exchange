#!/usr/bin/env python3
"""Serial, fail-stop Codex delivery supervised by systemd, independent of SSH.

No credentials are copied and no sandbox/approval rules are bypassed. A fresh
explicit arm binds the next run to a clean tracked checkout. Interrupted runs
are never resumed automatically: their effects require human/agent inspection.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import shutil
import stat
import subprocess
import sys
import tempfile
import time

REPO = Path('/root')
STATE = Path('/var/lib/obsidian-roadmap-autopilot')
PACKAGE = Path(__file__).resolve().parent
CODEX = Path('/root/.local/bin/codex')
RECEIPT_KEYS = {
    'status', 'active_route', 'summary', 'next_step', 'commit', 'evidence_paths',
    'tests_passed', 'acceptance_review_passed', 'independent_review_passed',
    'runtime_verified', 'blocker',
    'transition_evidence',
}
CHECKS = ('tests_passed', 'acceptance_review_passed',
          'independent_review_passed', 'runtime_verified')
STAGES = tuple(f'E{index}' for index in range(6))
HEARTBEAT_SECONDS = 30
ARTIFACT_MAX_FILE_BYTES = 64 * 1024 * 1024
ARTIFACT_MAX_BYTES = 256 * 1024 * 1024
ARTIFACT_MAX_FILES = 512
MIN_FREE_BYTES = 1024 * 1024 * 1024
MAX_CHILD_LOG_BYTES = 128 * 1024 * 1024
STARTUP_RETRY_DELAYS = (30, 120, 300)
ARTIFACT_SUFFIXES = {'.json', '.png', '.jpg', '.jpeg', '.webp', '.txt', '.log', '.html', '.zip', '.xml', '.csv', '.sarif'}
ARTIFACT_ROOTS = (('output', 'playwright'), ('output', 'autopilot'))


def now():
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path, value):
    fd, name = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=path.parent)
    temporary = Path(name)
    with os.fdopen(fd, 'w', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args],
                                   text=True, timeout=30).strip()


def clean_checkout(repo):
    if git(repo, 'status', '--porcelain', '--untracked-files=no'):
        raise ValueError('TRACKED_CHECKOUT_DIRTY')
    return git(repo, 'rev-parse', 'HEAD')


def untracked(repo):
    return sorted(filter(None, git(repo, 'ls-files', '--others',
                                   '--exclude-standard', '-z').split('\0')))


def artifact_bytes(repo, name):
    """Read only an ordinary bounded artifact, without following any link."""
    parts = Path(name).parts
    if (len(parts) < 3 or parts[:2] not in ARTIFACT_ROOTS
            or Path(name).as_posix() != name
            or any(not re.fullmatch(r'[A-Za-z0-9_.-]+', p) or p in ('.', '..') for p in parts)):
        raise ValueError('UNSAFE_ARTIFACT')
    directory = os.open(repo, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            following = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = following
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        with os.fdopen(fd, 'rb') as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
                raise ValueError('UNSAFE_ARTIFACT')
            if before.st_size > ARTIFACT_MAX_FILE_BYTES:
                raise ValueError('ARTIFACT_LIMIT_EXCEEDED')
            data = stream.read(ARTIFACT_MAX_FILE_BYTES + 1)
            after = os.fstat(stream.fileno())
            if len(data) > ARTIFACT_MAX_FILE_BYTES:
                raise ValueError('ARTIFACT_LIMIT_EXCEEDED')
            if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                    after.st_size, after.st_mtime_ns, after.st_ctime_ns) or len(data) != before.st_size:
                raise ValueError('ARTIFACT_CHANGED_DURING_READ')
            return data
    except OSError as exc:
        raise ValueError('UNSAFE_ARTIFACT') from exc
    finally:
        os.close(directory)


def account_artifacts(repo, baseline, run_dir):
    """Retain private copies, never commit/delete/execute generated artifacts."""
    names = sorted(set(untracked(repo)) - set(baseline))
    if any(Path(name).parts[:2] not in ARTIFACT_ROOTS or Path(name).suffix.lower()
           not in ARTIFACT_SUFFIXES for name in names):
        raise ValueError('UNCOMMITTED_NEW_FILES')
    if len(names) > ARTIFACT_MAX_FILES:
        raise ValueError('ARTIFACT_LIMIT_EXCEEDED')
    manifest = {'recorded_at': now(), 'files': [], 'file_count': 0, 'total_bytes': 0}
    blobs = run_dir / 'artifact-blobs'
    blobs.mkdir(mode=0o700, exist_ok=True)
    try:
        archive_fd = os.open(blobs, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError as exc:
        raise ValueError('UNSAFE_ARTIFACT_ARCHIVE') from exc
    try:
        return archive_artifacts(repo, names, run_dir, archive_fd, manifest)
    finally:
        os.close(archive_fd)


def archive_artifacts(repo, names, run_dir, archive_fd, manifest):
    for name in names:
        data = artifact_bytes(repo, name)
        manifest['total_bytes'] += len(data)
        if manifest['total_bytes'] > ARTIFACT_MAX_BYTES:
            raise ValueError('ARTIFACT_LIMIT_EXCEEDED')
        digest = hashlib.sha256(data).hexdigest()
        try:
            fd = os.open(digest, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600, dir_fd=archive_fd)
        except FileExistsError:
            pass
        else:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
        try:
            fd = os.open(digest, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=archive_fd)
            with os.fdopen(fd, 'rb') as stream:
                info = os.fstat(stream.fileno())
                if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                        or info.st_size != len(data) or info.st_mode & 0o077):
                    raise ValueError('UNSAFE_ARTIFACT_ARCHIVE')
                archived = stream.read(len(data) + 1)
        except OSError as exc:
            raise ValueError('UNSAFE_ARTIFACT_ARCHIVE') from exc
        if hashlib.sha256(archived).hexdigest() != digest:
            raise ValueError('ARTIFACT_ARCHIVE_MISMATCH')
        manifest['files'].append({'path': name, 'size': len(data), 'sha256': digest})
    os.fsync(archive_fd)
    manifest['file_count'] = len(manifest['files'])
    atomic_json(run_dir / 'artifacts.json', manifest)
    return manifest


def wait_child(child, prompt, state, deadline, log_path):
    """Send stdin once; publish liveness without copying log contents."""
    def snapshot():
        info = log_path.stat()
        stderr_path = log_path.with_suffix('.stderr')
        stderr_bytes = stderr_path.stat().st_size if stderr_path.exists() else 0
        if min(shutil.disk_usage(STATE).free, shutil.disk_usage(REPO).free) < MIN_FREE_BYTES:
            raise ValueError('INSUFFICIENT_DISK_SPACE')
        if info.st_size + stderr_bytes > MAX_CHILD_LOG_BYTES:
            raise ValueError('LOG_SIZE_LIMIT_EXCEEDED')
        state.update(heartbeat_at=now(), updated_at=now(), child_pid=child.pid,
                     remaining_seconds=max(0, int(deadline - time.time())), log_bytes=info.st_size,
                     stderr_bytes=stderr_bytes,
                     log_updated_at=datetime.fromtimestamp(info.st_mtime, timezone.utc).isoformat())
        atomic_json(STATE / 'status.json', state)
    pending = prompt
    while True:
        remaining = deadline - time.time()
        if remaining <= 0:
            raise subprocess.TimeoutExpired(child.args, 0)
        snapshot()
        try:
            child.communicate(pending, timeout=min(HEARTBEAT_SECONDS, remaining))
            snapshot()
            return
        except subprocess.TimeoutExpired:
            pending = None


def safe_startup_retry(log_path, repo, before, baseline):
    """Retry only a transient engine failure proven to precede all agent items.

    Any tool/message/item, malformed stream, dirty checkout or new file makes
    effects uncertain. In those cases a fresh execution is never automatic.
    """
    if log_path.stat().st_size > 2 * 1024 * 1024:
        return False
    try:
        events = [json.loads(line) for line in log_path.read_text().splitlines() if line.strip()]
        if (not events or any(not isinstance(event, dict) or event.get('type') not in
                ('thread.started', 'turn.started', 'turn.failed', 'error') for event in events)):
            return False
        errors = [event for event in events if event['type'] in ('error', 'turn.failed')]
        if re.search(r'\b40[13]\b|auth|credential|permission|approval|forbidden|quota|insufficient|usage.limit',
                     json.dumps(errors), flags=re.I):
            return False
        transient = re.search(r'\b429\b|\b50[234]\b|rate.limit|temporar|connection (?:reset|closed)|timed? out',
                              json.dumps(errors), flags=re.I)
        return bool(errors and transient and clean_checkout(repo) == before
                    and untracked(repo) == sorted(baseline))
    except (ValueError, OSError, subprocess.SubprocessError):
        return False


def retry_wait(seconds, state, deadline):
    until = min(time.time() + seconds, deadline)
    while time.time() < until:
        state.update(heartbeat_at=now(), updated_at=now(),
                     remaining_seconds=max(0, int(deadline - time.time())))
        atomic_json(STATE / 'status.json', state)
        time.sleep(min(HEARTBEAT_SECONDS, max(0, until - time.time())))


def reconcile_artifacts(runtime_evidence):
    """Resolve only the observed post-success artifact failure, without replay.

    This narrow recovery supports the public Mini App template deployment.
    Other failures/surfaces require separate operational inspection.
    """
    with writer_lock(STATE):
        old = json.loads((STATE / 'status.json').read_text())
        if old.get('status') != 'FAILED' or old.get('reason') != 'UNCOMMITTED_NEW_FILES':
            raise ValueError('NOT_AN_ARTIFACT_ONLY_FAILURE')
        head = clean_checkout(REPO)
        run_dir = Path(old['run_dir'])
        if run_dir.is_symlink() or run_dir.parent.resolve() != STATE.resolve():
            raise ValueError('UNSAFE_RECEIPT_DIRECTORY')
        original = json.loads((run_dir / 'receipt.json').read_text())
        if original.get('status') != 'VERIFIED_NEXT' or not re.fullmatch(r'[0-9a-f]{40}', original.get('commit', '')):
            raise ValueError('NO_VERIFIED_PREVIOUS_RECEIPT')
        git(REPO, 'merge-base', '--is-ancestor', original['commit'], head)
        repair_paths = ('scripts/obsidian_roadmap_autopilot.py',
                        'tests/test_obsidian_roadmap_autopilot.py', 'PROJECT_MEMORY.md',
                        'deploy/obsidian_roadmap_autopilot_install.sh',
                        'deploy/systemd/obsidian-roadmap-autopilot.service')
        changed = git(REPO, 'diff', '--name-only', original['commit'], head).splitlines()
        if any(name not in repair_paths and not name.startswith(('docs/', 'deploy/obsidian-roadmap-autopilot/'))
               for name in changed):
            raise ValueError('RECONCILIATION_REQUIRES_UNCHANGED_PRODUCT')
        # Repairs may advance HEAD; the accepted evidence and product must remain identical.
        protected = ['relay/webapp.html', *original['evidence_paths']]
        git(REPO, 'diff', '--exit-code', original['commit'], head, '--', *protected)
        candidate = dict(original, commit=head)
        expected_stage = old.get('scheduled_stage', old.get('start_stage', 'E4'))
        validate_receipt(candidate, REPO, old['before'], expected_stage)
        if runtime_evidence not in original['evidence_paths']:
            raise ValueError('RUNTIME_EVIDENCE_NOT_ACCEPTED')
        observation = json.loads(checked_evidence(REPO, runtime_evidence).read_text())
        target = Path('/opt/obsidian-exchange/relay/webapp.html')
        source = REPO / 'relay/webapp.html'
        if (observation.get('target') != str(target) or target.is_symlink()
                or observation.get('deployedSha256') != hashlib.sha256(target.read_bytes()).hexdigest()
                or target.read_bytes() != source.read_bytes()):
            raise ValueError('RUNTIME_RECONCILIATION_FAILED')
        archive = STATE / ('reconciled-artifacts-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S'))
        archive.mkdir(mode=0o700)
        artifacts = account_artifacts(REPO, old['untracked'], archive)
        for name in ('armed.json', 'status.json'):
            atomic_json(archive / name, json.loads((STATE / name).read_text()))
        atomic_json(archive / 'receipt.json', original)
        scope = validate_transition(candidate, REPO)
        if scope == 'CURRENT_AUTHORIZED_SCOPE' or old.get('continuation_scope') == 'KEYLESS_NONPRODUCTION':
            scope = old.get('continuation_scope', 'CURRENT_AUTHORIZED_SCOPE')
        report = {'status': 'RECONCILED', 'recorded_at': now(),
                  'previous_status_sha256': hashlib.sha256((STATE / 'status.json').read_bytes()).hexdigest(),
                  'previous_receipt_sha256': hashlib.sha256((run_dir / 'receipt.json').read_bytes()).hexdigest(),
                  'accepted_commit': original['commit'], 'head': head,
                  'next_step': original['next_step'], 'scheduled_stage': stage_of(original['next_step']),
                  'continuation_scope': scope, 'artifact_count': artifacts['file_count'],
                  'runtime_sha256': observation['deployedSha256'], 'replayed': False,
                  'archive': str(archive)}
        atomic_json(archive / 'reconciliation.json', report)
        atomic_json(STATE / 'status.json', report)
        print(json.dumps(report, ensure_ascii=False, indent=2))


def package_digest(package):
    digest = hashlib.sha256()
    for name in ('obsidian_roadmap_autopilot.py', 'iteration-prompt.md',
                 'iteration.schema.json'):
        digest.update(name.encode())
        digest.update((package / name).read_bytes())
    return digest.hexdigest()


@contextmanager
def writer_lock(state):
    state.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (state / 'writer.lock').open('a') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError('WRITER_LOCK_HELD') from exc
        yield stream.fileno()


def stage_of(route):
    match = re.fullmatch(r'(E[0-5])(?: / .+)?', route)
    if not match:
        raise ValueError('INVALID_CANONICAL_STAGE')
    return match[1]


def checked_evidence(repo, name):
    if not isinstance(name, str):
        raise ValueError('UNSAFE_EVIDENCE_PATH')
    path = Path(name)
    if (path.is_absolute() or '..' in path.parts or not name.startswith('docs/')
            or (repo / path).is_symlink()
            or not (repo / path).resolve().is_relative_to(repo.resolve())):
        raise ValueError('UNSAFE_EVIDENCE_PATH')
    git(repo, 'ls-files', '--error-unmatch', '--', name)
    if not (repo / path).is_file():
        raise ValueError('EVIDENCE_MISSING')
    return repo / path


def validate_transition(receipt, repo):
    current = stage_of(receipt['active_route'])
    complete = receipt['status'] == 'COMPLETE'
    target = 'COMPLETE' if complete else stage_of(receipt['next_step'])
    if target == current:
        return 'CURRENT_AUTHORIZED_SCOPE'
    path = receipt['transition_evidence']
    if not path or path not in receipt['evidence_paths']:
        raise ValueError('TRANSITION_EVIDENCE_REQUIRED')
    transition_path = checked_evidence(repo, path).resolve()
    transition = json.loads(transition_path.read_text())
    if (transition.get('schemaVersion') != 'autonomy-route-transition.v1'
            or transition.get('fromStage') != current
            or transition.get('toStage') != target
            or transition.get('roadmapSha256') != hashlib.sha256(
                (repo / 'docs/ecosystem-master-roadmap.md').read_bytes()).hexdigest()
            or not isinstance(transition.get('reason'), str)
            or not transition['reason'].strip()):
        raise ValueError('TRANSITION_BINDING_INVALID')
    assessments = transition.get('gateAssessments')
    if not isinstance(assessments, list) or len(assessments) != 6:
        raise ValueError('ALL_GATE_ASSESSMENTS_REQUIRED')
    for expected, gate in zip(STAGES, assessments):
        if not isinstance(gate, dict) or gate.get('stage') != expected:
            raise ValueError('GATE_ASSESSMENTS_ORDER_INVALID')
        if gate.get('status') not in ('VERIFIED', 'IN_PROGRESS', 'NOT_STARTED',
                                     'BLOCKED_OWNER', 'BLOCKED_EXTERNAL'):
            raise ValueError('GATE_STATUS_INVALID')
        paths = gate.get('evidencePaths')
        if not isinstance(paths, list) or not paths:
            raise ValueError('GATE_EVIDENCE_REQUIRED')
        for evidence in paths:
            if checked_evidence(repo, evidence).resolve() == transition_path:
                raise ValueError('TRANSITION_IS_NOT_GATE_EVIDENCE')
    basis = transition.get('basis')
    scope = transition.get('scope')
    if complete:
        if basis != 'ROADMAP_COMPLETE' or any(g['status'] != 'VERIFIED' for g in assessments):
            raise ValueError('ROADMAP_GATES_NOT_VERIFIED')
        return 'COMPLETE'
    first_unmet = next((g for g in assessments if g['status'] != 'VERIFIED'), None)
    if basis == 'RETURN_TO_EARLIEST':
        if (STAGES.index(target) >= STAGES.index(current) or first_unmet is None
                or first_unmet['stage'] != target):
            raise ValueError('NOT_EARLIEST_UNMET_GATE')
        if scope != 'EXISTING_AUTHORITY':
            raise ValueError('TRANSITION_SCOPE_INVALID')
    elif basis == 'VERIFIED_GATE_ADVANCE':
        if (STAGES.index(target) <= STAGES.index(current) or any(
                g['status'] != 'VERIFIED' for g in assessments[:STAGES.index(target)])):
            raise ValueError('EARLIER_GATES_NOT_VERIFIED')
        if scope != 'EXISTING_AUTHORITY':
            raise ValueError('TRANSITION_SCOPE_INVALID')
    elif basis == 'PREPARATION_UNDER_BLOCKER':
        if (first_unmet is None or first_unmet['status'] not in ('BLOCKED_OWNER', 'BLOCKED_EXTERNAL')
                or STAGES.index(first_unmet['stage']) >= STAGES.index(target)
                or not isinstance(transition.get('blocker'), str)
                or not transition['blocker'].strip()
                or transition.get('productionAllowed') is not False
                or scope != 'KEYLESS_NONPRODUCTION'):
            raise ValueError('PREPARATION_BOUNDARY_INVALID')
    else:
        raise ValueError('TRANSITION_BASIS_INVALID')
    return scope


def validate_receipt(receipt, repo, before, expected_stage='E4'):
    if not isinstance(receipt, dict) or set(receipt) != RECEIPT_KEYS:
        raise ValueError('INVALID_RECEIPT_FIELDS')
    for key in ('status', 'active_route', 'summary', 'next_step', 'commit', 'blocker', 'transition_evidence'):
        if not isinstance(receipt[key], str):
            raise ValueError('INVALID_RECEIPT_TYPES')
    if any(type(receipt[key]) is not bool for key in CHECKS):
        raise ValueError('INVALID_RECEIPT_CHECK_TYPES')
    paths = receipt['evidence_paths']
    if not isinstance(paths, list) or any(not isinstance(p, str) for p in paths):
        raise ValueError('INVALID_EVIDENCE_PATHS')
    status = receipt['status']
    if status not in ('VERIFIED_NEXT', 'BLOCKED', 'COMPLETE'):
        raise ValueError('INVALID_RECEIPT_STATUS')
    if stage_of(receipt['active_route']) != expected_stage:
        raise ValueError('UNSCHEDULED_STAGE')
    if status == 'BLOCKED':
        if not receipt['blocker'].strip():
            raise ValueError('BLOCKED_WITHOUT_REASON')
        return status
    if receipt['blocker'] or not all(receipt[k] for k in CHECKS):
        raise ValueError('ACCEPTANCE_INCOMPLETE')
    head = clean_checkout(repo)
    if receipt['commit'] != head or not receipt['summary'].strip() or not paths:
        raise ValueError('COMMIT_OR_EVIDENCE_MISSING')
    if status == 'VERIFIED_NEXT':
        if head == before:
            raise ValueError('NO_VERIFIED_PROGRESS')
        changes = git(repo, 'diff', '--name-only', before, head).splitlines()
        if not any(p.startswith(('relay/', 'bot/', 'web/', 'native-wallet/',
                                 'native/', 'kairos/', 'lumi/', 'core/', 'admin-panel/',
                                 'relay-fastapi/', 'contracts/', 'payment/', 'preview/',
                                 'monitoring/', 'news_bot/', 'support_bot/', 'deploy/', 'scripts/'))
                   or p in ('exchange.py', 'scripts/run_e4_review_browser.py',
                            'tests/e4_review_browser.cjs') for p in changes):
            raise ValueError('NO_PRODUCT_CODE_PROGRESS')
    for name in paths:
        checked_evidence(repo, name)
    validate_transition(receipt, repo)
    return status


def codex_command(package, output):
    return [str(CODEX), 'exec', '--approve-for-me', '--json', '--color', 'never',
            '-C', str(REPO), '--output-schema', str(package / 'iteration.schema.json'),
            '--output-last-message', str(output), '-']


def group_alive(pid):
    try:
        os.killpg(pid, 0)
        return True
    except ProcessLookupError:
        return False


def stop_group(child):
    if not group_alive(child.pid):
        return
    os.killpg(child.pid, signal.SIGTERM)
    deadline = time.monotonic() + 20
    while group_alive(child.pid) and time.monotonic() < deadline:
        child.poll()
        time.sleep(0.1)
    if group_alive(child.pid):
        os.killpg(child.pid, signal.SIGKILL)
    child.wait(timeout=10)


def service_other_pids():
    """Include detached and nested descendants in the dedicated systemd cgroup.

    A leftover aborts the service. KillMode=control-group then terminates the
    entire cgroup, including processes that escaped the original POSIX group.
    """
    group = '/system.slice/obsidian-roadmap-autopilot.service'
    if f'0::{group}' not in Path('/proc/self/cgroup').read_text().splitlines():
        raise ValueError('DEDICATED_SYSTEMD_CGROUP_REQUIRED')
    root = Path('/sys/fs/cgroup' + group)
    members = set()
    for path in (root / 'cgroup.procs', *root.glob('**/cgroup.procs')):
        members.update(int(pid) for pid in path.read_text().split())
    if os.getpid() not in members:
        raise ValueError('SUPERVISOR_CGROUP_MEMBERSHIP_MISSING')
    return members - {os.getpid()}


def arm(args):
    with writer_lock(STATE):
        status_file = STATE / 'status.json'
        old = json.loads(status_file.read_text()) if status_file.exists() else {}
        if old.get('status') in ('RUNNING', 'STARTING', 'WAITING_RETRY', 'INTERRUPTED', 'BLOCKED', 'FAILED'):
            raise ValueError('INSPECT_PREVIOUS_RUN_BEFORE_REARM')
        if not 1 <= args.hours <= 24 or not 0 <= args.max_iterations <= 1000:
            raise ValueError('INVALID_RUN_BUDGET')
        start_stage = getattr(args, 'start_stage', 'E4')
        next_step = getattr(args, 'next_step', '') or old.get('next_step', '')
        scope = getattr(args, 'start_scope', 'CURRENT_AUTHORIZED_SCOPE')
        if old.get('continuation_scope') == 'KEYLESS_NONPRODUCTION':
            scope = 'KEYLESS_NONPRODUCTION'
        if next_step and stage_of(next_step) != start_stage:
            raise ValueError('UNSCHEDULED_STAGE')
        receipt = {
            'status': 'ARMED', 'updated_at': now(),
            'head': clean_checkout(REPO), 'untracked': untracked(REPO),
            'package_digest': package_digest(PACKAGE),
            'max_iterations': args.max_iterations,
            'deadline': time.time() + args.hours * 3600,
            'start_stage': start_stage,
            'next_step': next_step,
            'continuation_scope': scope,
            'duration_hours': args.hours,
            'accepted_iterations': 0,
        }
        atomic_json(STATE / 'armed.json', receipt)
        atomic_json(status_file, receipt)
        print('ARMED: start obsidian-roadmap-autopilot.service after interactive edits finish')


def run():
    with writer_lock(STATE) as lock_fd:
        request = json.loads((STATE / 'armed.json').read_text())
        state = json.loads((STATE / 'status.json').read_text())
        if state.get('status') != 'ARMED':
            raise ValueError('NOT_FRESHLY_ARMED')
        state.update(status='STARTING', updated_at=now(), pid=os.getpid())
        atomic_json(STATE / 'status.json', state)
        child = None
        expected_stage = request.get('start_stage', 'E4')
        continuation_scope = request.get('continuation_scope', 'CURRENT_AUTHORIZED_SCOPE')
        known_untracked = list(request['untracked'])

        def stop(signum, frame):
            raise InterruptedError('SERVICE_STOPPED')

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        try:
            if service_other_pids():
                raise ValueError('OTHER_SERVICE_PROCESS_BEFORE_START')
            if request['head'] != clean_checkout(REPO):
                raise ValueError('CHECKOUT_CHANGED_AFTER_ARM')
            if request['package_digest'] != package_digest(PACKAGE):
                raise ValueError('PACKAGE_CHANGED_AFTER_ARM')
            if request['untracked'] != untracked(REPO):
                raise ValueError('UNTRACKED_CHANGED_AFTER_ARM')
            index = 0
            while not request['max_iterations'] or index < request['max_iterations']:
                remaining = request['deadline'] - time.time()
                if remaining <= 0:
                    state.update(status='LIMIT_REACHED', reason='authorized time limit reached between iterations')
                    break
                if shutil.disk_usage(STATE).free < MIN_FREE_BYTES:
                    raise ValueError('INSUFFICIENT_DISK_SPACE')
                index += 1
                before = clean_checkout(REPO)
                run_dir = STATE / ('run-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + f'-{index}')
                run_dir.mkdir(mode=0o700)
                output = run_dir / 'receipt.json'
                state.update(status='RUNNING', iteration=index, before=before,
                             run_dir=str(run_dir), updated_at=now(), scheduled_stage=expected_stage,
                             continuation_scope=continuation_scope)
                atomic_json(STATE / 'status.json', state)
                print(f'{now()} iteration {index} started', flush=True)
                prompt = (PACKAGE / 'iteration-prompt.md').read_text()
                prompt += (f'\nSupervisor scheduled stage: {expected_stage}. '
                           f'Allowed scope for this iteration: {continuation_scope}. '
                           'Your active_route must match this scheduled stage.\n')
                prompt += (f'Authorized run deadline UTC: {datetime.fromtimestamp(request["deadline"], timezone.utc).isoformat()}. '
                           f'Use unique browser artifacts root output/playwright/{run_dir.name}/. '
                           f'Other synthetic tool reports go under output/autopilot/{run_dir.name}/. '
                           'Allow time to verify deployment, commit evidence and return the receipt before that deadline.\n')
                if state.get('next_step'):
                    prompt += 'Accepted next item: ' + state['next_step'] + '\n'
                for attempt in range(len(STARTUP_RETRY_DELAYS) + 1):
                    if time.time() >= request['deadline']:
                        raise InterruptedError('DEADLINE_BEFORE_CHILD_START')
                    log_path = run_dir / ('codex.log' if attempt == 0 else f'codex-retry-{attempt}.log')
                    state.update(status='RUNNING', startup_attempt=attempt + 1, log_path=str(log_path))
                    with log_path.open('w') as log, log_path.with_suffix('.stderr').open('w') as stderr:
                        if time.time() >= request['deadline']:
                            raise InterruptedError('DEADLINE_BEFORE_CHILD_START')
                        child = subprocess.Popen(codex_command(PACKAGE, output),
                                                 stdin=subprocess.PIPE, stdout=log, stderr=stderr,
                                                 text=True, cwd=REPO, pass_fds=(lock_fd,),
                                                 start_new_session=True)
                        wait_child(child, prompt, state, request['deadline'], log_path)
                    if group_alive(child.pid):
                        raise ValueError('ITERATION_DESCENDANTS_REMAIN')
                    if service_other_pids():
                        raise ValueError('DETACHED_ITERATION_DESCENDANTS_REMAIN')
                    if child.returncode == 0:
                        break
                    if (attempt >= len(STARTUP_RETRY_DELAYS) or output.exists()
                            or not safe_startup_retry(log_path, REPO, before, known_untracked)):
                        raise ValueError(f'CODEX_EXIT_{child.returncode}')
                    state.update(status='WAITING_RETRY', child_pid=0,
                                 retry_reason='TRANSIENT_ENGINE_FAILURE_BEFORE_AGENT_ITEMS')
                    atomic_json(run_dir / f'startup-retry-{attempt + 1}.json', {
                        'recorded_at': now(), 'exit_code': child.returncode,
                        'reason': state['retry_reason'], 'log_sha256': hashlib.sha256(log_path.read_bytes()).hexdigest(),
                        'delay_seconds': STARTUP_RETRY_DELAYS[attempt]})
                    retry_wait(STARTUP_RETRY_DELAYS[attempt], state, request['deadline'])
                receipt = json.loads(output.read_text())
                result = validate_receipt(receipt, REPO, before, expected_stage)
                state.update(candidate_receipt=str(output), candidate_commit=receipt['commit'])
                if request['package_digest'] != package_digest(PACKAGE):
                    raise ValueError('SUPERVISOR_PACKAGE_CHANGED')
                artifacts = account_artifacts(REPO, known_untracked, run_dir)
                known_untracked = untracked(REPO)
                state.update(status=result, receipt=str(output), updated_at=now(), child_pid=0,
                             artifact_manifest=str(run_dir / 'artifacts.json'),
                             artifact_count=artifacts['file_count'], head=git(REPO, 'rev-parse', 'HEAD'))
                if result == 'BLOCKED':
                    state['reason'] = receipt['blocker']
                else:
                    state.update(last_accepted_commit=receipt['commit'],
                                 accepted_iterations=state.get('accepted_iterations', 0) + 1)
                atomic_json(STATE / 'status.json', state)
                print(f'{now()} iteration {index}: {result}', flush=True)
                if result != 'VERIFIED_NEXT':
                    break
                next_scope = validate_transition(receipt, REPO)
                if next_scope != 'CURRENT_AUTHORIZED_SCOPE':
                    continuation_scope = next_scope
                expected_stage = stage_of(receipt['next_step'])
                state.update(next_step=receipt['next_step'], scheduled_stage=expected_stage,
                             continuation_scope=continuation_scope)
                atomic_json(STATE / 'status.json', state)
            else:
                state.update(status='LIMIT_REACHED', reason='explicit iteration limit')
        except (InterruptedError, subprocess.TimeoutExpired):
            state.update(status='INTERRUPTED', reason='stop or time limit; inspect effects before any new run')
        except Exception as exc:
            # Exception type/code only: never include child output or credential-bearing text.
            reason = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
            state.update(status='FAILED', reason=reason[:160])
        finally:
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            signal.signal(signal.SIGINT, signal.SIG_IGN)
            if child is not None:
                stop_group(child)
            state['child_pid'] = 0
            state['updated_at'] = now()
            atomic_json(STATE / 'status.json', state)
        print(json.dumps({k: state[k] for k in ('status', 'reason', 'iteration') if k in state}), flush=True)
        return 1 if state['status'] in ('FAILED', 'INTERRUPTED') else 0


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    arming = commands.add_parser('arm')
    arming.add_argument('--max-iterations', type=int, default=0,
                        help='0: continue until the time limit; otherwise 1–1000')
    arming.add_argument('--hours', type=int, choices=range(1, 25), default=24)
    arming.add_argument('--start-stage', choices=STAGES, default='E4')
    arming.add_argument('--next-step', default='')
    arming.add_argument('--start-scope', choices=('CURRENT_AUTHORIZED_SCOPE', 'KEYLESS_NONPRODUCTION'),
                        default='CURRENT_AUTHORIZED_SCOPE')
    commands.add_parser('run')
    status_parser = commands.add_parser('status')
    status_parser.add_argument('--summary', action='store_true')
    reconciliation = commands.add_parser('reconcile-artifacts')
    reconciliation.add_argument('--runtime-evidence', required=True)
    args = parser.parse_args()
    if args.command == 'arm':
        arm(args)
    elif args.command == 'run':
        return run()
    elif args.command == 'reconcile-artifacts':
        reconcile_artifacts(args.runtime_evidence)
    else:
        path = STATE / 'status.json'
        state = json.loads(path.read_text()) if path.exists() else {'status': 'NOT_INSTALLED'}
        if args.summary:
            fields = ('status', 'updated_at', 'heartbeat_at', 'iteration', 'accepted_iterations',
                      'scheduled_stage', 'continuation_scope', 'next_step', 'head', 'last_accepted_commit',
                      'child_pid', 'log_bytes', 'log_updated_at', 'deadline', 'reason', 'retry_reason',
                      'artifact_count', 'run_dir', 'receipt', 'startup_attempt', 'log_path', 'max_iterations')
            state = {key: state[key] for key in fields if key in state}
            if 'deadline' in state:
                state['deadline_utc'] = datetime.fromtimestamp(state['deadline'], timezone.utc).isoformat()
                state['remaining_seconds'] = max(0, int(state['deadline'] - time.time()))
            if state.get('heartbeat_at'):
                age = (datetime.now(timezone.utc) - datetime.fromisoformat(state['heartbeat_at'])).total_seconds()
                state['heartbeat_age_seconds'] = int(age)
                if state.get('status') in ('RUNNING', 'WAITING_RETRY') and age > HEARTBEAT_SECONDS * 3:
                    state['attention'] = 'STALE_HEARTBEAT_INSPECT_SYSTEMD'
        print(json.dumps(state, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
