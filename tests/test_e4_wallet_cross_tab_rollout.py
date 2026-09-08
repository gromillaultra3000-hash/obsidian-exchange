import importlib.util,json,subprocess
from pathlib import Path
import pytest
spec=importlib.util.spec_from_file_location('rollout',str(Path(__file__).resolve().parents[1] / 'docs/e4-wallet-cross-tab/rollout.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
@pytest.fixture
def env(tmp_path,monkeypatch):
    before=subprocess.check_output(['git','show','6d273bc:relay/webapp.html'],cwd='/root')
    after=Path('/root/relay/webapp.html').read_bytes()
    target=tmp_path/'webapp.html';target.write_bytes(before)
    candidate=tmp_path/'candidate.html';candidate.write_bytes(after)
    side=tmp_path/'server.py';side.write_bytes(b'unchanged')
    plan=dict(target=str(target),candidate=str(candidate),candidate_sha=m.sha(after),baseline_sha=m.sha(before),metadata=m.metadata(target),scope=m.SCOPE.copy(),inputs=[dict(path=str(target),sha256=m.sha(before)),dict(path=str(side),sha256=m.sha(side.read_bytes()))])
    monkeypatch.setattr(m,'runtime',lambda p:None)
    monkeypatch.setattr(m,'public',lambda p,b:m.sha(b))
    return target,candidate,side,plan,tmp_path/'backup',before,after

def test_apply_reconcile_rollback(env):
    t,c,s,p,b,before,after=env
    assert m.execute(p,'apply',b)['result']=='APPLY_PASS'
    assert t.read_bytes()==after
    assert m.metadata(t)==p['metadata']
    assert (b/'webapp.html').read_bytes()==before
    assert m.execute(p,'reconcile',b)['result']=='RECONCILE_PASS'
    assert m.execute(p,'rollback',b)['result']=='ROLLBACK_PASS'
    assert t.read_bytes()==before
    assert m.metadata(t)==p['metadata']

@pytest.mark.parametrize('fault',['candidate','live','side','scope','backup_exists','metadata'])
def test_preconditions(env,fault):
    t,c,s,p,b,before,after=env
    if fault=='candidate':c.write_bytes(b'changed')
    if fault=='live':t.write_bytes(before+b'changed')
    if fault=='side':s.write_bytes(b'changed')
    if fault=='scope':p['scope']=[]
    if fault=='backup_exists':b.mkdir()
    if fault=='metadata':t.chmod(0o600)
    current=t.read_bytes()
    with pytest.raises((RuntimeError,FileExistsError)):m.execute(p,'apply',b)
    assert t.read_bytes()==current

def test_failed_replace_preserves_baseline(env,monkeypatch):
    t,c,s,p,b,before,after=env
    def fail(*args):raise OSError('injected replace failure')
    monkeypatch.setattr(m.os,'replace',fail)
    with pytest.raises(OSError):m.execute(p,'apply',b)
    assert t.read_bytes()==before
    assert (b/'webapp.html').read_bytes()==before
    assert not list(t.parent.glob('.e4-wallet-cross-tab-*'))

def test_post_public_failure_can_reconcile(env,monkeypatch):
    t,c,s,p,b,before,after=env
    def fail_candidate(p,body):
        if body==after:raise RuntimeError('injected public failure')
        return m.sha(body)
    monkeypatch.setattr(m,'public',fail_candidate)
    with pytest.raises(RuntimeError):m.execute(p,'apply',b)
    assert t.read_bytes()==after
    assert (b/'webapp.html').read_bytes()==before
    monkeypatch.setattr(m,'public',lambda p,b:m.sha(b))
    assert m.execute(p,'reconcile',b)['result']=='RECONCILE_PASS'
    assert m.execute(p,'rollback',b)['result']=='ROLLBACK_PASS'

def test_scope_guard(env):
    t,c,s,p,b,before,after=env
    m.bounded(before,after)
    with pytest.raises(RuntimeError):m.bounded(before,after+b'out of scope')

def test_bad_backup_rejected(env):
    t,c,s,p,b,before,after=env
    m.execute(p,'apply',b)
    (b/'webapp.html').write_bytes(b'wrong')
    with pytest.raises(RuntimeError):m.execute(p,'rollback',b)
    assert t.read_bytes()==after

@pytest.mark.parametrize('marker', [
    b'<section id="wallet-attempt-notice"',
    b'// One unresolved handoff ',
    b'(function wireWalletAttemptNotice() {',
])
def test_missing_addition_rejected(env, marker):
    *_, before, after = env
    with pytest.raises(RuntimeError, match='Region boundary missing'):
        m.bounded(before, after.replace(marker, b'MISSING', 1))


def test_unrelated_existing_function_mutation_rejected(env):
    *_, before, after = env
    with pytest.raises(RuntimeError, match='Changes outside authorized scope'):
        m.bounded(before, after.replace(b'function walletOpsRender(d)', b'function changedWalletOpsRender(d)', 1))


def test_active_autopilot_rejected(monkeypatch):
    monkeypatch.setattr(m, 'unit_state', lambda unit: {'MainPID': '5', 'ActiveState': 'active'})
    with pytest.raises(RuntimeError, match='Autopilot is a writer'):
        m.runtime({'units': []})


def test_runtime_identity_drift_rejected(monkeypatch):
    states = {'MainPID': '0', 'ActiveState': 'failed'}
    monkeypatch.setattr(m, 'unit_state', lambda unit: states if unit.endswith('autopilot.service') else {'MainPID': '999'})
    with pytest.raises(RuntimeError, match='Runtime state drift'):
        m.runtime({'units': [{'unit': 'relay-fastapi.service', 'state': {'MainPID': '123'}}]})


def test_duplicate_region_rejected(env):
    *_, before, after = env
    marker = b'        <section id="wallet-attempt-notice"\nX\n        </section>\n\n'
    with pytest.raises(RuntimeError, match='Region boundary missing/ambiguous'):
        m.bounded(before, after + marker)
