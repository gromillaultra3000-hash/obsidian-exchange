import copy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "relay"))

from core.e5_key_boundary import build_key_boundary
from core.e5_recovery_policy import build_recovery_policy, validate_recovery_policy


def boundary():
    return build_key_boundary(design_id="native_wallet_foundation")


def policy(**changes):
    values = dict(
        boundary=boundary(), policy_id="dual_path_recovery",
        guardian_trust_domains=["trusted_device", "family_guardian", "offline_guardian"],
    )
    values.update(changes)
    return build_recovery_policy(**values)


def test_dual_path_policy_is_canonical_and_server_cannot_recover():
    value = policy()
    assert value["recoveryPaths"]["offlineSeed"] == {
        "enabled": True, "userControlled": True, "serverRequired": False,
        "serverMayReceiveSeed": False, "localRestoreOnly": True,
    }
    guardians = value["recoveryPaths"]["thresholdGuardians"]
    assert guardians["threshold"] == 2
    assert guardians["guardianCount"] == 3
    assert value["serverCanRecover"] is False
    assert validate_recovery_policy(value, boundary=boundary()) == value


@pytest.mark.parametrize("domains", [
    ["trusted_device", "family_guardian"],
    ["trusted_device", "trusted_device", "offline_guardian"],
    ["server", "family_guardian", "offline_guardian"],
    ["operator", "family_guardian", "offline_guardian"],
])
def test_guardians_must_be_three_independent_non_server_domains(domains):
    with pytest.raises(ValueError):
        policy(guardian_trust_domains=domains)


@pytest.mark.parametrize("path,field,replacement", [
    (("recoveryPaths", "offlineSeed"), "serverMayReceiveSeed", True),
    (("recoveryPaths", "thresholdGuardians"), "serverMayHoldRecoveryShare", True),
    (("recoveryPaths", "thresholdGuardians"), "threshold", 1),
    (("rollbackResistance",), "oldBackupCannotLowerEpoch", False),
    (("abuseResistance",), "supportOverrideForbidden", False),
    (("abuseResistance",), "recoveryDelayHours", 0),
    (("backupRequirements",), "plaintextCloudBackupForbidden", False),
    ((), "serverCanRecover", True),
    ((), "recoveryImplemented", True),
    ((), "productionReleaseAllowed", True),
    ((), "actionAllowed", True),
])
def test_security_or_capability_tamper_fails(path, field, replacement):
    changed = copy.deepcopy(policy())
    target = changed
    for segment in path:
        target = target[segment]
    target[field] = replacement
    with pytest.raises(ValueError):
        validate_recovery_policy(changed, boundary=boundary())


def test_contract_has_no_secret_crypto_sdk_storage_network_or_recovery_surface():
    source = (ROOT / "relay/core/e5_recovery_policy.py").read_text().lower()
    for forbidden in (
        "sqlite", "psycopg", "requests", "httpx", "aiohttp", "socket",
        "os.environ", "subprocess", "mnemonic", "eth_account", "bitcoinlib",
        "sign_transaction", "private_key", "seed_phrase", "shamir",
        "keychain", "keystore", "android", "ios", "cloudkit",
    ):
        assert forbidden not in source
