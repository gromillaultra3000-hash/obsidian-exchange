#!/usr/bin/env python3
"""Three-template rollout; prepare is production read-only. No service restart."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
HELPER = ROOT / 'docs/e4-wallet-cross-tab/rollout.py'
INVENTORY = HERE / 'ops-baseline.json'
spec = importlib.util.spec_from_file_location('reviewed_atomic', HELPER)
s = importlib.util.module_from_spec(spec)
spec.loader.exec_module(s)
BASE = Path('/opt/obsidian-exchange/relay-fastapi/templates')
NAMES = ('dashboard_action_review.html', 'dashboard_exchange.html', 'dashboard_sell.html')
URLS = ('https://obsidian-exchange.org/dashboard/exchange', 'https://obsidian-exchange.org/dashboard/sell')


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
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args):
            return None
    opener = urllib.request.build_opener(NoRedirect)
    results = []
    for url in URLS:
        try:
            opener.open(urllib.request.Request(url, headers={'Cache-Control': 'no-cache'}), timeout=25)
        except urllib.error.HTTPError as response:
            s.require(response.code == 302 and response.headers.get('Location') == '/login', 'Auth redirect changed')
            results.append(dict(url=url, status=302, location='/login'))
            response.close()
        else:
            raise RuntimeError('Unauthenticated dashboard did not redirect')
    return results


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
    s.require([x['candidate'] for x in plan['targets']] == [str(ROOT / 'relay-fastapi/templates' / n) for n in NAMES], 'Candidate scope mismatch')
    for entry in plan['targets']:
        expected = next((x['sha256'] for x in plan['inputs'] if x['path'] == entry['target']), None)
        s.require(entry['baseline_sha'] == expected, 'Target baseline mismatch')
    s.require(plan['targets'][0]['baseline_sha'] is None, 'Include must be new')


def prepare(path):
    s.require(not path.exists(), 'Plan exists')
    baseline = json.loads(INVENTORY.read_text())
    targets = []
    meta = s.metadata(BASE / 'dashboard_exchange.html')
    for name in NAMES:
        target, candidate = BASE / name, ROOT / 'relay-fastapi/templates' / name
        entry = dict(target=str(target), candidate=str(candidate), baseline_sha=digest(target),
                     candidate_sha=digest(candidate), metadata=s.metadata(target) if target.exists() else meta)
        s.require(entry['candidate_sha'] and entry['candidate_sha'] != entry['baseline_sha'], 'Missing/empty candidate')
        targets.append(entry)
    plan = dict(targets=targets, inventory_sha=s.sha(INVENTORY.read_bytes()), helper_sha=s.sha(HELPER.read_bytes()),
                rollout_sha=s.sha(Path(__file__).read_bytes()),
                inputs=[e for f in baseline['files'] for e in f['liveInputs']], units=baseline['units'])
    validate(plan)
    check_files(plan, 'baseline')
    s.runtime(plan)
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
    s.runtime(plan)
    check_files(plan, 'mixed' if action == 'rollback' else 'candidate' if action == 'reconcile' else 'baseline')
    if action == 'apply':
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
        s.runtime(plan)
        check_files(plan, 'baseline')
        for entry in plan['targets']:
            s.atomic(Path(entry['target']), data[entry['target']], entry['metadata'])
    elif action == 'rollback':
        backups(plan, backup)
        for entry in reversed(plan['targets']):
            target = Path(entry['target'])
            if entry['baseline_sha'] is not None:
                s.atomic(target, (backup / target.name).read_bytes(), entry['metadata'])
            elif target.exists():
                target.unlink()
                sync_directory(target.parent)
    else:
        backups(plan, backup)
    check_files(plan, 'baseline' if action == 'rollback' else 'candidate')
    s.runtime(plan)
    return dict(result=action.upper() + '_PASS', targets={e['target']: digest(Path(e['target'])) for e in plan['targets']},
                public=public(), restart=False, other_inputs_preserved=len(plan['inputs']) - 2)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'apply', 'reconcile', 'rollback'])
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--backup', type=Path)
    args = parser.parse_args()
    if args.action == 'prepare':
        result = prepare(args.plan)
    else:
        s.require(args.backup is not None, '--backup required')
        result = execute(json.loads(args.plan.read_text()), args.action, args.backup)
    print(json.dumps(result, indent=2))
