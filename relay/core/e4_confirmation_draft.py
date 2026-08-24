"""Pure, unpersisted E4 confirmation draft; not a money intent."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from .e4_action_acknowledgement import validate_acknowledgement_receipt
from .e4_action_preview import validate_action_preview

SCHEMA = "wallet-action-confirmation-draft.v1"


def _hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def _digest(value: Any, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64 \
            or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{field} is invalid")
    return value


def _token(value: Any, field: str) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= 80 \
            or any(char not in "abcdefghijklmnopqrstuvwxyz0123456789_-" for char in value):
        raise ValueError(f"{field} is invalid")
    return value


def _time(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("createdAtEpochMs must be a positive integer")
    return value


def _destination(value: Mapping[str, Any], *, side: str,
                 custody_after: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {
            "kind", "network", "destinationFingerprintSha256"}:
        raise ValueError("destination summary schema is invalid")
    expected_kind = "WALLET_ADDRESS" if side == "BUY_CRYPTO" else "BANK_ACCOUNT"
    if value.get("kind") != expected_kind:
        raise ValueError("destination kind does not match action side")
    network = value.get("network")
    if expected_kind == "WALLET_ADDRESS":
        network = _token(network, "network")
    elif network is not None:
        raise ValueError("bank destination cannot declare a crypto network")
    return {"kind": expected_kind, "network": network,
            "destinationFingerprintSha256": _digest(
                value.get("destinationFingerprintSha256"),
                "destinationFingerprintSha256"),
            "custodyAfter": custody_after}


def build_confirmation_draft(*, preview: Mapping[str, Any],
                             challenge: Mapping[str, Any],
                             acknowledgement_receipt: Mapping[str, Any],
                             idempotency_key: str,
                             destination_summary: Mapping[str, Any],
                             created_at_epoch_ms: int) -> dict[str, Any]:
    action = validate_action_preview(preview)
    receipt = validate_acknowledgement_receipt(
        acknowledgement_receipt, preview=action, challenge=challenge)
    if receipt["confirmationEligible"] is not True or receipt["status"] != "ACKNOWLEDGED":
        raise ValueError("acknowledgement is not confirmation eligible")
    created = _time(created_at_epoch_ms)
    if not receipt["acknowledgedAtEpochMs"] <= created <= action["quote"]["expiresAtEpochMs"]:
        raise ValueError("confirmation draft time is invalid")
    idempotency_hash = _hash({"scope": "E4_CONFIRMATION_DRAFT",
                              "key": _token(idempotency_key, "idempotencyKey")})
    destination = _destination(
        destination_summary, side=action["side"],
        custody_after=action["custody"]["after"])
    unsigned = {
        "schemaVersion": SCHEMA, "previewId": action["previewId"],
        "acknowledgementReceiptId": receipt["receiptId"],
        "lane": action["lane"], "side": action["side"],
        "executor": action["executor"], "amounts": action["amounts"],
        "destination": destination,
        "idempotencyKeySha256": idempotency_hash,
        "quoteExpiresAtEpochMs": action["quote"]["expiresAtEpochMs"],
        "createdAtEpochMs": created, "status": "DRAFT_ONLY",
        "persisted": False, "serverAuthenticationSatisfied": False,
        "serverStateChecksSatisfied": False, "moneyIntentAllowed": False,
        "containsSecrets": False, "executionEffect": "NONE", "actionAllowed": False,
    }
    return {**unsigned, "draftId": "wacd_" + _hash(unsigned)}


def validate_confirmation_draft(value: Mapping[str, Any], *,
                                preview: Mapping[str, Any],
                                challenge: Mapping[str, Any],
                                acknowledgement_receipt: Mapping[str, Any],
                                idempotency_key: str) -> dict[str, Any]:
    required = {"schemaVersion", "draftId", "previewId",
                "acknowledgementReceiptId", "lane", "side", "executor",
                "amounts", "destination", "idempotencyKeySha256", "quoteExpiresAtEpochMs",
                "createdAtEpochMs", "status",
                "persisted", "serverAuthenticationSatisfied",
                "serverStateChecksSatisfied", "moneyIntentAllowed", "containsSecrets",
                "executionEffect", "actionAllowed"}
    if not isinstance(value, Mapping) or set(value) != required \
            or value.get("schemaVersion") != SCHEMA or value.get("status") != "DRAFT_ONLY" \
            or any(value.get(field) is not False for field in (
                "persisted", "serverAuthenticationSatisfied", "serverStateChecksSatisfied",
                "moneyIntentAllowed", "containsSecrets", "actionAllowed")) \
            or value.get("executionEffect") != "NONE":
        raise ValueError("confirmation draft schema is invalid")
    destination = value.get("destination")
    if not isinstance(destination, Mapping) or set(destination) != {
            "kind", "network", "destinationFingerprintSha256", "custodyAfter"}:
        raise ValueError("confirmation destination schema is invalid")
    rebuilt = build_confirmation_draft(
        preview=preview, challenge=challenge,
        acknowledgement_receipt=acknowledgement_receipt,
        idempotency_key=idempotency_key,
        destination_summary={key: destination[key] for key in (
            "kind", "network", "destinationFingerprintSha256")},
        created_at_epoch_ms=value["createdAtEpochMs"])
    if rebuilt != dict(value):
        raise ValueError("confirmation draft does not match acknowledged preview")
    return rebuilt
