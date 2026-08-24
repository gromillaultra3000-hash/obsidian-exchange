import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("observer", ROOT / "scripts/e0_names_only_observer.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_parser_emits_only_strict_unique_names():
    names, rejected = MODULE.parse_names("# x\n TOKEN =one=two\nexport API_KEY=x\nTOKEN=y\nbad-name=z\nraw\n")
    assert names == ["TOKEN"]
    assert rejected == 4


def test_parser_never_returns_raw_or_value_fragments():
    secret = "do-not-emit-this-value"
    names, _ = MODULE.parse_names(f"PASSWORD={secret}\nJWT=aaa.bbb.ccc\n")
    assert names == ["JWT", "PASSWORD"]
    assert secret not in repr(names)


def test_missing_and_symlink_sources_fail_closed(tmp_path):
    missing = MODULE.observe("missing", str(tmp_path / "missing.env"))
    assert missing["status"] == "MISSING" and missing["members"] == []
    target = tmp_path / "target.env"
    target.write_text("TOKEN=x\n")
    link = tmp_path / "link.env"
    link.symlink_to(target)
    observed = MODULE.observe("link", str(link))
    assert observed["status"] == "UNREADABLE_OR_UNSAFE"
    assert observed["members"] == []


def test_malformed_duplicate_continuation_and_nul_never_emit_names(tmp_path):
    malformed = tmp_path / "malformed.env"
    malformed.write_text("TOKEN=canary\nTOKEN=other\nNEXT=part\\\n")
    observed = MODULE.observe("malformed", str(malformed))
    assert observed["status"] == "MALFORMED"
    assert observed["members"] == []
    assert "canary" not in repr(observed)


def test_systemd_reducer_applies_file_reset_inline_empty_and_unset(tmp_path, monkeypatch):
    base = tmp_path / "demo.service"
    dropin = tmp_path / "zz.conf"
    base.write_text("[Service]\nEnvironmentFile=/root/bot/.env\nEnvironment=OLD=x\n")
    dropin.write_text("[Service]\nEnvironmentFile=\nEnvironmentFile=/etc/obsidian-exchange/app.env\nEnvironment=EMPTY=\nUnsetEnvironment=OLD\n")
    monkeypatch.setattr(MODULE, "_unit_files", lambda unit: [str(base), str(dropin)])
    observed = MODULE.observe_unit("demo.service")
    assert observed["status"] == "OBSERVED_NAMES_ONLY"
    assert observed["files"] == ["app-env"]
    assert observed["eliminatedSourceIds"] == ["legacy-monitor-env"]
    assert observed["inlineEmptyNames"] == ["EMPTY"]
    assert observed["unsetNames"] == ["OLD"]


def test_systemd_value_specific_unset_and_pass_environment_fail_closed(tmp_path, monkeypatch):
    unit = tmp_path / "demo.service"
    unit.write_text("[Service]\nPassEnvironment=CANARY\nUnsetEnvironment=TOKEN=canary-secret\n")
    monkeypatch.setattr(MODULE, "_unit_files", lambda name: [str(unit)])
    observed = MODULE.observe_unit("demo.service")
    assert observed["status"] in {"UNSUPPORTED_PASS_ENVIRONMENT", "UNSUPPORTED_VALUE_SPECIFIC_UNSET"}
    assert "canary-secret" not in repr(observed)


def test_systemd_multi_assignment_unset_and_continuation_fail_closed(tmp_path, monkeypatch):
    unit = tmp_path / "demo.service"
    unit.write_text('[Service]\nEnvironment="A=x" "B=y"\nUnsetEnvironment=A B\nEnvironment=C=x\\\n')
    monkeypatch.setattr(MODULE, "_unit_files", lambda name: [str(unit)])
    observed = MODULE.observe_unit("demo.service")
    assert observed["status"].startswith("UNSUPPORTED_")
    assert "A" not in observed["inlineNames"] and "B" not in observed["inlineNames"]
    nul = tmp_path / "nul.env"
    nul.write_bytes(b"TOKEN=canary\x00rest")
    observed = MODULE.observe("nul", str(nul))
    assert observed["status"] == "UNREADABLE_OR_INVALID_ENCODING"
    assert "canary" not in repr(observed)
