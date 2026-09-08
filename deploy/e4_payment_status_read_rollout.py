"""Hash-bound E4 payment-status read deployment; only the Relay service may be restarted.

Interrupted commands are reconciled by observation. Deploy cannot be replayed;
rollback is explicit, verifies every preimage, and accepts only known bytes.
"""
from __future__ import annotations

import base64
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

REPO = Path('/root')
ROOT = REPO / 'output/manual/e4-payment-status-read-20260908'
DOCS = REPO / 'docs/e4-payment-status-read'
LIVE = Path('/opt/obsidian-exchange')
PREIMAGES = Path('/var/lib/obsidian-exchange/deployment-preimages')
RECIPE = 'deploy/e4_payment_status_read_rollout.py'
MAIN = 'relay-fastapi/main.py'
HTML = 'relay/webapp.html'
MODULE = 'relay/repositories/payment_status_read_store.py'
ACCESS = 'relay/core/order_access.py'
ADDITIVE = (MODULE, ACCESS)
FILES = (*ADDITIVE, MAIN, HTML)
BASELINE = {
    MAIN: '3b75a18fffeabd2d8d2640d463d26eb8f227b010534e48c37edd3888be7013df',
    MODULE: None,
    ACCESS: None,
    HTML: 'b2859b9fbe532a6121f2bbd2487e0ef2a0ccee6bf3c54da414ad49b61087cc9d',
}
PRESERVED = {item['path']: item['sha256'] for item in [{'path': 'relay/repositories/order_read_store.py',
  'sha256': '2cc91c733a8388ac2f643016fe192f7687ef0c44b79305d23fed50dcfd2ca06d'},
 {'path': 'relay/repositories/payment_session_store.py',
  'sha256': 'eb41d099a06beac4251190d10221467bdca4b21db7bc97dba687dd8d40653b8e'},
 {'path': 'relay/repositories/receipt_store.py',
  'sha256': '252ada0ad673dfb60ad3f18913b11aa0a6bfa90d647978af71a97651cc54e123'},
 {'path': 'relay/core/db_runtime.py',
  'sha256': '9e0572dc70d5d883f7009c1f6701bdd8d34ec8fcc26a3d4c7a050a7938212237'},
 {'path': 'relay/core/payout_queue.py',
  'sha256': '23aea1f15c254cc05c6732119158076d2b946fda3a6d3d5409b7e9a54086c93c'},
 {'path': 'relay/core/txid.py',
  'sha256': '726b98d97696578b0883f5a14eca119f9bc4ce0fd92f409617edf1190129f824'},
 {'path': 'relay/repositories/activity_read_store.py',
  'sha256': '32166cac62d1f92f21b1cdcaad46edda968c75832db7311969dff9228cd82f6e'},
 {'path': 'relay/repositories/operational_read_store.py',
  'sha256': 'c4df1ca1bc1b6c5d66234c8a314896b31cfb1c96c2900e7240ac36ee5c517259'},
 {'path': 'relay/services/state_machine.py',
  'sha256': '0582042d29f4d1fe78fb33b58a84dc5538e49b4142b036ad7ddec9fb3886557e'},
 {'path': 'relay-fastapi/auth.py',
  'sha256': 'cb0c3831f2d862a5519824b317dd537f7e592fdeb678a7d34a083b26436c9746'},
 {'path': 'relay/core/requisites.py',
  'sha256': 'a6c9eb87a236081095eb8213828b4ea33e9296d6f1bb8696d2e91c9733aca507'},
 {'path': 'relay/services/requisite_origin.py',
  'sha256': '5552f1c274bc2e7721068bf7db69564ca360d5065920cebbb17c022df4335398'},
 {'path': 'relay/core/telegram_freshness.py',
  'sha256': '40bef427a0daa3069e05565fdb65217836414ed581960b64f1cff5c1c266d601'}]}

SERVICES = ('relay-fastapi.service', 'exchange-bot.service', 'nginx.service',
            'obsidian-postgres.service')
