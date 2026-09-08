"""Independent recovery-guidance and no-replay checks; all runtime I/O stubbed."""
import hashlib
import importlib.util
import json
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
RECIPE = ROOT / 'deploy/e4_payment_expiry_rollout.py'
spec = importlib.util.spec_from_file_location('acceptance_session_ops', RECIPE)
ops = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ops)
services = {name: {'ActiveState': 'active', 'MainPID': str(42 + index),
    'ExecMainStartTimestamp': 'synthetic-start', 'NRestarts': '0'}
    for index, name in enumerate(ops.SERVICES)}
candidate = {name: str(index + 1) * 64 for index, name in enumerate((*ops.FILES, ops.RECIPE))}
observations = []


def forbidden(*args, **kwargs):
    raise AssertionError('observation must not publish files or restart services')


for state in ['PREPARED', 'DEPLOY_RESTART_REQUESTED', 'ROLLBACK_RESTORING',
              'ROLLBACK_RESTART_REQUESTED', 'VERIFIED']:
    report = {'state': state, 'beforeServices': services, 'afterServices': services}
    writes = []
    with patch.multiple(ops,
        journal=lambda: (report, candidate, None),
        services=lambda **kwargs: services,
        file_state=lambda path: candidate[str(path.relative_to(ops.LIVE))],
        autopilot_stopped=lambda: {'ActiveState': 'failed', 'MainPID': '0'},
        public_check=lambda template, **kwargs: [{'status': 200, 'authenticated': False}],
        write_report=lambda path, value: writes.append((str(path), value)),
        replace=forbidden, restart_relay=forbidden), patch.object(Path, 'read_bytes', return_value=b'synthetic'):
        observed = ops.reconcile()
        assert observed['result'] == 'OBSERVED_NO_REPLAY' and observed['runtimeMutated'] is False
        if state.startswith('ROLLBACK'):
            assert 'independent' in observed['next'].lower(), observed['next']
            assert 'use explicit rollback' not in observed['next'].lower(), observed['next']
            try:
                ops.rollback()
            except RuntimeError as error:
                assert 'independent_reconciliation_no_replay' in str(error)
            else:
                raise AssertionError('interrupted rollback must not blindly restart again')
        elif state == 'VERIFIED':
            assert observed['next'] == 'Terminal state verified; no runtime action.'
        else:
            assert 'explicit rollback' in observed['next'].lower()
        observations.append({'state': state, 'result': 'PASS', 'guidance': observed['next'],
            'runtimeMutated': False, 'restartOrReplacementCalls': 0,
            'observationReportsWritten': len(writes)})
result = {'schemaVersion': 'e4-payment-expiry-acceptance-ops-probe.v1', 'result': 'PASS',
    'method': 'Imported recipe without main(); journal/files/services/autopilot/public probes/report writes replaced by inert fixtures. Both mutation functions raise if called. No host runtime/network/database access.',
    'inputs': [{'path': str(RECIPE.relative_to(ROOT)), 'sha256': hashlib.sha256(RECIPE.read_bytes()).hexdigest()}],
    'cases': observations,
    'limits': 'Checks observation and interrupted-rollback guidance/no-replay boundaries; deployment and filesystem mechanics use separate primary/operations tests and rehearsal evidence.'}
(OUT / 'acceptance-ops-probe.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps({'result': result['result'], 'cases': len(observations)}))
