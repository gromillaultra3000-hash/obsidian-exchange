"""One hash-bound public HTML replacement; no service or database mutations."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request

ROOT = Path('/root/output/manual/e4-activity-receipt-20260908')
DOCS = Path('/root/docs/e4-activity-receipt')
SOURCE = Path('/root/relay/webapp.html')
TARGET = Path('/opt/obsidian-exchange/relay/webapp.html')
OLD = 'efcc97b6e41f8972b39163a876196f45fd8c5562dad23b5769634aac8ba7b499'
NEW = '5cd9482c174fec4288ace306e0ead463534933fc6b594d7497d88ec5ccb3a623'
URL = 'https://obsidian-exchange.org/webapp'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write_report(path, data):
    path.write_text(json.dumps(data, indent=2) + '\n')


def timestamp():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def services():
    result = {}
    for service in ('relay-fastapi.service', 'exchange-bot.service', 'nginx.service'):
        proc = subprocess.run(['systemctl', 'show', service, '-p', 'MainPID',
                               '-p', 'ExecMainStartTimestamp', '-p', 'ActiveState'],
                              check=True, capture_output=True, text=True, timeout=10)
        result[service] = dict(line.split('=', 1) for line in proc.stdout.splitlines())
        assert result[service]['ActiveState'] == 'active'
        assert int(result[service]['MainPID']) > 0
    return result


def public_check(template):
    with urllib.request.urlopen(URL, timeout=15) as response:
        assert response.status == 200
        body = response.read(2 * 1024 * 1024)
    match = re.search(rb"const ecosystemBotUsername = '([A-Za-z0-9_]{5,32})';", body)
    assert match is not None
    assert template.replace(b'__OBSIDIAN_BOT_USERNAME__', match[1]) == body
    try:
        with urllib.request.urlopen(urllib.request.Request(URL, data=b'', method='POST'), timeout=15) as response:
            post_status = response.status
    except urllib.error.HTTPError as error:
        post_status = error.code
        error.close()
    assert post_status == 405
    return {'publicGet': 200, 'publicPost': post_status,
            'publicMatchesDeployedTemplate': True, 'publicBodySha256': sha(body), 'url': URL}


def replace(target, expected, content, metadata):
    assert not target.is_symlink() and stat.S_ISREG(target.stat().st_mode)
    assert sha(target.read_bytes()) == expected
    fd, name = tempfile.mkstemp(prefix='.activity-receipt-', dir=target.parent)
    try:
        with os.fdopen(fd, 'wb') as staged:
            staged.write(content)
            staged.flush()
            os.fchown(staged.fileno(), metadata.st_uid, metadata.st_gid)
            os.fchmod(staged.fileno(), stat.S_IMODE(metadata.st_mode))
            os.fsync(staged.fileno())
        assert sha(Path(name).read_bytes()) == sha(content)
        assert sha(target.read_bytes()) == expected
        os.replace(name, target)
        directory = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        assert sha(target.read_bytes()) == sha(content)
    finally:
        if Path(name).exists():
            Path(name).unlink()


def main(mode):
    # Manual takeover must not race an autonomous product writer.
    state = subprocess.run(['systemctl', 'show', 'obsidian-roadmap-autopilot.service',
                            '-p', 'ActiveState', '-p', 'MainPID'],
                           check=True, capture_output=True, text=True, timeout=10)
    fields = dict(line.split('=', 1) for line in state.stdout.splitlines())
    assert fields['ActiveState'] in ('inactive', 'failed') and fields['MainPID'] == '0'
    if mode in ('rehearse', 'preflight', 'deploy'):
        new = SOURCE.read_bytes()
        assert sha(new) == NEW
    if mode == 'rehearse':
        old = (ROOT / 'baseline-webapp.html').read_bytes()
        assert sha(old) == OLD
        with tempfile.TemporaryDirectory(prefix='rollback-', dir=ROOT) as tmp:
            target = Path(tmp) / 'webapp.html'
            target.write_bytes(old)
            metadata = target.stat()
            replace(target, OLD, new, metadata)
            replace(target, NEW, old, metadata)
            assert sha(target.read_bytes()) == OLD
        report = {'recordedAt': timestamp(), 'result': 'PASS', 'productionTouched': False,
                  'method': 'same fsynced atomic replacement: OLD to NEW to exact OLD',
                  'beforeSha256': OLD, 'afterSha256': NEW, 'cleanupVerified': not Path(tmp).exists()}
        write_report(DOCS / 'rollback-rehearsal.json', report)
    elif mode == 'preflight':
        old = TARGET.read_bytes()
        assert sha(old) == OLD
        assert not TARGET.is_symlink() and stat.S_ISREG(TARGET.stat().st_mode)
        assert SOURCE.stat().st_size < 2 * 1024 * 1024
        report = {'recordedAt': timestamp(), 'deployedSha256': OLD, 'candidateSha256': NEW,
                  'services': services(), **public_check(old)}
        write_report(DOCS / 'preflight.json', report)
    elif mode == 'deploy':
        # This mode is invoked once, after all test/review gates pass.
        for name in ('acceptance-review.json', 'security-review.json'):
            review = json.loads((DOCS / name).read_text())
            assert review['result'] == 'PASS'
            assert review['inputsSha256']['relay/webapp.html'] == NEW
            for name, expected in review['inputsSha256'].items():
                assert sha((Path('/root') / name).read_bytes()) == expected
        browser = json.loads((DOCS / 'report.json').read_text())
        assert browser['result'] == 'PASS' and browser['sourceSha256'] == NEW
        assert browser['runnerSha256'] == sha(Path('/root/tests/e4_review_browser.cjs').read_bytes())
        tests = json.loads((DOCS / 'tests.json').read_text())
        assert tests['result'] == 'PASS'
        assert tests['inputSha256']['relay/webapp.html'] == NEW
        for name, expected in tests['inputSha256'].items():
            assert sha((Path('/root') / name).read_bytes()) == expected
        assert json.loads((DOCS / 'rollback-rehearsal.json').read_text())['result'] == 'PASS'
        state_path = ROOT / 'deployment-state.json'
        assert not state_path.exists(), 'Never repeat an uncertain deployment'
        before = json.loads((DOCS / 'preflight.json').read_text())
        assert services() == before['services']
        old = TARGET.read_bytes()
        assert sha(old) == OLD
        public_check(old)
        metadata = TARGET.stat()
        backup = Path(tempfile.mkdtemp(prefix='e4-activity-receipt-20260908-',
                      dir='/var/lib/obsidian-exchange/deployment-preimages'))
        backup.chmod(0o700)
        preimage = backup / 'webapp.html'
        with preimage.open('xb') as saved:
            saved.write(old)
            saved.flush()
            os.fchmod(saved.fileno(), 0o600)
            os.fsync(saved.fileno())
        for folder in (backup, backup.parent):
            directory = os.open(folder, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        assert sha(preimage.read_bytes()) == OLD
        report = {'recordedAt': timestamp(), 'state': 'PREPARED', 'target': str(TARGET),
                  'previousSha256': OLD, 'deployedSha256': NEW,
                  'rollbackPreimage': str(preimage), 'rollbackPreimageSha256': OLD,
                  'method': 'hash-bound fsynced atomic replacement; no restart',
                  'rollbackExecuted': False}
        write_report(state_path, report)
        replace(TARGET, OLD, new, metadata)
        report['state'] = 'APPLIED'
        write_report(state_path, report)
        report.update(public_check(TARGET.read_bytes()))
        report['services'] = services()
        assert report['services'] == before['services']
        report['serviceIdentityUnchanged'] = True
        report['state'] = 'VERIFIED'
        report['recordedAt'] = timestamp()
        write_report(state_path, report)
        write_report(DOCS / 'deployment.json', report)
    elif mode == 'rollback':
        report = json.loads((ROOT / 'deployment-state.json').read_text())
        old = Path(report['rollbackPreimage']).read_bytes()
        assert sha(old) == OLD
        replace(TARGET, NEW, old, TARGET.stat())
        report.update(public_check(TARGET.read_bytes()))
        report.update(state='ROLLED_BACK', rollbackExecuted=True, services=services())
        write_report(ROOT / 'deployment-state.json', report)
    else:
        raise ValueError(mode)
    print(json.dumps(report))


if __name__ == '__main__':
    main(sys.argv[1])
