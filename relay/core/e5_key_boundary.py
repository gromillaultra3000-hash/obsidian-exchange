"""Pure E5 native-wallet key boundary; contains no signing implementation."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any, Mapping

SCHEMA = "native-wallet-key-boundary.v2"

_COMPONENTS = {
    "nativeApp": {
        "trustDomain": "USER_DEVICE",
        "mayRequestSigning": True,
        "mayReadPrivateKey": False,
    },
    "hardwareKeystore": {
        "trustDomain": "HARDWARE_BACKED_DEVICE_STORAGE",
        "mayGenerateWrappingKey": True,
        "mayWrapWalletSecret": True,
        "maySignBitcoinTransaction": False,
        "wrappingKeyExportable": False,
    },
    "encryptedWalletVault": {
        "trustDomain": "USER_DEVICE_ENCRYPTED_STORAGE",
        "storesCiphertextOnly": True,
        "mayContainPlaintextWalletSecret": False,
        "serverReadable": False,
    },
    "signingBridge": {
        "trustDomain": "NATIVE_PROCESS",
        "maySignOnlyAfterLocalAuthorization": True,
        "mayUnwrapWalletSecretInProtectedMemory": True,
        "mustZeroizeWalletSecretAfterUse": True,
        "mayPersistPlaintextWalletSecret": False,
        "mayExportWalletSecret": False,
        "mayAcceptServerAuthorizationAsSufficient": False,
    },
    "server": {
        "trustDomain": "REMOTE_UNTRUSTED_FOR_SIGNING",
        "mayBuildUnsignedRequest": True,
        "mayBroadcastSignedTransaction": True,
        "mayReadSeedOrPrivateKey": False,
        "mayInvokeSigningWithoutUser": False,
    },
}

_INVARIANTS = [
    "WALLET_SECRET_GENERATED_ON_USER_DEVICE",
    "WALLET_SECRET_NEVER_SENT_TO_SERVER",
    "WALLET_SECRET_ENCRYPTED_AT_REST_BY_NON_EXPORTABLE_HARDWARE_BACKED_WRAPPING_KEY",
    "PLAINTEXT_WALLET_SECRET_EXISTS_ONLY_IN_BOUNDED_PROTECTED_PROCESS_MEMORY",
    "PLAINTEXT_WALLET_SECRET_ZEROIZED_AFTER_SIGN_OR_FAILURE",
    "LOCAL_USER_AUTHORIZATION_REQUIRED_FOR_EACH_SIGNATURE",
    "TRANSACTION_SUMMARY_DISPLAYED_FROM_SIGNED_PREIMAGE",
    "SERVER_AUTHORIZATION_NEVER_SUFFICIENT_FOR_SIGNATURE",
    "SIGNED_BYTES_BOUND_TO_DISPLAYED_NETWORK_DESTINATION_AMOUNT_AND_FEE",
    "BACKUP_RESTORE_PROVEN_BEFORE_PRODUCTION",
]

_FORBIDDEN_SERVER_INPUTS = [
    "SEED_PHRASE", "PRIVATE_KEY", "KEYSTORE_EXPORT", "BIOMETRIC_TEMPLATE",
    "LOCAL_AUTHENTICATOR_SECRET",
]


def _hash(value: Mapping[str, Any]) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def build_key_boundary(*, design_id: str) -> dict[str, Any]:
    if not isinstance(design_id, str) or not 1 <= len(design_id) <= 64 \
            or any(char not in "abcdefghijklmnopqrstuvwxyz0123456789_-" for char in design_id):
        raise ValueError("designId is invalid")
    unsigned = {
        "schemaVersion": SCHEMA,
        "designId": design_id,
        "components": deepcopy(_COMPONENTS),
        "securityInvariants": list(_INVARIANTS),
        "forbiddenServerInputs": list(_FORBIDDEN_SERVER_INPUTS),
        "networkSelection": "BITCOIN_SIGNET_FIRST",
        "walletKeyModel": "HARDWARE_WRAPPED_SOFTWARE_SECP256K1",
        "hardwareNativeSecp256k1Claimed": False,
        "recoveryDesign": "REQUIRED_NOT_IMPLEMENTED",
        "buildProvenance": "REQUIRED_NOT_IMPLEMENTED",
        "status": "DESIGN_ONLY",
        "containsKeyMaterial": False,
        "signingImplemented": False,
        "serverCanSign": False,
        "productionReleaseAllowed": False,
        "executionEffect": "NONE",
        "actionAllowed": False,
    }
    return {**unsigned, "boundaryId": "nwkb_" + _hash(unsigned)}


def validate_key_boundary(value: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "schemaVersion", "boundaryId", "designId", "components",
        "securityInvariants", "forbiddenServerInputs", "networkSelection",
        "walletKeyModel", "hardwareNativeSecp256k1Claimed",
        "recoveryDesign", "buildProvenance", "status", "containsKeyMaterial",
        "signingImplemented", "serverCanSign", "productionReleaseAllowed",
        "executionEffect", "actionAllowed",
    }
    if not isinstance(value, Mapping) or set(value) != required \
            or value.get("schemaVersion") != SCHEMA:
        raise ValueError("key boundary schema is invalid")
    rebuilt = build_key_boundary(design_id=value.get("designId"))
    if rebuilt != dict(value):
        raise ValueError("key boundary does not match canonical content")
    return rebuilt
