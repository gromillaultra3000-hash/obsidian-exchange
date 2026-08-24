"""Pure E5 transaction-display consent contracts; never signs anything."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from core.e5_key_boundary import validate_key_boundary

REQUEST_SCHEMA = "native-signing-display-request.v1"
RECEIPT_SCHEMA = "native-signing-consent-receipt.v1"
NETWORK = "SYNTHETIC_TESTNET_V1"
ASSET = "TST"


def _hash(value: Mapping[str, Any]) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def _digest(value: Any, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64 \
            or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{field} must be a lowercase SHA-256 digest")
    return value


def _token(value: Any, field: str) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= 64 \
            or any(char not in "abcdefghijklmnopqrstuvwxyz0123456789_-" for char in value):
        raise ValueError(f"{field} is invalid")
    return value


def _time(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field} must be a positive integer")
    return value


def _amount(value: Any, field: str, *, allow_zero: bool = False) -> str:
    if not isinstance(value, str) or len(value) > 48:
        raise ValueError(f"{field} must be a decimal string")
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"{field} must be a decimal string") from exc
    if not number.is_finite() or number < 0 or (number == 0 and not allow_zero):
        raise ValueError(f"{field} is outside bounds")
    canonical = format(number, "f")
    if "." in canonical:
        canonical = canonical.rstrip("0").rstrip(".")
    if canonical != value:
        raise ValueError(f"{field} must be canonical")
    return canonical


def _destination(value: Any) -> str:
    if not isinstance(value, str) or not 12 <= len(value) <= 96 \
            or not value.startswith("tst1") \
            or any(char not in "023456789acdefghjklmnpqrstuvwxyz" for char in value[4:]):
        raise ValueError("destination is invalid for synthetic profile")
    return value


def build_signing_display_request(
        *, boundary: Mapping[str, Any], request_nonce: str,
        unsigned_payload_sha256: str, destination: str, amount: str, fee: str,
        created_at_epoch_ms: int, expires_at_epoch_ms: int) -> dict[str, Any]:
    key_boundary = validate_key_boundary(boundary)
    created = _time(created_at_epoch_ms, "createdAtEpochMs")
    expires = _time(expires_at_epoch_ms, "expiresAtEpochMs")
    if not created < expires <= created + 2 * 60 * 1000:
        raise ValueError("request lifetime is invalid")
    display = {
        "network": NETWORK, "asset": ASSET,
        "destination": _destination(destination),
        "amount": _amount(amount, "amount"),
        "fee": _amount(fee, "fee", allow_zero=True),
    }
    unsigned = {
        "schemaVersion": REQUEST_SCHEMA,
        "boundaryId": key_boundary["boundaryId"],
        "requestNonce": _token(request_nonce, "requestNonce"),
        "unsignedPayloadSha256": _digest(
            unsigned_payload_sha256, "unsignedPayloadSha256"),
        "display": display,
        "displayBindingSha256": _hash({
            "unsignedPayloadSha256": unsigned_payload_sha256, "display": display,
        }),
        "createdAtEpochMs": created, "expiresAtEpochMs": expires,
        "networkProfile": "SYNTHETIC_ONLY",
        "containsKeyMaterial": False, "containsBiometricData": False,
        "signaturePresent": False, "signingAllowed": False,
        "productionNetworkAllowed": False, "executionEffect": "NONE",
        "actionAllowed": False,
    }
    return {**unsigned, "requestId": "nsdr_" + _hash(unsigned)}


def validate_signing_display_request(
        value: Mapping[str, Any], *, boundary: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "schemaVersion", "requestId", "boundaryId", "requestNonce",
        "unsignedPayloadSha256", "display", "displayBindingSha256",
        "createdAtEpochMs", "expiresAtEpochMs", "networkProfile",
        "containsKeyMaterial", "containsBiometricData", "signaturePresent",
        "signingAllowed", "productionNetworkAllowed", "executionEffect",
        "actionAllowed",
    }
    if not isinstance(value, Mapping) or set(value) != required \
            or value.get("schemaVersion") != REQUEST_SCHEMA:
        raise ValueError("signing display request schema is invalid")
    display = value.get("display")
    if not isinstance(display, Mapping) or set(display) != {
            "network", "asset", "destination", "amount", "fee"} \
            or display.get("network") != NETWORK or display.get("asset") != ASSET:
        raise ValueError("signing display is invalid")
    rebuilt = build_signing_display_request(
        boundary=boundary, request_nonce=value.get("requestNonce"),
        unsigned_payload_sha256=value.get("unsignedPayloadSha256"),
        destination=display.get("destination"), amount=display.get("amount"),
        fee=display.get("fee"), created_at_epoch_ms=value.get("createdAtEpochMs"),
        expires_at_epoch_ms=value.get("expiresAtEpochMs"))
    if rebuilt != dict(value):
        raise ValueError("signing display request does not match canonical content")
    return rebuilt


def build_signing_consent_receipt(
        *, request: Mapping[str, Any], boundary: Mapping[str, Any],
        first_interaction_id: str, confirm_interaction_id: str,
        displayed_at_epoch_ms: int, confirmed_at_epoch_ms: int) -> dict[str, Any]:
    candidate = validate_signing_display_request(request, boundary=boundary)
    first = _token(first_interaction_id, "firstInteractionId")
    confirm = _token(confirm_interaction_id, "confirmInteractionId")
    displayed = _time(displayed_at_epoch_ms, "displayedAtEpochMs")
    confirmed = _time(confirmed_at_epoch_ms, "confirmedAtEpochMs")
    if first == confirm:
        raise ValueError("confirmation requires a distinct interaction")
    if displayed < candidate["createdAtEpochMs"] \
            or confirmed < displayed + 750 \
            or confirmed > candidate["expiresAtEpochMs"]:
        raise ValueError("confirmation timing is invalid")
    unsigned = {
        "schemaVersion": RECEIPT_SCHEMA,
        "requestId": candidate["requestId"],
        "boundaryId": candidate["boundaryId"],
        "unsignedPayloadSha256": candidate["unsignedPayloadSha256"],
        "displayBindingSha256": candidate["displayBindingSha256"],
        "firstInteractionIdSha256": hashlib.sha256(first.encode()).hexdigest(),
        "confirmInteractionIdSha256": hashlib.sha256(confirm.encode()).hexdigest(),
        "displayedAtEpochMs": displayed, "confirmedAtEpochMs": confirmed,
        "status": "LOCAL_CONSENT_RECORDED_OFFLINE",
        "localAuthenticatorVerified": False,
        "containsKeyMaterial": False, "containsBiometricData": False,
        "signaturePresent": False, "signingAllowed": False,
        "productionNetworkAllowed": False, "executionEffect": "NONE",
        "actionAllowed": False,
    }
    return {**unsigned, "receiptId": "nscr_" + _hash(unsigned)}


def validate_signing_consent_receipt(
        value: Mapping[str, Any], *, request: Mapping[str, Any],
        boundary: Mapping[str, Any], first_interaction_id: str,
        confirm_interaction_id: str) -> dict[str, Any]:
    required = {
        "schemaVersion", "receiptId", "requestId", "boundaryId",
        "unsignedPayloadSha256", "displayBindingSha256",
        "firstInteractionIdSha256", "confirmInteractionIdSha256",
        "displayedAtEpochMs", "confirmedAtEpochMs", "status",
        "localAuthenticatorVerified", "containsKeyMaterial",
        "containsBiometricData", "signaturePresent", "signingAllowed",
        "productionNetworkAllowed", "executionEffect", "actionAllowed",
    }
    if not isinstance(value, Mapping) or set(value) != required \
            or value.get("schemaVersion") != RECEIPT_SCHEMA:
        raise ValueError("signing consent receipt schema is invalid")
    rebuilt = build_signing_consent_receipt(
        request=request, boundary=boundary,
        first_interaction_id=first_interaction_id,
        confirm_interaction_id=confirm_interaction_id,
        displayed_at_epoch_ms=value.get("displayedAtEpochMs"),
        confirmed_at_epoch_ms=value.get("confirmedAtEpochMs"))
    if rebuilt != dict(value):
        raise ValueError("signing consent receipt does not match canonical content")
    return rebuilt
