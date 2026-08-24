import copy
import inspect
import json
import os
import stat
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "lumi") not in sys.path:
    sys.path.insert(0, str(ROOT / "lumi"))

from lumi.app.integration.shadow_key_provisioning import (
    build_plan, provision_service_keys, validate_plan,
)
from lumi.app.integration.shadow_public_keyring import load_keyring, resolve_public_key

NOW = 1786424405
GROUPS = {"kairos-svc": os.getgid(), "lumi-svc": os.getgid()}
PRIVATE = {
    "KAIROS_TO_LUMI": Ed25519PrivateKey.from_private_bytes(bytes(range(1, 33))),
    "LUMI_TO_KAIROS": Ed25519PrivateKey.from_private_bytes(bytes(range(65, 97))),
}


def factory(direction):
    private = PRIVATE[direction]
    return private.private_bytes_raw(), private.public_key().public_bytes_raw()


def logical(root, value):
    return root.joinpath(*Path(value).parts[1:])


def test_frozen_two_direction_ownership_plan_is_exact():
    expected = json.loads((
        ROOT / "contracts/e2-shadow/service-key-plan.v1.json").read_text())
    assert build_plan(generated_at=NOW) == expected
    assert validate_plan(expected) == expected
    first, second = expected["identities"]
    assert first["privateGroup"] == "kairos-svc"
    assert first["publicGroup"] == "lumi-svc"
    assert second["privateGroup"] == "lumi-svc"
    assert second["publicGroup"] == "kairos-svc"
    assert expected["executionEffect"] == "NONE" and expected["actionAllowed"] is False


def test_provisioner_creates_separated_private_keys_and_opposite_public_keyrings(tmp_path):
    plan = build_plan(generated_at=NOW)
    report = provision_service_keys(
        plan, root=tmp_path, owner_uid=os.getuid(), group_ids=GROUPS,
        key_factory=factory)
    assert report == {
        "schemaVersion": "shadow-service-key-provisioning.v1",
        "planId": plan["planId"], "status": "PROVISIONED",
        "keyIds": ["kairos-shadow-v1", "lumi-shadow-v1"],
        "privateKeyCount": 2, "publicKeyringCount": 2,
        "secretsExposed": False, "executionEffect": "KEY_FILES_CREATED",
        "actionAllowed": False,
    }
    for identity in plan["identities"]:
        private_path = logical(tmp_path, identity["privatePath"])
        public_path = logical(tmp_path, identity["publicKeyringPath"])
        assert stat.S_IMODE(private_path.stat().st_mode) == 0o640
        assert stat.S_IMODE(public_path.stat().st_mode) == 0o640
        assert stat.S_IMODE(private_path.parent.stat().st_mode) == 0o750
        assert stat.S_IMODE(public_path.parent.stat().st_mode) == 0o750
        assert len(private_path.read_text().strip()) == 43
        keyring = load_keyring(
            public_path, expected_audience=identity["audience"])
        public = resolve_public_key(
            keyring, key_id=identity["keyId"], at_epoch=NOW,
            expected_audience=identity["audience"])
        assert public == PRIVATE[identity["direction"]].public_key().public_bytes_raw()


@pytest.mark.parametrize("fault_after", [1, 2, 3, 4])
def test_fault_rolls_back_every_key_file_without_partial_identity(tmp_path, fault_after):
    plan = build_plan(generated_at=NOW)
    with pytest.raises(RuntimeError, match="injected"):
        provision_service_keys(
            plan, root=tmp_path, owner_uid=os.getuid(), group_ids=GROUPS,
            key_factory=factory, fault_after_writes=fault_after)
    for identity in plan["identities"]:
        assert not logical(tmp_path, identity["privatePath"]).exists()
        assert not logical(tmp_path, identity["publicKeyringPath"]).exists()


def test_existing_or_partial_target_fails_without_overwrite(tmp_path):
    plan = build_plan(generated_at=NOW)
    target = logical(tmp_path, plan["identities"][0]["privatePath"])
    target.parent.mkdir(parents=True)
    target.write_text("do-not-overwrite")
    before = target.read_bytes()
    with pytest.raises(ValueError, match="already exists"):
        provision_service_keys(
            plan, root=tmp_path, owner_uid=os.getuid(), group_ids=GROUPS,
            key_factory=factory)
    assert target.read_bytes() == before


def test_symlink_target_fails_without_following_it(tmp_path):
    plan = build_plan(generated_at=NOW)
    outside = tmp_path / "outside"
    outside.write_text("unchanged")
    target = logical(tmp_path, plan["identities"][1]["publicKeyringPath"])
    target.parent.mkdir(parents=True)
    target.symlink_to(outside)
    with pytest.raises(ValueError, match="already exists"):
        provision_service_keys(
            plan, root=tmp_path, owner_uid=os.getuid(), group_ids=GROUPS,
            key_factory=factory)
    assert outside.read_text() == "unchanged"


def test_invalid_key_factory_rolls_back_prior_files(tmp_path):
    plan = build_plan(generated_at=NOW)

    def invalid(direction):
        return (b"short", b"short") if direction == "LUMI_TO_KAIROS" else factory(direction)

    with pytest.raises(ValueError, match="invalid material"):
        provision_service_keys(
            plan, root=tmp_path, owner_uid=os.getuid(), group_ids=GROUPS,
            key_factory=invalid)
    assert not any(tmp_path.rglob("*.key"))
    assert not any(tmp_path.rglob("*.json"))


@pytest.mark.parametrize(("path", "value"), [
    (("planId",), "kp_" + "0" * 64),
    (("validUntil",), NOW + 1),
    (("executionEffect",), "WRITE"),
    (("actionAllowed",), True),
    (("identities", 0, "privateGroup"), "lumi-svc"),
    (("identities", 0, "privatePath"), "/tmp/key"),
    (("identities", 1, "audience"), "lumi-shadow"),
    (("identities", 1, "scope"), "shadow:write"),
])
def test_plan_tamper_fails_closed(path, value):
    plan = copy.deepcopy(build_plan(generated_at=NOW))
    target = plan
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValueError):
        validate_plan(plan)


def test_provisioner_has_no_network_env_subprocess_print_or_secret_logging():
    source = inspect.getsource(sys.modules[
        "lumi.app.integration.shadow_key_provisioning"]).lower()
    assert all(term not in source for term in (
        "requests", "urllib", "http://", "https://", "socket", "os.getenv",
        "environ", "subprocess", "print(", "logging", "private_raw.hex",
        "private_raw.decode"))
