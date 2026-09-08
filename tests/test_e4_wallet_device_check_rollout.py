"""Static symlink publication failures rehearsed only in disposable directories."""
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace
import pytest

spec = importlib.util.spec_from_file_location('device_ops', Path(__file__).resolve().parents[1] / 'docs/e4-wallet-device-check/rollout.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


@pytest.fixture
def env(tmp_path, monkeypatch):
    old = tmp_path / 'old'
    old.mkdir()
    (old / 'index.html').write_text('prior index')
    (old / 'assets').mkdir()
    (old / 'assets/keep.js').write_text('preserved')
    for p in old.rglob('*'):
        p.chmod(0o555 if p.is_dir() else 0o444)
    old.chmod(0o555)
    current = tmp_path / 'current'
    current.symlink_to(old)
    candidate = tmp_path / 'candidate'
    candidate.mkdir()
    for name in m.FILES:
        (candidate / name).write_text('inert ' + name)
    index = tmp_path / 'new-index.html'
    index.write_bytes((old / 'index.html').read_bytes() + m.ANCHOR)
    plan = {'indexSource':str(index),'indexSha256':m.sha(index.read_bytes()),'current':str(current),'linkTarget':str(old),'linkUid':os.getuid(),'linkGid':os.getgid(),
            'previewTree':m.tree(old),'candidate':str(candidate),'release':str(tmp_path/'e4-device-check-test'),
            'assets':m.asset_hashes(candidate),'inputs':[],'units':[],'nginx':{}}
    def preserved(p):
        m.require(m.tree(old)==p['previewTree'],'Original preview drift')
    monkeypatch.setattr(m,'preserved',preserved)
    monkeypatch.setattr(m,'public',lambda *args:None)
    return SimpleNamespace(old=old,current=current,candidate=candidate,plan=plan,release=Path(plan['release']))


def test_apply_reconcile_rollback_preserves_original_exactly(env):
    e=env
    assert m.execute(e.plan,'apply')['state']=='PUBLISHED'
    assert m.tree(e.old)==e.plan['previewTree']
    assert m.tree(e.release)==m.expected_tree(e.plan)
    assert m.execute(e.plan,'reconcile')['state']=='PUBLISHED'
    assert m.execute(e.plan,'rollback')['state']=='BASELINE'
    assert m.execute(e.plan,'reconcile')['state']=='BASELINE'
    assert os.readlink(e.current)==str(e.old)


@pytest.mark.parametrize('fault',['candidate','extra_asset','symlink_asset','old_tree','current','release_exists'])
def test_preflight_drift_rejects_without_link_mutation(env,fault):
    e=env
    if fault=='candidate':(e.candidate/m.FILES[0]).write_text('changed')
    if fault=='extra_asset':(e.candidate/'extra').write_text('extra')
    if fault=='symlink_asset':
        (e.candidate/m.FILES[0]).unlink();(e.candidate/m.FILES[0]).symlink_to(e.old/'index.html')
    if fault=='old_tree':(e.old/'index.html').chmod(0o644)
    if fault=='current':e.current.unlink();e.current.symlink_to('/tmp/unknown-device-target')
    if fault=='release_exists':e.release.mkdir()
    before=os.readlink(e.current)
    with pytest.raises(RuntimeError):m.execute(e.plan,'apply')
    assert os.readlink(e.current)==before


def test_failed_atomic_swap_leaves_old_release_and_no_automatic_retry(env,monkeypatch):
    def fail(*args):raise OSError('injected swap failure')
    monkeypatch.setattr(m.os,'replace',fail)
    with pytest.raises(OSError):m.execute(env.plan,'apply')
    assert os.readlink(env.current)==str(env.old)
    assert m.execute(env.plan,'reconcile')['state']=='BASELINE'
    assert not list(env.current.parent.glob('.device-check-link-*'))
    with pytest.raises(RuntimeError,match='never replay'):m.execute(env.plan,'apply')


def test_public_post_swap_failure_can_reconcile_and_rollback(env,monkeypatch):
    def fail(p,published):
        if published:raise RuntimeError('public failure')
    monkeypatch.setattr(m,'public',fail)
    with pytest.raises(RuntimeError,match='public failure'):m.execute(env.plan,'apply')
    assert os.readlink(env.current)==str(env.release)
    monkeypatch.setattr(m,'public',lambda *args:None)
    assert m.execute(env.plan,'reconcile')['state']=='PUBLISHED'
    assert m.execute(env.plan,'rollback')['state']=='BASELINE'


def test_changed_release_blocks_rollback(env):
    m.execute(env.plan,'apply')
    p=env.release/'device-check'/m.FILES[0];p.chmod(0o644);p.write_text('changed')
    with pytest.raises(RuntimeError,match='Published release drift'):m.execute(env.plan,'rollback')
    assert os.readlink(env.current)==str(env.release)


def test_unexpected_symlink_release_entry_rejected(env):
    env.old.chmod(0o755)
    link=env.old/'escape'
    link.symlink_to('/etc/passwd')
    with pytest.raises(RuntimeError,match='Unexpected release entry'):m.tree(env.old)


def test_index_scope_rejects_unrelated_change(env):
    index=Path(env.plan['indexSource'])
    index.write_bytes(index.read_bytes()+b'UNRELATED')
    env.plan['indexSha256']=m.sha(index.read_bytes())
    with pytest.raises(RuntimeError,match='Index changes outside'):
        m.execute(env.plan,'apply')
    assert os.readlink(env.current)==str(env.old)


def test_incomplete_staging_is_explicit_and_not_replayed(env):
    env.release.mkdir()
    report=m.execute(env.plan,'reconcile')
    assert report['state']=='BASELINE'
    assert report['stagedRelease']=='INCOMPLETE_OR_DRIFTED'
    assert report['applyReplayPermitted'] is False
    with pytest.raises(RuntimeError,match='never replay'):
        m.execute(env.plan,'apply')


def test_actual_preservation_guard_rejects_active_writer(monkeypatch):
    monkeypatch.setattr(m,'unit_state',lambda _: {'MainPID':'3','ActiveState':'active'})
    with pytest.raises(RuntimeError,match='Autopilot is a writer'):
        m.preserved({})