URL = 'https://obsidian-exchange.org'
STATE = ROOT / 'deployment-state.json'
MANIFEST = DOCS / 'ops-release-manifest.json'


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def timestamp():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def fsync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write_report(path, data):
    fd, name = tempfile.mkstemp(prefix='.payment-status-report-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write((json.dumps(data, indent=2) + '\n').encode())
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        fsync_dir(path.parent)
    finally:
        if Path(name).exists():
            Path(name).unlink()


def file_state(path):
    require(not path.is_symlink(), f'symlink_refused:{path}')
    if not path.exists():
        return None
    require(stat.S_ISREG(path.stat().st_mode), f'not_regular:{path}')
    return sha(path.read_bytes())


def metadata(path):
    require(file_state(path) is not None, f'missing_metadata:{path}')
    info = path.stat()
    return {'uid': info.st_uid, 'gid': info.st_gid,
            'mode': stat.S_IMODE(info.st_mode),
            'atimeNs': info.st_atime_ns, 'mtimeNs': info.st_mtime_ns,
            'xattrs': {key: base64.b64encode(os.getxattr(path, key)).decode()
                       for key in os.listxattr(path)}}


def replace(target, expected, content, saved):
    require(file_state(target) == expected, f'target_changed:{target}')
    fd, name = tempfile.mkstemp(prefix='.payment-status-read-', dir=target.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content)
            stream.flush()
            os.fchown(stream.fileno(), saved['uid'], saved['gid'])
            os.fchmod(stream.fileno(), saved['mode'])
            for key, value in saved['xattrs'].items():
                os.setxattr(stream.fileno(), key, base64.b64decode(value))
            os.utime(stream.fileno(), ns=(saved['atimeNs'], saved['mtimeNs']))
            os.fsync(stream.fileno())
        require(sha(Path(name).read_bytes()) == sha(content), 'staging_digest')
        require(file_state(target) == expected, f'target_changed:{target}')
        os.replace(name, target)
        fsync_dir(target.parent)
        require(file_state(target) == sha(content), f'replacement_digest:{target}')
        current = metadata(target)
        require(all(current[key] == saved[key] for key in
                    ('uid', 'gid', 'mode', 'mtimeNs', 'xattrs')), 'replacement_metadata')
    finally:
        if Path(name).exists():
            Path(name).unlink()


def unit_state(service):
    proc = subprocess.run(['systemctl', 'show', service, '-p', 'MainPID',
                           '-p', 'ExecMainStartTimestamp', '-p', 'ActiveState',
                           '-p', 'SubState', '-p', 'NRestarts'],
                          check=True, capture_output=True, text=True, timeout=10)
    return dict(line.split('=', 1) for line in proc.stdout.splitlines())


def autopilot_stopped():
    state = unit_state('obsidian-roadmap-autopilot.service')
    require(state['ActiveState'] in ('inactive', 'failed') and state['MainPID'] == '0',
            'autopilot_is_writer')
    return state


def services(require_active=True):
    result = {service: unit_state(service) for service in SERVICES}
    if require_active:
        require(all(item['ActiveState'] == 'active' and int(item['MainPID']) > 0
                    for item in result.values()), 'service_not_active')
    return result


def preserved_inputs():
    return [{'path': path, 'sha256': expected} for path, expected in PRESERVED.items()]


def preserved():
    require(all(file_state(LIVE / path) == expected
                for path, expected in PRESERVED.items()), 'preserved_file_drift')


def safe_runtime_flags():
    # Read only this allowlisted boolean from the running process; never emit
    # or retain the surrounding environment or any unrecognized raw value.
    pid = unit_state('relay-fastapi.service')['MainPID']
    require(pid.isdigit() and int(pid) > 0, 'relay_pid_missing')
    name = b'RELAY_P3_AUTHORIZED_READ_FUNCTIONS_ENABLED='
    values = [entry[len(name):] for entry in
              Path('/proc', pid, 'environ').read_bytes().split(b'\0')
              if entry.startswith(name)]
    require(len(values) <= 1, 'duplicate_runtime_read_flag')
    value = values[0].strip().lower() if values else b''
    require(value in {b'', b'0', b'false', b'no'}, 'runtime_read_rpc_flag_not_disabled')
    return {'setting': name[:-1].decode(), 'present': bool(values), 'enabled': False}


def public_check(template, *, baseline=False, rollback=False):
    result = []
    for path, method, expected in (('/webapp', 'GET', 200),
                                    ('/webapp', 'POST', 405),
                                    ('/api/history', 'GET', 403),
                                    ('/api/order/0', 'GET', 500 if baseline else 404),
                                    ('/pay/0', 'GET', (404, 500) if rollback else
                                     (500 if baseline else 404))):
        request = urllib.request.Request(URL + path, method=method,
                  data=b'' if method == 'POST' else None,
                  headers={'Cache-Control': 'no-cache'})
        try:
            with urllib.request.urlopen(request, timeout=8) as response:
                status, body = response.status, response.read(2 * 1024 * 1024)
                final_url = response.url
        except urllib.error.HTTPError as error:
            status, body, final_url = error.code, error.read(2 * 1024 * 1024), error.url
            error.close()
        require(final_url == URL + path, 'unexpected_redirect')
        accepted = expected if isinstance(expected, tuple) else (expected,)
        require(status in accepted, f'public_status:{path}:{method}:{status}')
        record = {'path': path, 'method': method, 'status': status,
                  'authenticated': False}
        if path == '/webapp' and method == 'GET':
            match = re.search(rb"const ecosystemBotUsername = '([A-Za-z0-9_]{5,32})';", body)
            require(match is not None, 'public_template_marker')
            require(template.replace(b'__OBSIDIAN_BOT_USERNAME__', match[1]) == body,
                    'public_template_mismatch')
            record.update(publicMatchesDeployedTemplate=True, publicBodySha256=sha(body))
        elif path == '/api/history':
            require(set(json.loads(body)) == {'detail'}, 'unauthorized_response_shape')
            record['customerRowsReturned'] = 0
        result.append(record)
    return result


def inputs_match(rows):
    require(isinstance(rows, list) and rows, 'missing_input_bindings')
    found = {}
    for row in rows:
        path = row['path']
        require(not Path(path).is_absolute() and '..' not in Path(path).parts,
                'unsafe_input_path')
        require(path not in found, 'duplicate_input')
        require(file_state(REPO / path) == row['sha256'], f'input_changed:{path}')
        found[path] = row['sha256']
    return found


def manifest():
    result = json.loads(MANIFEST.read_text())
    require(result['baseline'] == BASELINE, 'baseline_manifest_changed')
    require(result['preserved'] == preserved_inputs(), 'preserved_manifest_changed')
    inputs = inputs_match(result['inputs'])
    require(set(inputs) == {*FILES, RECIPE}, 'manifest_scope')
    require(all(inputs[path] != BASELINE[path] for path in FILES), 'empty_candidate')
    return result, inputs


def bind():
    require(not STATE.exists(), 'deployment_exists_no_rebind')
    require(not MANIFEST.exists(), 'manifest_exists_no_rebind')
    preserved()
    require(all(file_state(LIVE / path) == expected
                for path, expected in BASELINE.items()), 'baseline_drift')
    report = {'recordedAt': timestamp(), 'baseline': BASELINE, 'preserved': preserved_inputs(),
              'inputs': [{'path': path, 'sha256': file_state(REPO / path)}
                         for path in (*FILES, RECIPE)]}
    write_report(MANIFEST, report)
    return report


def gates(candidate):
    for name in ('tests.json', 'browser-report.json', 'acceptance-review.json', 'security-review.json',
                 'rollback-rehearsal.json', 'isolated-postgres.json',
                 'live-dependency-rehearsal.json'):
        report = json.loads((DOCS / name).read_text())
        require(report['result'] == 'PASS', f'gate_failed:{name}')
        if name == 'browser-report.json':
            require(report['sourceSha256'] == candidate[HTML], 'browser_html_changed')
            require(report['runnerSha256'] == file_state(REPO / 'tests/e4_review_browser.cjs'),
                    'browser_runner_changed')
            isolation = json.loads((DOCS / 'browser-isolation.json').read_text())
            require(isolation['sourceSha256'] == candidate[HTML] and
                    isolation['runnerSha256'] == report['runnerSha256'], 'browser_isolation_inputs')
            require(isolation['unitStopped'] is True and isolation['processExitCode'] == 0 and
                    isolation['chromiumSandbox'] is True and isolation['privateNetwork'] is True,
                    'browser_isolation_incomplete')
            require(isolation['stopObservation']['MainPID'] == '0' and
                    isolation['stopObservation']['cgroupEmpty'] is True, 'browser_cleanup_incomplete')
            continue
        bindings = inputs_match(report['inputs'])
        require(all(bindings.get(path) == candidate[path] for path in FILES),
                f'gate_not_bound_to_candidate:{name}')
        if name in ('acceptance-review.json', 'security-review.json', 'rollback-rehearsal.json'):
            require(bindings.get(RECIPE) == candidate[RECIPE], f'gate_not_bound_to_recipe:{name}')


def record_state(report, state):
    report.update(state=state, recordedAt=timestamp())
    write_report(STATE, report)


def preflight():
    release, candidate = manifest()
    require(not STATE.exists(), 'deployment_exists_use_reconcile')
    preserved()
    require(all(file_state(LIVE / path) == expected
                for path, expected in BASELINE.items()), 'baseline_drift')
    for path in FILES:
        require((REPO / path).stat().st_size < 2 * 1024 * 1024, 'candidate_too_large')
        if path.endswith('.py'):
            compile((REPO / path).read_bytes(), path, 'exec')
    report = {'recordedAt': timestamp(), 'result': 'PASS', 'inputs': release['inputs'],
              'manifestSha256': file_state(MANIFEST), 'services': services(),
              'publicChecks': public_check((LIVE / HTML).read_bytes(), baseline=True),
              'autopilot': autopilot_stopped(), 'safeRuntimeFlags': safe_runtime_flags(),
              'runtimeMutated': False}
    write_report(DOCS / 'preflight.json', report)
    return report


def restart_relay(report, state):
    autopilot_stopped()
    # Persist intent before systemd submission. A lost result never authorizes replay.
    record_state(report, state + '_RESTART_REQUESTED')
    previous = services(require_active=False)
    subprocess.run(['systemctl', 'restart', '--no-block', 'relay-fastapi.service'],
                   check=True, capture_output=True, text=True, timeout=10)
    deadline = time.monotonic() + 50
    while time.monotonic() < deadline:
        current = services(require_active=False)
        require(all(current[name] == report['beforeServices'][name]
                    for name in SERVICES[1:]), 'unrelated_service_changed')
        relay = current[SERVICES[0]]
        if (relay['ActiveState'] == 'active' and int(relay['MainPID']) > 0 and
                relay['ExecMainStartTimestamp'] != previous[SERVICES[0]]['ExecMainStartTimestamp']):
            require(relay['NRestarts'] == '0', 'unexpected_automatic_restart')
            report['afterServices'] = current
            record_state(report, state + '_RESTARTED')
            return
        time.sleep(0.5)
    raise RuntimeError('relay_restart_uncertain_use_reconcile')


def verify_runtime(report, template):
    # Readiness can lag the service's process start. Probes use only public routes.
    deadline = time.monotonic() + 40
    last = None
    while time.monotonic() < deadline:
        try:
            is_rollback = report['state'].startswith('ROLLBACK')
            checks = public_check(template, baseline=is_rollback, rollback=is_rollback)
            now = services()
            require(all(now[name] == report['beforeServices'][name]
                        for name in SERVICES[1:]), 'unrelated_service_changed')
            require(now[SERVICES[0]]['NRestarts'] == '0', 'unexpected_automatic_restart')
            require(safe_runtime_flags() == report['safeRuntimeFlags'], 'runtime_read_flag_changed')
            report.update(publicChecks=checks, afterServices=now)
            return
        except (OSError, RuntimeError, ValueError) as error:
            last = type(error).__name__
            time.sleep(0.5)
    raise RuntimeError(f'public_verification_failed:{last}:use_reconcile_or_rollback')


def deploy():
    release, candidate = manifest()
    gates(candidate)
    before = json.loads((DOCS / 'preflight.json').read_text())
    require(before['manifestSha256'] == file_state(MANIFEST), 'preflight_manifest_drift')
    require(not STATE.exists(), 'never_repeat_deployment_use_reconcile')
    require(services() == before['services'], 'service_changed_since_preflight')
    require(safe_runtime_flags() == before['safeRuntimeFlags'], 'runtime_read_flag_changed')
    preserved()
    require(all(file_state(LIVE / path) == old for path, old in BASELINE.items()),
            'baseline_drift')
    public_check((LIVE / HTML).read_bytes(), baseline=True)
    backup = Path(tempfile.mkdtemp(prefix='e4-payment-status-read-20260908-', dir=PREIMAGES))
    backup.chmod(0o700)
    saved = {}
    for path in FILES:
        target = LIVE / path
        saved[path] = metadata(target) if BASELINE[path] else metadata(REPO / path)
        if BASELINE[path] is not None:
            preimage = backup / path
            preimage.parent.mkdir(parents=True, exist_ok=True)
            with preimage.open('xb') as stream:
                stream.write(target.read_bytes())
                stream.flush()
                os.fchmod(stream.fileno(), 0o600)
                os.fsync(stream.fileno())
            require(file_state(preimage) == BASELINE[path], 'preimage_digest')
            fsync_dir(preimage.parent)
    write_report(backup / 'metadata.json', saved)
    for folder in sorted((p for p in backup.rglob('*') if p.is_dir()),
                         key=lambda p: len(p.parts), reverse=True):
        fsync_dir(folder)
    fsync_dir(backup)
    fsync_dir(backup.parent)
    report = {'beforeServices': before['services'], 'inputs': release['inputs'],
              'manifestSha256': file_state(MANIFEST), 'rollbackDirectory': str(backup),
              'originalMetadata': saved, 'baseline': BASELINE,
              'rollbackExecuted': False, 'applied': [], 'runtimeMutated': True,
              'safeRuntimeFlags': before['safeRuntimeFlags']}
    record_state(report, 'PREPARED')
    for path in FILES:
        autopilot_stopped()
        content = (REPO / path).read_bytes()
        require(sha(content) == candidate[path], f'candidate_changed:{path}')
        replace(LIVE / path, BASELINE[path], content, saved[path])
        report['applied'].append(path)
        record_state(report, 'APPLYING')
    record_state(report, 'APPLIED')
    restart_relay(report, 'DEPLOY')
    verify_runtime(report, (LIVE / HTML).read_bytes())
    preserved()
    require(all(file_state(LIVE / path) == candidate[path] for path in FILES),
            'post_deploy_file_drift')
    record_state(report, 'VERIFIED')
    write_report(DOCS / 'deployment.json', report)
    return report


def journal():
    report = json.loads(STATE.read_text())
    require(report['baseline'] == BASELINE, 'journal_baseline')
    candidate = {row['path']: row['sha256'] for row in report['inputs']}
    require(set(candidate) == {*FILES, RECIPE}, 'journal_scope')
    require(candidate[RECIPE] == file_state(REPO / RECIPE), 'recipe_changed_after_deploy')
    for path in FILES:
        require(file_state(LIVE / path) in {BASELINE[path], candidate[path]},
                f'unknown_runtime_bytes:{path}')
    backup = Path(report['rollbackDirectory'])
    require(backup.parent == PREIMAGES and not backup.is_symlink(), 'unsafe_preimage_directory')
    for path in FILES:
        if BASELINE[path] is not None:
            require(file_state(backup / path) == BASELINE[path], 'preimage_changed')
    require(json.loads((backup / 'metadata.json').read_text()) == report['originalMetadata'],
            'preimage_metadata_changed')
    preserved()
    return report, candidate, backup


def reconcile():
    report, candidate, _ = journal()
    current = services(require_active=False)
    observed = {path: file_state(LIVE / path) for path in FILES}
    result = {'recordedAt': timestamp(), 'result': 'OBSERVED_NO_REPLAY',
              'journalState': report['state'], 'files': observed, 'services': current,
              'autopilot': autopilot_stopped(), 'runtimeMutated': False,
              'next': 'Use explicit rollback for an interrupted state; do not repeat deploy/restart.'}
    if report['state'].startswith('ROLLBACK'):
        result['next'] = ('Interrupted rollback requires independent inspection and manual completion '
                          'of known remaining steps; deploy and rollback replay are both refused.')
    try:
        result['publicChecks'] = public_check((LIVE / HTML).read_bytes(),
                baseline=observed[MAIN] == BASELINE[MAIN],
                rollback=report['state'].startswith('ROLLBACK') or report['state'] == 'ROLLED_BACK')
    except (OSError, RuntimeError, ValueError) as error:
        result['publicCheckError'] = type(error).__name__
    if report['state'] in ('VERIFIED', 'ROLLED_BACK'):
        expected = candidate if report['state'] == 'VERIFIED' else BASELINE
        require(all(observed[path] == expected[path] for path in FILES), 'terminal_file_drift')
        require(current == report['afterServices'], 'terminal_service_drift')
        require('publicChecks' in result, 'terminal_public_check_failed')
        result['next'] = 'Terminal state verified; no runtime action.'
    write_report(DOCS / 'ops-reconciliation.json', result)
    return result


def rollback():
    report, candidate, backup = journal()
    require(report['state'] != 'ROLLED_BACK', 'rollback_already_terminal')
    require(not report['state'].startswith('ROLLBACK'),
            'interrupted_rollback_requires_independent_reconciliation_no_replay')
    current = services(require_active=False)
    require(all(current[name] == report['beforeServices'][name]
                for name in SERVICES[1:]), 'unrelated_service_changed')
    report['rollbackFromState'] = report['state']
    record_state(report, 'ROLLBACK_PREPARED')
    # Old main must run before removing either additive module. Known original files
    # are accepted after an interrupted partial restoration; unknown bytes never are.
    for path in (MAIN, HTML):
        autopilot_stopped()
        now = file_state(LIVE / path)
        replace(LIVE / path, now, (backup / path).read_bytes(),
                report['originalMetadata'][path])
        record_state(report, 'ROLLBACK_RESTORING')
    restart_relay(report, 'ROLLBACK')
    autopilot_stopped()
    for path in ADDITIVE:
        if file_state(LIVE / path) is not None:
            require(file_state(LIVE / path) == candidate[path], f'added_module_changed:{path}')
            (LIVE / path).unlink()
            fsync_dir((LIVE / path).parent)
    # Removal precedes baseline probes: old numeric pay imports order_access
    # dynamically. An in-flight public request may have cached that module before
    # removal, so both historical 500 and fail-closed 404 are truthful rollback
    # observations for proofless /pay/0; neither reveals an order or enters SQL.
    verify_runtime(report, (LIVE / HTML).read_bytes())
    require(all(file_state(LIVE / path) == expected for path, expected in BASELINE.items()),
            'rollback_bytes')
    for path in (MAIN, HTML):
        now = metadata(LIVE / path)
        require(all(now[key] == report['originalMetadata'][path][key]
                    for key in ('uid', 'gid', 'mode', 'mtimeNs', 'xattrs')), 'rollback_metadata')
    report['rollbackExecuted'] = True
    record_state(report, 'ROLLED_BACK')
    write_report(DOCS / 'rollback.json', report)
    return report


def rehearse():
    release, candidate = manifest()
    cases = []
    with tempfile.TemporaryDirectory(prefix='ops-rehearsal-', dir=ROOT) as tmp:
        sandbox = Path(tmp)
        for path in FILES:
            target = sandbox / path
            target.parent.mkdir(parents=True, exist_ok=True)
            old = None if BASELINE[path] is None else (ROOT / 'baseline' / path).read_bytes()
            if old is not None:
                require(sha(old) == BASELINE[path], 'rehearsal_preimage')
                target.write_bytes(old)
                target.chmod(0o640)
            saved = metadata(target if old is not None else REPO / path)
            new = (REPO / path).read_bytes()
            replace(target, BASELINE[path], new, saved)
            try:
                replace(target, BASELINE[path], new, saved)
            except RuntimeError:
                cases.append(path + ':blind_replay_rejected')
            else:
                raise RuntimeError('replay_not_rejected')
            if old is None:
                require(file_state(target) == candidate[path], 'rehearsal_added_digest')
                target.unlink()
            else:
                replace(target, candidate[path], old, saved)
                require(metadata(target)['mode'] == 0o640, 'rehearsal_mode_restore')
            require(file_state(target) == BASELINE[path], 'rehearsal_restoration')
            cases.append(path + ':exact_baseline_restored')
        journal_path = sandbox / 'journal.json'
        write_report(journal_path, {'state': 'PREPARED'})
        write_report(journal_path, {'state': 'APPLIED'})
        require(json.loads(journal_path.read_text()) == {'state': 'APPLIED'}, 'journal_atomic_write')
        cases.append('fsynced_atomic_journal_replacement')
    report = {'recordedAt': timestamp(), 'result': 'PASS', 'inputs': release['inputs'],
              'productionTouched': False, 'cleanupVerified': not Path(tmp).exists(),
              'cases': cases,
              'limits': 'Atomic file/preimage mechanics only; production restart is not rehearsed.'}
    write_report(DOCS / 'rollback-rehearsal.json', report)
    return report


def main(mode):
    require(mode in {'bind', 'rehearse', 'preflight', 'deploy', 'reconcile', 'rollback'}, 'mode')
    ROOT.mkdir(parents=True, exist_ok=True)
    DOCS.mkdir(parents=True, exist_ok=True)
    # This local lock excludes concurrent manual instances; stopped autopilot is
    # separately rechecked immediately before every runtime publication/restart.
    with (ROOT / 'ops.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        autopilot_stopped()
        report = globals()[mode]()
        print(json.dumps(report))


if __name__ == '__main__':
    main(sys.argv[1])
