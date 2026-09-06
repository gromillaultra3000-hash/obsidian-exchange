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
import subprocess
import sys
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


def now():
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path, value):
    temporary = path.with_suffix('.tmp')
    with temporary.open('w', encoding='utf-8') as stream:
        os.chmod(temporary, 0o600)
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
                                 'monitoring/', 'news_bot/', 'support_bot/'))
                   or p in ('exchange.py', 'scripts/run_e4_review_browser.py',
                            'tests/e4_review_browser.cjs') for p in changes):
            raise ValueError('NO_PRODUCT_CODE_PROGRESS')
    for name in paths:
        checked_evidence(repo, name)
    validate_transition(receipt, repo)
    return status


def codex_command(package, output):
    return [str(CODEX), 'exec', '--approve-for-me', '--color', 'never',
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
        if old.get('status') in ('RUNNING', 'STARTING', 'INTERRUPTED', 'BLOCKED', 'FAILED'):
            raise ValueError('INSPECT_PREVIOUS_RUN_BEFORE_REARM')
        receipt = {
            'status': 'ARMED', 'updated_at': now(),
            'head': clean_checkout(REPO), 'untracked': untracked(REPO),
            'package_digest': package_digest(PACKAGE),
            'max_iterations': args.max_iterations,
            'deadline': time.time() + args.hours * 3600,
            'start_stage': getattr(args, 'start_stage', 'E4'),
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
        continuation_scope = 'CURRENT_AUTHORIZED_SCOPE'

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
            for index in range(1, request['max_iterations'] + 1):
                remaining = request['deadline'] - time.time()
                if remaining <= 0:
                    state.update(status='LIMIT_REACHED', reason='overnight time limit')
                    break
                before = clean_checkout(REPO)
                run_dir = STATE / ('run-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + f'-{index}')
                run_dir.mkdir(mode=0o700)
                output = run_dir / 'receipt.json'
                state.update(status='RUNNING', iteration=index, before=before,
                             run_dir=str(run_dir), updated_at=now())
                atomic_json(STATE / 'status.json', state)
                print(f'{now()} iteration {index} started', flush=True)
                prompt = (PACKAGE / 'iteration-prompt.md').read_text()
                prompt += (f'\nSupervisor scheduled stage: {expected_stage}. '
                           f'Allowed scope for this iteration: {continuation_scope}. '
                           'Your active_route must match this scheduled stage.\n')
                if state.get('next_step'):
                    prompt += 'Accepted next item: ' + state['next_step'] + '\n'
                with (run_dir / 'codex.log').open('w') as log:
                    child = subprocess.Popen(codex_command(PACKAGE, output),
                                             stdin=subprocess.PIPE, stdout=log, stderr=log,
                                             text=True, cwd=REPO, pass_fds=(lock_fd,),
                                             start_new_session=True)
                    child.communicate(prompt, timeout=remaining)
                if child.returncode != 0:
                    raise ValueError(f'CODEX_EXIT_{child.returncode}')
                if group_alive(child.pid):
                    raise ValueError('ITERATION_DESCENDANTS_REMAIN')
                if service_other_pids():
                    raise ValueError('DETACHED_ITERATION_DESCENDANTS_REMAIN')
                receipt = json.loads(output.read_text())
                result = validate_receipt(receipt, REPO, before, expected_stage)
                if request['package_digest'] != package_digest(PACKAGE):
                    raise ValueError('SUPERVISOR_PACKAGE_CHANGED')
                if set(untracked(REPO)) - set(request['untracked']):
                    raise ValueError('UNCOMMITTED_NEW_FILES')
                state.update(status=result, receipt=str(output), updated_at=now())
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
            else:
                state.update(status='LIMIT_REACHED', reason='overnight iteration limit')
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
            state['updated_at'] = now()
            atomic_json(STATE / 'status.json', state)
        print(json.dumps({k: state[k] for k in ('status', 'reason', 'iteration') if k in state}), flush=True)
        return 1 if state['status'] in ('FAILED', 'INTERRUPTED') else 0


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    arming = commands.add_parser('arm')
    arming.add_argument('--max-iterations', type=int, choices=range(1, 17), default=8)
    arming.add_argument('--hours', type=int, choices=range(1, 13), default=12)
    arming.add_argument('--start-stage', choices=STAGES, default='E4')
    commands.add_parser('run')
    commands.add_parser('status')
    args = parser.parse_args()
    if args.command == 'arm':
        arm(args)
    elif args.command == 'run':
        return run()
    else:
        path = STATE / 'status.json'
        print(path.read_text() if path.exists() else '{"status":"NOT_INSTALLED"}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
