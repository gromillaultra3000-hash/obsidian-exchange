"""Pure E5 technology-selection contract; installs no toolchain or mobile code."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from core.e5_key_boundary import validate_key_boundary

SCHEMA = "native-wallet-technology-selection.v1"


def _hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def build_technology_selection(*, boundary: Mapping[str, Any]) -> dict[str, Any]:
    key_boundary = validate_key_boundary(boundary)
    unsigned = {
        "schemaVersion": SCHEMA,
        "boundaryId": key_boundary["boundaryId"],
        "decisionStatus": "SELECTED_FOR_HERMETIC_SCAFFOLD",
        "firstNetwork": "BITCOIN_SIGNET",
        "productionNetwork": "UNSELECTED",
        "ios": {"language": "SWIFT", "ui": "SWIFTUI", "nativeShell": True},
        "android": {
            "language": "KOTLIN", "ui": "JETPACK_COMPOSE", "nativeShell": True,
        },
        "sharedCore": {
            "language": "RUST", "toolchain": "PIN_REQUIRED",
            "ffi": "UNIFFI", "unsafeCodeDefaultDenied": True,
        },
        "bitcoin": {
            "curve": "SECP256K1", "signer": "BITCOIN_CORE_LIBSECP256K1_FAMILY",
            "signetFirst": True, "mainnetEnabled": False,
        },
        "keyProtection": {
            "model": "HARDWARE_WRAPPED_SOFTWARE_SECP256K1",
            "iosWrapping": "CRYPTOKIT_SECURE_ENCLAVE_P256_DERIVED_WRAP",
            "androidWrapping": "ANDROID_KEYSTORE_STRONGBOX_PREFERRED_AES_GCM",
            "plaintextPersistenceAllowed": False,
            "boundedMemoryAndZeroizationRequired": True,
        },
        "integrity": {
            "ios": "APP_ATTEST_SERVER_VERIFIED_RISK_SIGNAL",
            "android": "PLAY_INTEGRITY_SERVER_VERIFIED_RISK_SIGNAL",
            "sufficientForSigningAuthorization": False,
        },
        "supplyChain": {
            "pinnedToolchainsRequired": True, "lockfilesRequired": True,
            "sbomRequired": True, "provenanceRequired": True,
            "reproducibleReleaseEvidenceRequired": True,
            "twoPersonReleaseApprovalRequired": True,
        },
        "explicitlyDeferred": [
            "REAL_SEED_GENERATION", "REAL_KEY_DERIVATION", "TRANSACTION_SIGNING",
            "BITCOIN_MAINNET", "EVM", "TRON", "LITECOIN", "MPC",
            "EXTERNAL_HARDWARE_WALLET",
        ],
        "containsKeyMaterial": False, "toolchainPinRecorded": True,
        "rustScaffoldDefined": True, "nativeShellScaffoldsCreated": False,
        "rustsecAuditRequired": True, "rustsecAuditPassed": False,
        "signingImplemented": False,
        "productionReleaseAllowed": False, "executionEffect": "NONE",
        "actionAllowed": False,
    }
    return {**unsigned, "selectionId": "nwts_" + _hash(unsigned)}


def validate_technology_selection(
        value: Mapping[str, Any], *, boundary: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or value.get("schemaVersion") != SCHEMA:
        raise ValueError("technology selection schema is invalid")
    rebuilt = build_technology_selection(boundary=boundary)
    if rebuilt != dict(value):
        raise ValueError("technology selection does not match canonical decision")
    return rebuilt
