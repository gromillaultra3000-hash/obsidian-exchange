"""Pure E5 local-authenticator evidence contract; never signs anything."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable, Mapping

from core.e5_key_boundary import validate_key_boundary
from core.e5_signing_consent import (
    validate_signing_consent_receipt,
    validate_signing_display_request,
)

SCHEMA = "native-authenticator-evidence.v1"
MAX_ASSERTION_AGE_MS = 30_000
MAX_FUTURE_SKEW_MS = 1_000


def _hash(value: Mapping[str, Any]) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def _digest(value: Any, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64 \
            or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{field} must be a lowercase SHA-256 digest")
    return value


def _counter(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return value


def build_authenticator_evidence(
        *, request: Mapping[str, Any], consent: Mapping[str, Any],
        boundary: Mapping[str, Any], first_interaction_id: str,
        confirm_interaction_id: str, device_key_identity_sha256: str,
        challenge_sha256: str, assertion_sha256: str, assertion_counter: int,
        previous_assertion_counter: int, asserted_at_epoch_ms: int,
        observed_at_epoch_ms: int,
        consumed_assertion_ids: Iterable[str] = ()) -> dict[str, Any]:
    key_boundary = validate_key_boundary(boundary)
    signing_request = validate_signing_display_request(request, boundary=key_boundary)
    receipt = validate_signing_consent_receipt(
        consent, request=signing_request, boundary=key_boundary,
        first_interaction_id=first_interaction_id,
        confirm_interaction_id=confirm_interaction_id)
    device_key = _digest(device_key_identity_sha256, "deviceKeyIdentitySha256")
    challenge = _digest(challenge_sha256, "challengeSha256")
    assertion = _digest(assertion_sha256, "assertionSha256")
    current_counter = _counter(assertion_counter, "assertionCounter")
    previous_counter = _counter(
        previous_assertion_counter, "previousAssertionCounter")
    asserted_at = _counter(asserted_at_epoch_ms, "assertedAtEpochMs")
    observed_at = _counter(observed_at_epoch_ms, "observedAtEpochMs")
    if current_counter <= previous_counter:
        raise ValueError("authenticator counter did not advance")
    if asserted_at < receipt["confirmedAtEpochMs"] \
            or asserted_at > signing_request["expiresAtEpochMs"]:
        raise ValueError("assertion is outside the consent window")
    if observed_at + MAX_FUTURE_SKEW_MS < asserted_at \
            or observed_at - asserted_at > MAX_ASSERTION_AGE_MS:
        raise ValueError("assertion freshness is invalid")
    unsigned = {
        "schemaVersion": SCHEMA,
        "boundaryId": key_boundary["boundaryId"],
        "requestId": signing_request["requestId"],
        "consentReceiptId": receipt["receiptId"],
        "unsignedPayloadSha256": signing_request["unsignedPayloadSha256"],
        "displayBindingSha256": signing_request["displayBindingSha256"],
        "deviceKeyIdentitySha256": device_key,
        "challengeSha256": challenge,
        "assertionSha256": assertion,
        "assertionCounter": current_counter,
        "previousAssertionCounter": previous_counter,
        "assertedAtEpochMs": asserted_at,
        "observedAtEpochMs": observed_at,
        "hardwareBackedClaim": True,
        "userVerificationClaim": True,
        "status": "AUTHENTICATOR_EVIDENCE_VALIDATED_OFFLINE",
        "platformAttestationVerified": False,
        "localAuthenticatorVerified": False,
        "containsKeyMaterial": False,
        "containsBiometricData": False,
        "signaturePresent": False,
        "signingAllowed": False,
        "productionNetworkAllowed": False,
        "executionEffect": "NONE",
        "actionAllowed": False,
    }
    evidence = {**unsigned, "evidenceId": "nae_" + _hash(unsigned)}
    consumed = set(consumed_assertion_ids)
    if any(not isinstance(item, str) for item in consumed) \
            or evidence["evidenceId"] in consumed:
        raise ValueError("authenticator assertion replay detected")
    return evidence


def validate_authenticator_evidence(
        value: Mapping[str, Any], **context: Any) -> dict[str, Any]:
    required = {
        "schemaVersion", "evidenceId", "boundaryId", "requestId",
        "consentReceiptId", "unsignedPayloadSha256", "displayBindingSha256",
        "deviceKeyIdentitySha256", "challengeSha256", "assertionSha256",
        "assertionCounter", "previousAssertionCounter", "assertedAtEpochMs",
        "observedAtEpochMs", "hardwareBackedClaim", "userVerificationClaim",
        "status", "platformAttestationVerified", "localAuthenticatorVerified",
        "containsKeyMaterial", "containsBiometricData", "signaturePresent",
        "signingAllowed", "productionNetworkAllowed", "executionEffect",
        "actionAllowed",
    }
    if not isinstance(value, Mapping) or set(value) != required \
            or value.get("schemaVersion") != SCHEMA:
        raise ValueError("authenticator evidence schema is invalid")
    rebuilt = build_authenticator_evidence(
        device_key_identity_sha256=value.get("deviceKeyIdentitySha256"),
        challenge_sha256=value.get("challengeSha256"),
        assertion_sha256=value.get("assertionSha256"),
        assertion_counter=value.get("assertionCounter"),
        previous_assertion_counter=value.get("previousAssertionCounter"),
        asserted_at_epoch_ms=value.get("assertedAtEpochMs"),
        observed_at_epoch_ms=value.get("observedAtEpochMs"), **context)
    if rebuilt != dict(value):
        raise ValueError("authenticator evidence does not match canonical content")
    return rebuilt
