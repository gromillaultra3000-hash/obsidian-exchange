import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "relay"))

from core.e5_key_boundary import build_key_boundary, validate_key_boundary


def boundary():
    return build_key_boundary(design_id="native_wallet_foundation")


def test_boundary_keeps_all_private_material_out_of_server_domain():
    value = boundary()
    server = value["components"]["server"]
    keystore = value["components"]["hardwareKeystore"]
    vault = value["components"]["encryptedWalletVault"]
    bridge = value["components"]["signingBridge"]
    assert server["mayReadSeedOrPrivateKey"] is False
    assert server["mayInvokeSigningWithoutUser"] is False
    assert keystore["wrappingKeyExportable"] is False
    assert keystore["maySignBitcoinTransaction"] is False
    assert vault["storesCiphertextOnly"] is True
    assert bridge["mustZeroizeWalletSecretAfterUse"] is True
    assert bridge["mayAcceptServerAuthorizationAsSufficient"] is False
    assert value["containsKeyMaterial"] is False
    assert validate_key_boundary(json.loads(json.dumps(value))) == value


def test_design_remains_blocked_until_network_recovery_and_build_work_exist():
    value = boundary()
    assert value["networkSelection"] == "BITCOIN_SIGNET_FIRST"
    assert value["walletKeyModel"] == "HARDWARE_WRAPPED_SOFTWARE_SECP256K1"
    assert value["hardwareNativeSecp256k1Claimed"] is False
    assert value["recoveryDesign"] == "REQUIRED_NOT_IMPLEMENTED"
    assert value["buildProvenance"] == "REQUIRED_NOT_IMPLEMENTED"
    assert value["signingImplemented"] is False
    assert value["productionReleaseAllowed"] is False
    assert value["executionEffect"] == "NONE"
    assert value["actionAllowed"] is False


@pytest.mark.parametrize("field,replacement", [
    ("serverCanSign", True),
    ("productionReleaseAllowed", True),
    ("signingImplemented", True),
    ("networkSelection", "BITCOIN_MAINNET"),
    ("hardwareNativeSecp256k1Claimed", True),
])
def test_tamper_cannot_claim_signing_or_readiness(field, replacement):
    value = copy.deepcopy(boundary())
    value[field] = replacement
    with pytest.raises(ValueError):
        validate_key_boundary(value)


def test_nested_capability_tamper_fails_closed():
    value = copy.deepcopy(boundary())
    value["components"]["server"]["mayReadSeedOrPrivateKey"] = True
    with pytest.raises(ValueError):
        validate_key_boundary(value)


def test_returned_nested_content_cannot_mutate_future_canonical_builds():
    first = boundary()
    first["components"]["server"]["mayReadSeedOrPrivateKey"] = True
    first["securityInvariants"].clear()
    second = boundary()
    assert second["components"]["server"]["mayReadSeedOrPrivateKey"] is False
    assert second["securityInvariants"]


def test_contract_has_no_key_network_storage_or_signing_surface():
    source = (ROOT / "relay/core/e5_key_boundary.py").read_text()
    for forbidden in (
        "sqlite", "psycopg", "requests", "httpx", "aiohttp", "socket",
        "os.environ", "subprocess", "mnemonic", "eth_account", "bitcoinlib",
        "send_crypto", "sign_transaction", "seed_value", "private_key_value",
    ):
        assert forbidden not in source
