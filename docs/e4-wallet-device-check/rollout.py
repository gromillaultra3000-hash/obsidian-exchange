#!/usr/bin/env python3
"""Publish one additive static preview release; never edit the old release in place."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import urllib.error
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT / 'docs/e4-wallet-device-check/ops-baseline.json'
FILES = ('index.html', 'device-check.css', 'device-check.js', 'manifest.json')
PUBLIC = 'https://obsidian-exchange.org/preview/'
INDEX = ROOT / 'preview/e4-visible-portfolio-preview/index.html'
ANCHOR = b'<br><a href="/preview/device-check/">' + 'Проверка устройства без переводов'.encode() + b'</a>'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def metadata(path):
    info = path.stat()
    return dict(mode=stat.S_IMODE(info.st_mode), uid=info.st_uid, gid=info.st_gid,
                xattrs={k: os.getxattr(path, k).hex() for k in os.listxattr(path)})


def tree(path):
    require(path.is_dir() and not path.is_symlink(), 'Invalid release root')
    result = {}
    for item in [path, *sorted(path.rglob('*'))]:
        require(not item.is_symlink() and (item.is_dir() or item.is_file()), 'Unexpected release entry')
        value = dict(kind='directory' if item.is_dir() else 'file', **metadata(item))
        if item.is_file():
            value['sha256'] = sha(item.read_bytes())
        result['.' if item == path else item.relative_to(path).as_posix()] = value
    return result


def unit_state(unit):
    raw = subprocess.check_output(['systemctl', 'show', unit, '-p', 'MainPID', '-p', 'ActiveState', '-p', 'SubState', '-p', 'NRestarts', '-p', 'ExecMainStartTimestamp'], text=True)
    return dict(line.split('=', 1) for line in raw.splitlines())


def preserved(plan):
    auto = unit_state('obsidian-roadmap-autopilot.service')
    require(auto['MainPID'] == '0' and auto['ActiveState'] in ('failed', 'inactive'), 'Autopilot is a writer')
    for unit in plan['units']:
        require(unit_state(unit['unit']) == unit['state'], 'Runtime drift: ' + unit['unit'])
    for item in [*plan['inputs'], plan['nginx']]:
        require(sha(Path(item['path']).read_bytes()) == item['sha256'], 'Preserved file drift: ' + item['path'])
    require(tree(Path(plan['linkTarget'])) == plan['previewTree'], 'Original preview drift')


def link_check(plan, target):
    current = Path(plan['current'])
    require(current.is_symlink() and os.readlink(current) == target, 'Current symlink drift')
    info = current.lstat()
    require((info.st_uid, info.st_gid) == (plan['linkUid'], plan['linkGid']), 'Current symlink owner drift')


def asset_hashes(candidate):
    require(candidate.is_dir() and not candidate.is_symlink(), 'Invalid candidate directory')
    require(sorted(p.name for p in candidate.iterdir()) == sorted(FILES), 'Candidate must contain exactly four approved files')
    result = {}
    for name in FILES:
        p = candidate / name
        require(p.is_file() and not p.is_symlink(), 'Candidate must contain only regular files')
        result[name] = sha(p.read_bytes())
    return result


def get_exact(url, expected):
    request = urllib.request.Request(url, headers={'Cache-Control': 'no-cache'})
    with urllib.request.urlopen(request, timeout=25) as response:
        require(response.status == 200 and response.geturl() == url, 'Public redirect or failure')
        require(response.read() == expected, 'Public bytes differ: ' + url)


def public(plan, published):
    old = Path(plan['linkTarget'])
    for name, entry in plan['previewTree'].items():
        if entry['kind'] == 'file':
            source = Path(plan['release']) if published and name == 'index.html' else old
            get_exact(PUBLIC + name, (source / name).read_bytes())
    landing = Path(plan['release']) if published else old
    get_exact(PUBLIC, (landing / 'index.html').read_bytes())
    if published:
        get_exact(PUBLIC + 'device-check/', (Path(plan['release']) / 'device-check/index.html').read_bytes())
        for name in FILES:
            get_exact(PUBLIC + 'device-check/' + name, (Path(plan['release']) / 'device-check' / name).read_bytes())
    else:
        try:
            urllib.request.urlopen(PUBLIC + 'device-check/', timeout=25)
        except urllib.error.HTTPError as error:
            require(error.code == 404, 'Expected absent device-check path')
        else:
            raise RuntimeError('Device-check path unexpectedly present')


def index_scope(before, after):
    require(after.count(ANCHOR) == 1 and ANCHOR not in before, 'Invalid index anchor scope')
    require(after.replace(ANCHOR, b'', 1) == before, 'Index changes outside exact anchor')


def expected_tree(plan):
    expected = dict(plan['previewTree'])
    expected['index.html'] = {**expected['index.html'], 'sha256': plan['indexSha256']}
    expected['device-check'] = dict(kind='directory', mode=0o555, uid=0, gid=0, xattrs={})
    for name, digest in plan['assets'].items():
        expected['device-check/' + name] = dict(kind='file', mode=0o444, uid=0, gid=0, xattrs={}, sha256=digest)
    return expected


def sync_dir(path):
    fd = os.open(path, os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def swap(plan, expected, wanted):
    current = Path(plan['current'])
    link_check(plan, expected)
    temp = current.parent / ('.device-check-link-' + uuid.uuid4().hex)
    try:
        os.symlink(wanted, temp)
        os.lchown(temp, plan['linkUid'], plan['linkGid'])
        link_check(plan, expected)
        os.replace(temp, current)
        sync_dir(current.parent)
    finally:
        if temp.is_symlink():
            temp.unlink()


def prepare(candidate, release, plan_path):
    require(not plan_path.exists(), 'Plan already exists')
    plan = json.loads(BASELINE.read_text())
    candidate = candidate.resolve()
    release = release.absolute()
    require(release.parent == Path(plan['current']).parent and release.name.startswith('e4-device-check-'), 'Release must be new bounded preview sibling')
    require(not release.exists() and not release.is_symlink(), 'Release already exists')
    require('device-check' not in plan['previewTree'], 'Device-check already present')
    index_scope((Path(plan['linkTarget']) / 'index.html').read_bytes(), INDEX.read_bytes())
    plan['indexSource'] = str(INDEX)
    plan['indexSha256'] = sha(INDEX.read_bytes())
    plan.update(candidate=str(candidate), release=str(release), assets=asset_hashes(candidate), baselineSha256=sha(BASELINE.read_bytes()))
    preserved(plan)
    link_check(plan, plan['linkTarget'])
    public(plan, False)
    plan_path.write_text(json.dumps(plan, indent=2) + '\n')
    return {'result': 'PREPARED', 'release': str(release), 'assets': plan['assets']}


def execute(plan, action):
    require(set(plan['assets']) == set(FILES), 'Invalid asset scope')
    release = Path(plan['release'])
    current = Path(plan['current'])
    require(release.parent == current.parent and release.name.startswith('e4-device-check-'), 'Invalid release path')
    preserved(plan)
    if action == 'apply':
        link_check(plan, plan['linkTarget'])
        require(asset_hashes(Path(plan['candidate'])) == plan['assets'], 'Candidate drift')
        index = Path(plan['indexSource']).read_bytes()
        require(sha(index) == plan['indexSha256'], 'Index candidate drift')
        index_scope((Path(plan['linkTarget']) / 'index.html').read_bytes(), index)
        require(not release.exists() and not release.is_symlink(), 'Release exists: reconcile, never replay apply')
        public(plan, False)
        shutil.copytree(Path(plan['linkTarget']), release, copy_function=shutil.copy2)
        release.chmod(0o755)
        index_path = release / 'index.html'
        index_path.chmod(0o644)
        index_path.write_bytes(index)
        index_path.chmod(plan['previewTree']['index.html']['mode'])
        device = release / 'device-check'
        device.mkdir(mode=0o755)
        for name in FILES:
            path = device / name
            shutil.copyfile(Path(plan['candidate']) / name, path)
            path.chmod(0o444)
            with path.open('rb') as stream:
                os.fsync(stream.fileno())
        device.chmod(0o555)
        release.chmod(plan['previewTree']['.']['mode'])
        require(tree(release) == expected_tree(plan), 'New release verification failed')
        for folder in [release, *[p for p in release.rglob('*') if p.is_dir()]]:
            sync_dir(folder)
        # Persist all preserved files as well before publishing the new tree.
        for path in release.rglob('*'):
            if path.is_file():
                with path.open('rb') as stream:
                    os.fsync(stream.fileno())
        sync_dir(release.parent)
        preserved(plan)
        swap(plan, plan['linkTarget'], str(release))
    elif action == 'rollback':
        link_check(plan, str(release))
        require(tree(release) == expected_tree(plan), 'Published release drift')
        swap(plan, str(release), plan['linkTarget'])
    elif action != 'reconcile':
        raise RuntimeError('Invalid action')
    wanted = os.readlink(current)
    require(wanted in (plan['linkTarget'], str(release)), 'Unknown current target')
    link_check(plan, wanted)
    published = wanted == str(release)
    if published:
        require(tree(release) == expected_tree(plan), 'Published release drift')
    preserved(plan)
    public(plan, published)
    staged = 'ABSENT'
    if release.exists():
        staged = 'VERIFIED' if tree(release) == expected_tree(plan) else 'INCOMPLETE_OR_DRIFTED'
    return {'result': action.upper() + '_PASS', 'state': 'PUBLISHED' if published else 'BASELINE',
            'currentTarget': wanted, 'stagedRelease': staged, 'applyReplayPermitted': False, 'restart': False, 'oldReleaseUnchanged': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'apply', 'reconcile', 'rollback'])
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--candidate', type=Path)
    parser.add_argument('--release', type=Path)
    args = parser.parse_args()
    if args.action == 'prepare':
        require(args.candidate is not None and args.release is not None, 'Candidate and release required')
        result = prepare(args.candidate, args.release, args.plan)
    else:
        result = execute(json.loads(args.plan.read_text()), args.action)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
