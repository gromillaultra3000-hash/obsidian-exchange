#!/usr/bin/env python3
"""Independently complete rollback after each partial publication; local files only."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile

import pytest

ROOT = Path('/root')
TEST = ROOT / 'tests/test_e4_payment_status_read_rollout.py'
RECIPE = ROOT / 'deploy/e4_payment_status_read_rollout.py'
spec = importlib.util.spec_from_file_location('security_ops_fixture', TEST)
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)
cases = []


def baseline_restored(ops):
    m = ops.module
    assert all(m.file_state(m.LIVE / path) == expected for path, expected in m.BASELINE.items())
    assert all(not (m.LIVE / path).exists() for path in m.ADDITIVE)
    assert (m.LIVE / 'preserved.py').read_bytes() == b'unchanged'
    assert m.reconcile()['journalState'] == 'ROLLED_BACK'


for boundary in range(5):
    with tempfile.TemporaryDirectory(prefix='e4-security-ops-') as temp:
        patch = pytest.MonkeyPatch()
        try:
            ops = fixture.ops.__wrapped__(Path(temp), patch)
            m = ops.module
            original_replace = m.replace
            original_restart = m.restart_relay
            count = [0]

            def interrupt(*args):
                if count[0] == boundary:
                    raise RuntimeError('independent interruption')
                original_replace(*args)
                count[0] += 1

            m.replace = interrupt
            if boundary == 4:
                def no_restart(*args):
                    raise RuntimeError('independent interruption')
                m.restart_relay = no_restart
            try:
                m.deploy()
                raise AssertionError('interruption not reached')
            except RuntimeError as error:
                assert str(error) == 'independent interruption'
            assert not ops.calls
            m.reconcile()
            assert not ops.calls
            m.replace, m.restart_relay = original_replace, original_restart
            assert m.rollback()['state'] == 'ROLLED_BACK'
            assert len(ops.calls) == 1
            baseline_restored(ops)
            cases.append({'publishedFiles': boundary, 'explicitRollback': 'PASS',
                          'reconciliationSubmittedNoRestart': True, 'rollbackRestartCount': 1})
        finally:
            patch.undo()
    assert not Path(temp).exists()

with tempfile.TemporaryDirectory(prefix='e4-security-ops-') as temp:
    patch = pytest.MonkeyPatch()
    try:
        ops = fixture.ops.__wrapped__(Path(temp), patch)
        m = ops.module
        accepted_run = m.subprocess.run

        def lost_ack(command, **kwargs):
            accepted_run(command, **kwargs)
            raise RuntimeError('independent acknowledgement lost')

        m.subprocess.run = lost_ack
        try:
            m.deploy()
            raise AssertionError('uncertain restart not reached')
        except RuntimeError as error:
            assert str(error) == 'independent acknowledgement lost'
        assert len(ops.calls) == 1
        assert json.loads(m.STATE.read_text())['state'] == 'DEPLOY_RESTART_REQUESTED'
        m.subprocess.run = accepted_run
        assert m.reconcile()['result'] == 'OBSERVED_NO_REPLAY'
        assert len(ops.calls) == 1
        assert m.rollback()['state'] == 'ROLLED_BACK'
        assert len(ops.calls) == 2
        baseline_restored(ops)
        cases.append({'case': 'restart-submitted-acknowledgement-lost',
                      'recordedIntentBeforeSubmission': True, 'reconcileDoesNotReplay': True,
                      'explicitRollback': 'PASS', 'totalRestartCount': 2})
    finally:
        patch.undo()
assert not Path(temp).exists()

print(json.dumps({'schemaVersion': 'e4-payment-status-independent-ops-probe.v1',
    'result': 'PASS', 'inputs': [{'path': str(p.relative_to(ROOT)),
    'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for p in [Path(__file__), TEST, RECIPE]],
    'cases': cases, 'scope': 'Real deploy/journal/preimage/replacement/rollback functions on disposable files; test fixture mocks all service/public calls and upstream gates.',
    'productionReadsWritesRestartsNetwork': False, 'temporaryDirectoriesRemoved': True}, indent=2))
