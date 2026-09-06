"""Fail-closed disposable browser cleanup; no service is started by these tests."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

SPEC = importlib.util.spec_from_file_location(
    'e4_browser_runner', Path(__file__).resolve().parents[1] / 'scripts/run_e4_review_browser.py')
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


@pytest.mark.parametrize('returncode,output', [
    (1, ''), (0, ''), (1, 'LoadState=not-found\nActiveState=inactive\nMainPID=0'),
    (0, 'LoadState=loaded\nActiveState=active\nMainPID=42'),
    (0, 'LoadState=loaded\nActiveState=inactive\nMainPID=42'),
])
def test_unknown_or_live_unit_never_reports_cleanup(monkeypatch, returncode, output):
    monkeypatch.setattr(runner.subprocess, 'run', lambda *a, **kw:
                        SimpleNamespace(returncode=returncode, stdout=output))
    with pytest.raises(RuntimeError, match='stop unverified'):
        runner.stop_and_verify('e4-review-browser-test')


def test_detached_child_prevents_cleanup(monkeypatch, tmp_path):
    group = tmp_path / 'e4-review-browser-test.service' / 'child'
    group.mkdir(parents=True)
    (group / 'cgroup.procs').write_text('123\n')
    monkeypatch.setattr(runner, 'Path', lambda _: tmp_path)
    monkeypatch.setattr(runner.subprocess, 'run', lambda *a, **kw: SimpleNamespace(
        returncode=0, stdout='LoadState=loaded\nActiveState=inactive\nMainPID=0'))
    with pytest.raises(RuntimeError, match='cgroup not empty'):
        runner.stop_and_verify('e4-review-browser-test')


def test_collected_unit_with_absent_cgroup_is_verified(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, 'Path', lambda _: tmp_path)
    monkeypatch.setattr(runner.subprocess, 'run', lambda *a, **kw: SimpleNamespace(
        returncode=0, stdout='LoadState=not-found\nActiveState=inactive\nMainPID=0'))
    assert runner.stop_and_verify('e4-review-browser-test')['cgroupEmpty'] is True


def test_uncertain_stop_retains_stage(monkeypatch, tmp_path):
    root = tmp_path / 'root'
    (root / 'tests').mkdir(parents=True)
    (root / 'tests/e4_review_browser.cjs').write_text('// synthetic')
    (root / 'node_modules/playwright-core').mkdir(parents=True)
    source = tmp_path / 'public.html'
    source.write_text('<html></html>')
    stage = tmp_path / 'stage'
    stage.mkdir()
    monkeypatch.setattr(runner.tempfile, 'mkdtemp', lambda **kw: str(stage))
    monkeypatch.setattr(runner.os, 'chown', lambda *a: None)
    monkeypatch.setattr(runner.subprocess, 'run', lambda *a, **kw: SimpleNamespace(returncode=1))
    def uncertain(_):
        raise RuntimeError('stop unverified')
    monkeypatch.setattr(runner, 'stop_and_verify', uncertain)
    with pytest.raises(RuntimeError, match='stop unverified'):
        runner.run(source, tmp_path / 'output', root)
    assert (stage / 'webapp.html').exists()
    assert (stage / 'runner.cjs').stat().st_mode & 0o777 == 0o644
    assert (stage / 'node_modules').stat().st_mode & 0o777 == 0o755
