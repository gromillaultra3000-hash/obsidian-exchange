"""Pure deliberate acknowledgement gate for one exact E4 action preview."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence

from .e4_action_preview import validate_action_preview

CHALLENGE_SCHEMA = "wallet-action-acknowledgement-challenge.v1"
RECEIPT_SCHEMA = "wallet-action-acknowledgement-receipt.v1"
ACKNOWLEDGEMENTS = (
    "EXECUTOR_UNDERSTOOD", "CUSTODY_UNDERSTOOD", "KYC_UNDERSTOOD",
    "TOTAL_FEES_UNDERSTOOD", "IRREVERSIBILITY_UNDERSTOOD",
)
MIN_DELIBERATION_MS = 750
MAX_CHALLENGE_MS = 2 * 60 * 1000


def _hash(value: Mapping[str, Any]) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def _token(value: Any, field: str) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= 80 \
            or any(char not in "abcdefghijklmnopqrstuvwxyz0123456789_-" for char in value):
        raise ValueError(f"{field} is invalid")
    return value


def _time(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field} must be a positive integer")
    return value


def build_acknowledgement_challenge(*, preview: Mapping[str, Any],
                                    presentation_id: str,
                                    issued_at_epoch_ms: int) -> dict[str, Any]:
    action = validate_action_preview(preview)
    issued = _time(issued_at_epoch_ms, "issuedAtEpochMs")
    if not action["quote"]["quotedAtEpochMs"] <= issued < action["quote"]["expiresAtEpochMs"]:
        raise ValueError("challenge must be issued while quote is current")
    expires = min(issued + MAX_CHALLENGE_MS, action["quote"]["expiresAtEpochMs"])
    unsigned = {
        "schemaVersion": CHALLENGE_SCHEMA, "previewId": action["previewId"],
        "presentationId": _token(presentation_id, "presentationId"),
        "issuedAtEpochMs": issued, "expiresAtEpochMs": expires,
        "requiredAcknowledgements": list(ACKNOWLEDGEMENTS),
        "minimumDeliberationMs": MIN_DELIBERATION_MS,
        "secondInteractionRequired": True, "containsSecrets": False,
        "moneyIntentAllowed": False, "executionEffect": "NONE", "actionAllowed": False,
    }
    return {**unsigned, "challengeId": "waac_" + _hash(unsigned)}


def validate_acknowledgement_challenge(value: Mapping[str, Any], *,
                                       preview: Mapping[str, Any]) -> dict[str, Any]:
    required = {"schemaVersion", "challengeId", "previewId", "presentationId",
                "issuedAtEpochMs", "expiresAtEpochMs", "requiredAcknowledgements",
                "minimumDeliberationMs", "secondInteractionRequired", "containsSecrets",
                "moneyIntentAllowed", "executionEffect", "actionAllowed"}
    if not isinstance(value, Mapping) or set(value) != required \
            or value.get("schemaVersion") != CHALLENGE_SCHEMA \
            or value.get("secondInteractionRequired") is not True \
            or value.get("containsSecrets") is not False \
            or value.get("moneyIntentAllowed") is not False \
            or value.get("executionEffect") != "NONE" \
            or value.get("actionAllowed") is not False:
        raise ValueError("acknowledgement challenge schema is invalid")
    rebuilt = build_acknowledgement_challenge(
        preview=preview, presentation_id=value["presentationId"],
        issued_at_epoch_ms=value["issuedAtEpochMs"])
    if rebuilt != dict(value):
        raise ValueError("acknowledgement challenge does not match preview")
    return rebuilt


def acknowledge_action_preview(*, preview: Mapping[str, Any],
                               challenge: Mapping[str, Any], interaction_id: str,
                               acknowledged: Sequence[str],
                               acknowledged_at_epoch_ms: int) -> dict[str, Any]:
    action = validate_action_preview(preview)
    gate = validate_acknowledgement_challenge(challenge, preview=action)
    interaction = _token(interaction_id, "interactionId")
    accepted_at = _time(acknowledged_at_epoch_ms, "acknowledgedAtEpochMs")
    if interaction == gate["presentationId"]:
        raise ValueError("acknowledgement must be a second interaction")
    if not isinstance(acknowledged, Sequence) or isinstance(acknowledged, (str, bytes)) \
            or list(acknowledged) != list(ACKNOWLEDGEMENTS):
        raise ValueError("all acknowledgements must be explicit and ordered")
    blockers = []
    if accepted_at < gate["issuedAtEpochMs"] + gate["minimumDeliberationMs"]:
        blockers.append("DELIBERATION_TOO_SHORT")
    if accepted_at > gate["expiresAtEpochMs"]:
        blockers.append("CHALLENGE_OR_QUOTE_EXPIRED")
    if action["availability"] != "AVAILABLE":
        blockers.append("LANE_NOT_AVAILABLE")
    eligible = not blockers
    unsigned = {
        "schemaVersion": RECEIPT_SCHEMA, "previewId": action["previewId"],
        "challengeId": gate["challengeId"], "interactionId": interaction,
        "acknowledgedAtEpochMs": accepted_at,
        "acknowledged": list(ACKNOWLEDGEMENTS),
        "status": "ACKNOWLEDGED" if eligible else "NO_GO", "blockers": blockers,
        "confirmationEligible": eligible, "moneyIntentAllowed": False,
        "containsSecrets": False, "executionEffect": "NONE", "actionAllowed": False,
    }
    return {**unsigned, "receiptId": "waar_" + _hash(unsigned)}


def validate_acknowledgement_receipt(value: Mapping[str, Any], *,
                                     preview: Mapping[str, Any],
                                     challenge: Mapping[str, Any]) -> dict[str, Any]:
    required = {"schemaVersion", "receiptId", "previewId", "challengeId",
                "interactionId", "acknowledgedAtEpochMs", "acknowledged", "status",
                "blockers", "confirmationEligible", "moneyIntentAllowed",
                "containsSecrets", "executionEffect", "actionAllowed"}
    if not isinstance(value, Mapping) or set(value) != required \
            or value.get("schemaVersion") != RECEIPT_SCHEMA \
            or value.get("moneyIntentAllowed") is not False \
            or value.get("containsSecrets") is not False \
            or value.get("executionEffect") != "NONE" \
            or value.get("actionAllowed") is not False:
        raise ValueError("acknowledgement receipt schema is invalid")
    rebuilt = acknowledge_action_preview(
        preview=preview, challenge=challenge, interaction_id=value["interactionId"],
        acknowledged=value["acknowledged"],
        acknowledged_at_epoch_ms=value["acknowledgedAtEpochMs"])
    if rebuilt != dict(value):
        raise ValueError("acknowledgement receipt does not match challenge")
    return rebuilt
