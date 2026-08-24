import importlib.util
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location("producer",ROOT/"lumi/scripts/produce_shadow_backup_evidence.py")
producer=importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(producer)

def test_same_device_refuses_before_copy(tmp_path):
    paths=[tmp_path/name for name in ("state","primary","secondary","scratch")]
    for path in paths: path.mkdir()
    with pytest.raises(RuntimeError,match="three devices"):
        producer.produce(paths[0]/"decisions.jsonl",*paths[1:])
    assert not list(paths[1].iterdir()) and not list(paths[2].iterdir())

def test_atomic_write_is_0640(tmp_path,monkeypatch):
    monkeypatch.setattr(producer.os,"fchown",lambda *args:None)
    target=tmp_path/"evidence.json"; producer.atomic_write(target,{"ready":True},group=123)
    assert target.read_text()=='{"ready":true}\n'
    assert target.stat().st_mode & 0o777 == 0o640
