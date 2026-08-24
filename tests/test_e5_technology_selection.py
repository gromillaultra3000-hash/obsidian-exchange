import copy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "relay"))

from core.e5_key_boundary import build_key_boundary
from core.e5_technology_selection import build_technology_selection, validate_technology_selection


def selection():
    boundary = build_key_boundary(design_id="native_wallet_foundation")
    return boundary, build_technology_selection(boundary=boundary)


def test_competitive_native_stack_is_frozen_for_hermetic_scaffold_only():
    boundary, value = selection()
    assert value["ios"] == {"language": "SWIFT", "ui": "SWIFTUI", "nativeShell": True}
    assert value["android"]["ui"] == "JETPACK_COMPOSE"
    assert value["sharedCore"]["language"] == "RUST"
    assert value["sharedCore"]["ffi"] == "UNIFFI"
    assert value["firstNetwork"] == "BITCOIN_SIGNET"
    assert value["bitcoin"]["mainnetEnabled"] is False
    assert value["toolchainPinRecorded"] is True
    assert value["rustScaffoldDefined"] is True
    assert value["nativeShellScaffoldsCreated"] is False
    assert value["rustsecAuditRequired"] is True
    assert value["rustsecAuditPassed"] is False
    assert validate_technology_selection(value, boundary=boundary) == value


def test_key_model_is_truthful_about_software_secp256k1():
    _, value = selection()
    protection = value["keyProtection"]
    assert protection["model"] == "HARDWARE_WRAPPED_SOFTWARE_SECP256K1"
    assert protection["plaintextPersistenceAllowed"] is False
    assert protection["boundedMemoryAndZeroizationRequired"] is True
    assert value["integrity"]["sufficientForSigningAuthorization"] is False


def test_real_keys_signing_mainnet_and_extra_chains_are_deferred():
    _, value = selection()
    for capability in (
        "REAL_SEED_GENERATION", "REAL_KEY_DERIVATION", "TRANSACTION_SIGNING",
        "BITCOIN_MAINNET", "EVM", "TRON", "LITECOIN",
    ):
        assert capability in value["explicitlyDeferred"]
    assert value["containsKeyMaterial"] is False
    assert value["signingImplemented"] is False
    assert value["productionReleaseAllowed"] is False
    assert value["actionAllowed"] is False


@pytest.mark.parametrize("path,replacement", [
    (("firstNetwork",), "BITCOIN_MAINNET"),
    (("bitcoin", "mainnetEnabled"), True),
    (("keyProtection", "plaintextPersistenceAllowed"), True),
    (("integrity", "sufficientForSigningAuthorization"), True),
    (("sharedCore", "unsafeCodeDefaultDenied"), False),
    (("rustsecAuditPassed",), True),
    (("signingImplemented",), True), (("actionAllowed",), True),
])
def test_selection_tamper_fails_closed(path, replacement):
    boundary, value = selection(); changed = copy.deepcopy(value)
    target = changed
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = replacement
    with pytest.raises(ValueError):
        validate_technology_selection(changed, boundary=boundary)


def test_contract_has_no_install_network_storage_or_key_surface():
    source = (ROOT / "relay/core/e5_technology_selection.py").read_text().lower()
    for forbidden in (
        "open(", "read_text", "subprocess", "requests", "httpx", "socket",
        "os.environ", "rustup", "cargo install", "mnemonic", "private_key",
        "seed_phrase", "sign_transaction",
    ):
        assert forbidden not in source
