#!/usr/bin/env python3
"""Two-file bot review rollout; prepare is read-only, apply/rollback restart only bot."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import py_compile
import time
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
HELPER = ROOT / 'docs/e4-wallet-cross-tab/rollout.py'
INVENTORY = HERE / 'ops-baseline.json'
spec = importlib.util.spec_from_file_location('reviewed_atomic', HELPER)
s = importlib.util.module_from_spec(spec)
spec.loader.exec_module(s)
BASE = Path('/opt/obsidian-exchange/bot')
NAMES = ('action_review.py', 'main_bot.py')
UNIT = 'exchange-bot.service'


def runtime(plan, baseline=False):
    auto = s.unit_state('obsidian-roadmap-autopilot.service')
    s.require(auto['MainPID'] == '0' and auto['ActiveState'] in ('failed', 'inactive'), 'Autopilot is a writer')
    for unit in plan['units']:
        state = s.unit_state(unit['unit'])
        if unit['unit'] != UNIT or baseline:
            s.require(state == unit['state'], 'Runtime state drift: ' + unit['unit'])
        else:
            s.require(state['MainPID'] != '0' and state['ActiveState'] == 'active' and state['SubState'] == 'running', 'Bot unhealthy')
    return s.unit_state(UNIT)


def candidate_check():
    # Compile only: never import application code or instantiate Telegram clients.
    with tempfile.TemporaryDirectory(prefix='e4-bot-preflight-') as folder:
        for name in NAMES:
            py_compile.compile(str(ROOT / 'bot' / name), cfile=str(Path(folder) / (name + 'c')), doraise=True)


def inventory():
    s.require(not INVENTORY.exists(), 'Inventory exists')
    prior = json.loads((ROOT / 'docs/e4-website-swap/ops-baseline.json').read_text())
    paths = {e['path'] for f in prior['files'] for e in f['liveInputs']}
    paths.update(str(BASE / n) for n in NAMES)
    prior['files'] = [dict(path=p, liveInputs=[dict(path=p, sha256=digest(Path(p)))]) for p in sorted(paths)]
    for unit in prior['units']:
        unit['state'] = s.unit_state(unit['unit'])
    runtime(prior, baseline=True)
    prior['recordedAt'] = datetime.now(timezone.utc).isoformat()
    prior['sourceInventory'] = 'docs/e4-website-swap/ops-baseline.json'
    prior['baselineRevision'] = subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], text=True).strip()
    prior['runtimeInventoryVerification'] = 'Host state captured; bot alone may restart.'
    s.write_json(INVENTORY, prior)
    return dict(result='INVENTORY_CAPTURED', files=len(paths), units=prior['units'])


def restart(plan):
    before = s.unit_state(UNIT)
    subprocess.run(['systemctl', 'restart', UNIT], check=True, timeout=60)
    for _ in range(20):
        state = s.unit_state(UNIT)
        if state['ActiveState'] == 'active' and state['SubState'] == 'running' and state['MainPID'] != '0':
            try:
                first = public()
                time.sleep(2)
                s.require(public() == first, 'Bot process changed during startup')
                break
            except Exception:
                pass
        time.sleep(1)
    else:
        raise RuntimeError('Bot restart health check failed; use rollback')
    after = runtime(plan)
    s.require(after['MainPID'] != before['MainPID'], 'Bot did not restart')
    return after


def sync_directory(path):
    fd = os.open(path, os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def digest(path):
    s.require(not path.is_symlink(), 'Symlink: ' + str(path))
    return s.sha(path.read_bytes()) if path.exists() else None


def public():
    # Read process arguments only. No Telegram/API/customer traffic.
    processes = []
    for proc in Path('/proc').glob('[0-9]*'):
        try:
            args = (proc / 'cmdline').read_bytes().split(b'\0')
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            continue
        if any(arg in (b'main_bot.py', b'/opt/obsidian-exchange/bot/main_bot.py') for arg in args):
            processes.append(proc.name)
    state = s.unit_state(UNIT)
    s.require(processes == [state['MainPID']], 'Expected exactly one systemd bot process')
    return dict(bot_processes=processes, bot_state=state)


def check_files(plan, state):
    targets = {x['target']: x for x in plan['targets']}
    for entry in plan['inputs']:
        if entry['path'] not in targets:
            s.require(digest(Path(entry['path'])) == entry['sha256'], 'Unrelated input drift: ' + entry['path'])
    for entry in plan['targets']:
        path = Path(entry['target'])
        observed = digest(path)
        wanted = [entry['baseline_sha'], entry['candidate_sha']] if state == 'mixed' else [entry[state + '_sha']]
        s.require(observed in wanted, 'Target drift: ' + str(path))
        if observed is not None:
            s.require(s.metadata(path) == entry['metadata'], 'Metadata drift: ' + str(path))


def validate(plan):
    baseline = json.loads(INVENTORY.read_text())
    s.require(plan['inventory_sha'] == s.sha(INVENTORY.read_bytes()), 'Inventory digest mismatch')
    s.require(plan['helper_sha'] == s.sha(HELPER.read_bytes()), 'Helper digest mismatch')
    s.require(plan['rollout_sha'] == s.sha(Path(__file__).read_bytes()), 'Rollout digest mismatch')
    s.require(plan['inputs'] == [e for f in baseline['files'] for e in f['liveInputs']], 'Inventory input mismatch')
    s.require(plan['units'] == baseline['units'], 'Unit inventory mismatch')
    s.require([x['target'] for x in plan['targets']] == [str(BASE / n) for n in NAMES], 'Target scope mismatch')
    s.require([x['candidate'] for x in plan['targets']] == [str(ROOT / 'bot' / n) for n in NAMES], 'Candidate scope mismatch')
    for entry in plan['targets']:
        expected = next((x['sha256'] for x in plan['inputs'] if x['path'] == entry['target']), None)
        s.require(entry['baseline_sha'] == expected, 'Target baseline mismatch')
    s.require(plan['targets'][0]['baseline_sha'] is None, 'Review helper must be new')


def prepare(path):
    s.require(not path.exists(), 'Plan exists')
    baseline = json.loads(INVENTORY.read_text())
    targets = []
    candidate_check()
    for name in NAMES:
        target, candidate = BASE / name, ROOT / 'bot' / name
        meta = s.metadata(BASE / 'main_bot.py')
        entry = dict(target=str(target), candidate=str(candidate), baseline_sha=digest(target),
                     candidate_sha=digest(candidate), metadata=s.metadata(target) if target.exists() else meta)
        s.require(entry['candidate_sha'] and entry['candidate_sha'] != entry['baseline_sha'], 'Missing/empty candidate')
        targets.append(entry)
    plan = dict(targets=targets, inventory_sha=s.sha(INVENTORY.read_bytes()), helper_sha=s.sha(HELPER.read_bytes()),
                rollout_sha=s.sha(Path(__file__).read_bytes()),
                inputs=[e for f in baseline['files'] for e in f['liveInputs']], units=baseline['units'])
    validate(plan)
    check_files(plan, 'baseline')
    runtime(plan, baseline=True)
    plan['baseline_public'] = public()
    s.write_json(path, plan)
    return dict(result='PREPARED', targets=targets, public=plan['baseline_public'])


def backups(plan, backup):
    s.require(not backup.is_symlink(), 'Backup symlink')
    s.require(json.loads((backup / 'plan.json').read_text()) == plan, 'Backup plan mismatch')
    for entry in plan['targets']:
        saved = backup / Path(entry['target']).name
        s.require(digest(saved) == entry['baseline_sha'], 'Backup digest mismatch')
        if saved.exists():
            s.require(s.metadata(saved) == entry['metadata'], 'Backup metadata mismatch')


def execute(plan, action, backup):
    validate(plan)
    if action == 'apply':
        runtime(plan, baseline=True)
    else:
        # Rollback must work even when the new bot process failed to start.
        check_other_runtime(plan)
    check_files(plan, 'mixed' if action == 'rollback' else 'candidate' if action == 'reconcile' else 'baseline')
    if action == 'apply':
        candidate_check()
        for entry in plan['targets']:
            s.require(digest(Path(entry['candidate'])) == entry['candidate_sha'], 'Candidate digest mismatch')
        data = {e['target']: Path(e['candidate']).read_bytes() for e in plan['targets']}
        for entry in plan['targets']:
            s.require(s.sha(data[entry['target']]) == entry['candidate_sha'], 'Candidate digest mismatch')
        public()
        backup.mkdir(mode=0o700, parents=True, exist_ok=False)
        for entry in plan['targets']:
            if entry['baseline_sha'] is not None:
                dest = backup / Path(entry['target']).name
                shutil.copy2(entry['target'], dest)
                os.chown(dest, entry['metadata']['uid'], entry['metadata']['gid'])
                with dest.open('rb') as saved:
                    os.fsync(saved.fileno())
        s.write_json(backup / 'plan.json', plan)
        with (backup / 'plan.json').open('rb') as saved:
            os.fsync(saved.fileno())
        sync_directory(backup)
        sync_directory(backup.parent)
        backups(plan, backup)
        runtime(plan, baseline=True)
        check_files(plan, 'baseline')
        # Helper first; old in-memory bot keeps running until both files are ready.
        for entry in plan['targets']:
            s.atomic(Path(entry['target']), data[entry['target']], entry['metadata'])
        restart(plan)
    elif action == 'rollback':
        backups(plan, backup)
        # Restore entry point before removing helper. Stale order_review_ callbacks
        # have no matching baseline handler; receipts also expire on restart.
        ordered = list(reversed(plan['targets']))
        for entry in ordered:
            target = Path(entry['target'])
            if entry['baseline_sha'] is not None:
                s.atomic(target, (backup / target.name).read_bytes(), entry['metadata'])
            elif target.exists():
                target.unlink()
                sync_directory(target.parent)
    else:
        backups(plan, backup)
    check_files(plan, 'baseline' if action == 'rollback' else 'candidate')
    state = restart(plan) if action == 'rollback' else runtime(plan)
    return dict(result=action.upper() + '_PASS', targets={e['target']: digest(Path(e['target'])) for e in plan['targets']},
                public=public(), restart=action in ('apply', 'rollback'), bot_state=state,
                other_inputs_preserved=len(plan['inputs']) - len(NAMES))


def check_other_runtime(plan):
    # runtime returns bot state but validates only the listed preserved units.
    return runtime(dict(plan, units=[u for u in plan['units'] if u['unit'] != UNIT]))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['inventory', 'prepare', 'apply', 'reconcile', 'rollback'])
    parser.add_argument('--plan', type=Path)
    parser.add_argument('--backup', type=Path)
    args = parser.parse_args()
    if args.action == 'inventory':
        result = inventory()
    elif args.action == 'prepare':
        s.require(args.plan is not None, '--plan required')
        result = prepare(args.plan)
    else:
        s.require(args.plan is not None, '--plan required')
        s.require(args.backup is not None, '--backup required')
        result = execute(json.loads(args.plan.read_text()), args.action, args.backup)
    print(json.dumps(result, indent=2))
