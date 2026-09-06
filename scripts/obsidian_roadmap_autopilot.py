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
}
CHECKS = ('tests_passed', 'acceptance_review_passed',
          'independent_review_passed', 'runtime_verified')


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


def validate_receipt(receipt, repo, before):
    if not isinstance(receipt, dict) or set(receipt) != RECEIPT_KEYS:
        raise ValueError('INVALID_RECEIPT_FIELDS')
    for key in ('status', 'active_route', 'summary', 'next_step', 'commit', 'blocker'):
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
    if status == 'BLOCKED':
        if not receipt['blocker'].strip():
            raise ValueError('BLOCKED_WITHOUT_REASON')
        return status
    if not (receipt['active_route'] == 'E4'
            or receipt['active_route'].startswith('E4 /')):
        raise ValueError('ROUTE_CHANGED')
    if receipt['blocker'] or not all(receipt[k] for k in CHECKS):
        raise ValueError('ACCEPTANCE_INCOMPLETE')
    head = clean_checkout(repo)
    if receipt['commit'] != head or not receipt['summary'].strip() or not paths:
        raise ValueError('COMMIT_OR_EVIDENCE_MISSING')
    if status == 'VERIFIED_NEXT':
        if head == before or not receipt['next_step'].startswith('E4 /'):
            raise ValueError('NO_VERIFIED_PROGRESS')
        changes = git(repo, 'diff', '--name-only', before, head).splitlines()
        if not any(p.startswith(('relay/', 'bot/', 'web/', 'native-wallet/'))
                   or p == 'exchange.py' for p in changes):
            raise ValueError('NO_PRODUCT_CODE_PROGRESS')
    for name in paths:
        path = Path(name)
        if (path.is_absolute() or '..' in path.parts or not name.startswith('docs/')
                or (repo / path).is_symlink()
                or not (repo / path).resolve().is_relative_to(repo.resolve())):
            raise ValueError('UNSAFE_EVIDENCE_PATH')
        git(repo, 'ls-files', '--error-unmatch', '--', name)
        if not (repo / path).is_file():
            raise ValueError('EVIDENCE_MISSING')
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
                result = validate_receipt(receipt, REPO, before)
                if request['package_digest'] != package_digest(PACKAGE):
                    raise ValueError('SUPERVISOR_PACKAGE_CHANGED')
                if set(untracked(REPO)) - set(request['untracked']):
                    raise ValueError('UNCOMMITTED_NEW_FILES')
                state.update(status=result, receipt=str(output), updated_at=now())
                atomic_json(STATE / 'status.json', state)
                print(f'{now()} iteration {index}: {result}', flush=True)
                if result != 'VERIFIED_NEXT':
                    break
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
