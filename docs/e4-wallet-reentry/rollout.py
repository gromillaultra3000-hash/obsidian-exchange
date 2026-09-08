#!/usr/bin/env python3
"""Bounded Mini App rollout. prepare is read-only for production; apply/rollback explicit."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
TARGET = '/opt/obsidian-exchange/relay/webapp.html'
NAMES = ('walletTransfer', 'walletPay')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def stripped(data):
    for name in NAMES:
        pattern = rb'(?m)^        (?:async )?function ' + name.encode() + rb'\([^\n]*\) \{\n.*?^        \}'
        data, count = re.subn(pattern, b'FUNCTION:' + name.encode(), data, flags=re.S)
        require(count == 1, 'Function boundary missing/ambiguous: ' + name)
    return data


def bounded(before, after):
    require(before != after, 'Empty candidate')
    require(stripped(before) == stripped(after), 'Changes outside authorized functions')


def metadata(path):
    require(not path.is_symlink() and path.is_file(), 'Target must be a regular non-symlink file')
    s = path.stat()
    return dict(mode=stat.S_IMODE(s.st_mode), uid=s.st_uid, gid=s.st_gid,
                xattrs={k: os.getxattr(path, k).hex() for k in os.listxattr(path)})


def unit_state(unit):
    raw = subprocess.check_output(['systemctl', 'show', unit, '-p', 'MainPID', '-p', 'ActiveState', '-p', 'SubState', '-p', 'NRestarts', '-p', 'ExecMainStartTimestamp'], text=True)
    return dict(line.split('=', 1) for line in raw.splitlines())


def runtime(plan, captured=False):
    auto = unit_state('obsidian-roadmap-autopilot.service')
    require(auto['MainPID'] == '0' and auto['ActiveState'] in ('failed', 'inactive'), 'Autopilot is a writer')
    for unit in plan['units']:
        current = unit_state(unit['unit'])
        require(current == unit['state'], 'Runtime state drift: ' + unit['unit'])


def check_files(plan, target_sha):
    for item in plan['inputs']:
        wanted = target_sha if item['path'] == plan['target'] else item['sha256']
        require(sha(Path(item['path']).read_bytes()) == wanted, 'Live drift: ' + item['path'])
    require(metadata(Path(plan['target'])) == plan['metadata'], 'Live metadata drift')


def public(plan, template):
    expected = template.replace(b'__OBSIDIAN_BOT_USERNAME__', plan['bot_username'].encode())
    req = urllib.request.Request(plan['url'], headers={'Cache-Control': 'no-cache'})
    with urllib.request.urlopen(req, timeout=25) as response:
        require(response.status == 200 and response.geturl() == plan['url'], 'Public URL redirected or failed')
        body = response.read()
    require(body == expected, 'Public GET differs from substituted exact template')
    return sha(body)


def atomic(path, data, meta):
    fd, temp = tempfile.mkstemp(prefix='.e4-wallet-reentry-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as out:
            out.write(data)
            out.flush()
            os.fchown(out.fileno(), meta['uid'], meta['gid'])
            os.fchmod(out.fileno(), meta['mode'])
            for key, value in meta['xattrs'].items():
                os.setxattr(out.fileno(), key, bytes.fromhex(value))
            os.fsync(out.fileno())
        os.replace(temp, path)
        directory = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2) + '\n')


def prepare(args):
    baseline_path = ROOT / 'docs/e4-wallet-reentry/ops-baseline.json'
    baseline = json.loads(baseline_path.read_text())
    live = Path(TARGET).read_bytes()
    candidate = args.candidate.resolve().read_bytes()
    require(sha(candidate) == args.candidate_sha, 'Candidate digest mismatch')
    bounded(live, candidate)
    plan = dict(target=TARGET, candidate=str(args.candidate.resolve()), candidate_sha=sha(candidate),
                baseline_sha=sha(live), inventory_sha=sha(baseline_path.read_bytes()),
                metadata=metadata(Path(TARGET)), bot_username=args.bot_username,
                url='https://obsidian-exchange.org/webapp',
                inputs=[entry for file in baseline['files'] for entry in file['liveInputs']],
                units=baseline['units'], scope=list(NAMES))
    check_files(plan, plan['baseline_sha'])
    expected = next(x['sha256'] for x in plan['inputs'] if x['path'] == TARGET)
    require(expected == plan['baseline_sha'], 'Inventory baseline mismatch')
    runtime(plan)
    plan['baseline_public_sha'] = public(plan, live)
    require(not args.plan.exists(), 'Plan already exists; regenerate under a new name')
    write_json(args.plan, plan)
    return {'result': 'PREPARED', 'candidate_sha': plan['candidate_sha']}


def execute(plan, action, backup):
    target = Path(plan['target'])
    runtime(plan)
    require(plan['scope'] == list(NAMES), 'Invalid rollout scope')
    current_sha = plan['candidate_sha'] if action in ('rollback', 'reconcile') else plan['baseline_sha']
    check_files(plan, current_sha)
    if action == 'apply':
        candidate = Path(plan['candidate']).read_bytes()
        require(sha(candidate) == plan['candidate_sha'], 'Candidate digest mismatch')
        bounded(target.read_bytes(), candidate)
        public(plan, target.read_bytes())
        backup.mkdir(mode=0o700, parents=True, exist_ok=False)
        shutil.copy2(target, backup / 'webapp.html')
        os.chown(backup / 'webapp.html', plan['metadata']['uid'], plan['metadata']['gid'])
        write_json(backup / 'plan.json', plan)
        require(sha((backup / 'webapp.html').read_bytes()) == plan['baseline_sha'], 'Backup digest mismatch')
        require(metadata(backup / 'webapp.html') == plan['metadata'], 'Backup metadata mismatch')
        runtime(plan)
        check_files(plan, plan['baseline_sha'])
        atomic(target, candidate, plan['metadata'])
    elif action == 'rollback':
        require(json.loads((backup / 'plan.json').read_text()) == plan, 'Backup plan mismatch')
        original = (backup / 'webapp.html').read_bytes()
        require(sha(original) == plan['baseline_sha'], 'Backup digest mismatch')
        require(metadata(backup / 'webapp.html') == plan['metadata'], 'Backup metadata mismatch')
        bounded(original, target.read_bytes())
        atomic(target, original, plan['metadata'])
    wanted = plan['baseline_sha'] if action == 'rollback' else plan['candidate_sha']
    check_files(plan, wanted)
    runtime(plan)
    public_sha = public(plan, target.read_bytes())
    return dict(result=action.upper() + '_PASS', live_sha=wanted, public_sha=public_sha, restart=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'apply', 'reconcile', 'rollback'])
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--candidate', type=Path, default=ROOT / 'relay/webapp.html')
    parser.add_argument('--candidate-sha')
    parser.add_argument('--bot-username', default='Obsidian666999bot')
    parser.add_argument('--backup', type=Path)
    args = parser.parse_args()
    if args.action == 'prepare':
        require(bool(args.candidate_sha), '--candidate-sha required')
        result = prepare(args)
    else:
        require(args.backup is not None, '--backup required')
        result = execute(json.loads(args.plan.read_text()), args.action, args.backup)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
