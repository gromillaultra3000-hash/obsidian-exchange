import copy
import inspect
import json
import os
import stat
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "lumi") not in sys.path:
    sys.path.insert(0, str(ROOT / "lumi"))

from lumi.app.integration.shadow_replay_ledger import validate_snapshot
from lumi.app.integration.shadow_replay_provisioning import (
    build_plan, provision_replay_state, validate_plan,
)


def prepare_root(tmp_path):
    ancestor = tmp_path / "var/lib/lumi"
    ancestor.mkdir(parents=True, mode=0o700)
    ancestor.chmod(0o700)
    return tmp_path


def target(root, logical):
    return root.joinpath(*Path(logical).parts[1:])


def provision(root, **changes):
    return provision_replay_state(
        build_plan(), root=root, owner_uid=os.getuid(), owner_gid=os.getgid(),
        **changes)


def test_frozen_plan_is_exact_and_non_executing():
    expected = json.loads((
        ROOT / "contracts/e2-shadow/replay-provisioning-plan.v1.json"
    ).read_text())
    assert build_plan() == expected
    assert validate_plan(expected) == expected
    assert expected["executionEffect"] == "NONE"
    assert expected["actionAllowed"] is False


def test_fresh_provisioning_creates_empty_narrow_state_and_lock(tmp_path):
    root = prepare_root(tmp_path)
    plan = build_plan()
    report = provision(root)
    state = target(root, plan["statePath"])
    lock = target(root, plan["lockPath"])
    assert report == {
        "schemaVersion": "shadow-replay-provisioning.v1",
        "planId": plan["planId"], "status": "PROVISIONED",
        "stateCreated": True, "lockCreated": True,
        "entryCount": 0, "capacity": 10000,
        "executionEffect": "REPLAY_STATE_CREATED", "actionAllowed": False,
    }
    assert validate_snapshot(json.loads(state.read_bytes()))["entryCount"] == 0
    assert lock.read_bytes() == b""
    for path in (state.parent,):
        assert stat.S_IMODE(path.stat().st_mode) == 0o700
    for path in (state, lock):
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert path.stat().st_uid == os.getuid()
        assert path.stat().st_gid == os.getgid()


@pytest.mark.parametrize("stage", ["after_directory", "after_state", "after_lock"])
def test_injected_fault_removes_every_new_target(tmp_path, stage):
    root = prepare_root(tmp_path)

    def fail(actual):
        if actual == stage:
            raise RuntimeError("injected replay provisioning fault")

    with pytest.raises(RuntimeError, match="injected"):
        provision(root, fault=fail)
    plan = build_plan()
    assert not target(root, plan["statePath"]).exists()
    assert not target(root, plan["lockPath"]).exists()
    assert not target(root, plan["statePath"]).parent.exists()


@pytest.mark.parametrize("which", ["statePath", "lockPath"])
def test_existing_or_partial_target_fails_without_overwrite(tmp_path, which):
    root = prepare_root(tmp_path)
    plan = build_plan()
    leaf = target(root, plan["statePath"]).parent
    leaf.mkdir(mode=0o700)
    existing = target(root, plan[which])
    existing.write_bytes(b"do-not-overwrite")
    before = existing.read_bytes()
    with pytest.raises(ValueError, match="already exists"):
        provision(root)
    assert existing.read_bytes() == before


def test_symlink_target_and_unsafe_ancestor_fail_closed(tmp_path):
    root = prepare_root(tmp_path)
    plan = build_plan()
    leaf = target(root, plan["statePath"]).parent
    leaf.mkdir(mode=0o700)
    outside = tmp_path / "outside"
    outside.write_bytes(b"unchanged")
    target(root, plan["statePath"]).symlink_to(outside)
    with pytest.raises(ValueError, match="already exists"):
        provision(root)
    assert outside.read_bytes() == b"unchanged"

    second = tmp_path / "second"
    prepare_root(second).joinpath("var/lib/lumi").chmod(0o755)
    with pytest.raises(ValueError, match="ancestor is unsafe"):
        provision(second)


@pytest.mark.parametrize(("path", "value"), [
    (("planId",), "rp_" + "0" * 64),
    (("statePath",), "/tmp/replay.json"),
    (("lockPath",), "/tmp/replay.lock"),
    (("owner",), "root"),
    (("directoryMode",), "0750"),
    (("fileMode",), "0640"),
    (("capacity",), 1),
    (("executionEffect",), "WRITE"),
    (("actionAllowed",), True),
])
def test_plan_tamper_fails_closed(path, value):
    plan = copy.deepcopy(build_plan())
    plan[path[0]] = value
    with pytest.raises(ValueError):
        validate_plan(plan)


def test_provisioner_has_no_network_env_subprocess_print_or_secret_surface():
    source = inspect.getsource(sys.modules[
        "lumi.app.integration.shadow_replay_provisioning"]).lower()
    assert all(term not in source for term in (
        "requests", "urllib", "http://", "https://", "socket", "os.getenv",
        "environ", "subprocess", "print(", "logging"))
