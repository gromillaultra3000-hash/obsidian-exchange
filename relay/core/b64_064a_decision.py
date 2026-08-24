"""Pure two-person signature protocol for bounded 064A evidence acceptance."""
from __future__ import annotations

import base64
import hashlib
import json
from typing import Any, Callable, Mapping

ROUTE = "E0/E0.3/B5.3/064A"
LEGACY_STATEMENT_SCHEMA = "b64-064a-decision-statement.v1"
STATEMENT_SCHEMA = "b64-064a-decision-statement.v2"
REVIEW_SCHEMA = "b64-064a-independent-review.v1"
OWNER_SCHEMA = "b64-064a-owner-countersignature.v1"
MAX_LIFETIME_SECONDS = 24 * 60 * 60
MAX_FUTURE_SKEW_SECONDS = 60
DOMAINS = {
    "INDEPENDENT_REVIEWER": b"OBSIDIAN\0B64_064A_REVIEW\0V1\0",
    "ACCOUNTABLE_OWNER": b"OBSIDIAN\0B64_064A_OWNER\0V1\0",
}


def _canonical(value: Any) -> bytes:
    def check(item: Any) -> None:
        if item is None or type(item) in (str, int, bool):
            return
        if isinstance(item, list):
            for child in item:
                check(child)
            return
        if isinstance(item, dict) and all(isinstance(k, str) for k in item):
            for child in item.values():
                check(child)
            return
        raise ValueError("noncanonical_value")
    check(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _digest(value: Any, name: str) -> str:
    if (not isinstance(value, str) or len(value) != 64
            or any(c not in "0123456789abcdef" for c in value)):
        raise ValueError(f"invalid_{name}")
    return value


def _token(value: Any, name: str, maximum: int = 128) -> str:
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
    if (not isinstance(value, str) or not 1 <= len(value) <= maximum
            or any(c not in allowed for c in value)):
        raise ValueError(f"invalid_{name}")
    return value


def _nonce(value: Any) -> str:
    token = _token(value, "nonce", 96)
    try:
        raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
    except Exception as exc:
        raise ValueError("invalid_nonce") from exc
    if len(raw) < 16 or base64.urlsafe_b64encode(raw).rstrip(b"=").decode() != token:
        raise ValueError("invalid_nonce")
    return token


def _signature(raw: bytes) -> str:
    if not isinstance(raw, bytes) or len(raw) != 64:
        raise ValueError("invalid_signature")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _decode_signature(value: Any) -> bytes:
    token = _token(value, "signature", 96)
    try:
        raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
    except Exception as exc:
        raise ValueError("invalid_signature") from exc
    if len(raw) != 64 or _signature(raw) != token:
        raise ValueError("invalid_signature")
    return raw


def build_statement(*, decision_input_sha256: str, evidence_bundle_sha256: str,
                    issued_at_epoch: int, expires_at_epoch: int,
                    nonce: str, source_observed_at_epoch: int | None = None,
                    source_expires_at_epoch: int | None = None) -> dict[str, Any]:
    if (type(issued_at_epoch) is not int or type(expires_at_epoch) is not int
            or issued_at_epoch <= 0
            or not issued_at_epoch < expires_at_epoch <= issued_at_epoch + MAX_LIFETIME_SECONDS):
        raise ValueError("invalid_lifetime")
    if ((source_observed_at_epoch is None) != (source_expires_at_epoch is None)):
        raise ValueError("incomplete_source_window")
    source_bound = source_observed_at_epoch is not None
    if source_bound and (type(source_observed_at_epoch) is not int
            or type(source_expires_at_epoch) is not int
            or source_observed_at_epoch <= 0
            or source_expires_at_epoch != source_observed_at_epoch + MAX_LIFETIME_SECONDS
            or not source_observed_at_epoch <= issued_at_epoch
            or expires_at_epoch > source_expires_at_epoch):
        raise ValueError("invalid_source_window")
    unsigned = {
        "schemaVersion": STATEMENT_SCHEMA if source_bound else LEGACY_STATEMENT_SCHEMA,
        "project": "obsidian-exchange", "route": ROUTE,
        "phase": "CATALOG_SECURITY_RESTORE_EVIDENCE",
        "environment": "PRODUCTION_SOURCE_READ_ONLY_TO_DISPOSABLE_PG17",
        "decision": "ACCEPT_BOUNDED_EVIDENCE",
        "claim": "DECLARED_V2_PROJECTION_ONLY",
        "decisionInputSha256": _digest(decision_input_sha256, "decision_input_digest"),
        "evidenceBundleSha256": _digest(evidence_bundle_sha256, "bundle_digest"),
        "issuedAtEpoch": issued_at_epoch, "expiresAtEpoch": expires_at_epoch,
        "nonce": _nonce(nonce),
        "boundedEvidenceAcceptanceRequested": True,
        "packagePreparationOnly": True,
        "productionMutationAuthorized": False, "productionExpandAuthorized": False,
        "cutoverAuthorized": False, "telegramDeliveryAuthorized": False,
        "ambiguousSendingDispositionAuthorized": False, "actionAllowed": False,
    }
    if source_bound:
        unsigned["sourceObservedAtEpoch"] = source_observed_at_epoch
        unsigned["sourceExpiresAtEpoch"] = source_expires_at_epoch
    return {**unsigned, "statementSha256": _sha(unsigned)}


def _validate_statement(value: Mapping[str, Any], *, now_epoch: int,
                        current_input_sha256: str,
                        expected_source_observed_at_epoch: int | None = None,
                        expected_source_expires_at_epoch: int | None = None) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("invalid_statement")
    schema = value.get("schemaVersion")
    if schema not in {LEGACY_STATEMENT_SCHEMA, STATEMENT_SCHEMA}:
        raise ValueError("invalid_statement_schema")
    if schema == STATEMENT_SCHEMA and (expected_source_observed_at_epoch is None
            or expected_source_expires_at_epoch is None):
        raise ValueError("source_window_context_missing")
    if schema == LEGACY_STATEMENT_SCHEMA and (expected_source_observed_at_epoch is not None
            or expected_source_expires_at_epoch is not None):
        raise ValueError("legacy_statement_not_source_bound")
    rebuilt = build_statement(
        decision_input_sha256=value.get("decisionInputSha256"),
        evidence_bundle_sha256=value.get("evidenceBundleSha256"),
        issued_at_epoch=value.get("issuedAtEpoch"), expires_at_epoch=value.get("expiresAtEpoch"),
        nonce=value.get("nonce"),
        source_observed_at_epoch=value.get("sourceObservedAtEpoch") if schema == STATEMENT_SCHEMA else None,
        source_expires_at_epoch=value.get("sourceExpiresAtEpoch") if schema == STATEMENT_SCHEMA else None)
    if dict(value) != rebuilt or current_input_sha256 != rebuilt["decisionInputSha256"]:
        raise ValueError("statement_binding_mismatch")
    if schema == STATEMENT_SCHEMA and (
            rebuilt["sourceObservedAtEpoch"] != expected_source_observed_at_epoch
            or rebuilt["sourceExpiresAtEpoch"] != expected_source_expires_at_epoch):
        raise ValueError("statement_source_window_mismatch")
    if not rebuilt["issuedAtEpoch"] <= now_epoch + MAX_FUTURE_SKEW_SECONDS:
        raise ValueError("statement_from_future")
    if now_epoch >= rebuilt["expiresAtEpoch"]:
        raise ValueError("statement_expired")
    return rebuilt


def _build_envelope(*, schema: str, role: str, statement_sha256: str,
                    review_envelope_sha256: str | None, key_id: str,
                    identity_id: str, trust_domain: str, keyring_sha256: str,
                    issued_at_epoch: int, expires_at_epoch: int, nonce: str,
                    sign: Callable[[str, bytes], bytes]) -> dict[str, Any]:
    unsigned = {
        "schemaVersion": schema, "route": ROUTE, "role": role,
        "statementSha256": _digest(statement_sha256, "statement_digest"),
        "reviewEnvelopeSha256": review_envelope_sha256,
        "keyId": _token(key_id, "key_id"), "identityId": _token(identity_id, "identity_id"),
        "trustDomain": _token(trust_domain, "trust_domain"),
        "keyringSha256": _digest(keyring_sha256, "keyring_digest"),
        "issuedAtEpoch": issued_at_epoch, "expiresAtEpoch": expires_at_epoch,
        "nonce": _nonce(nonce), "decision": "ACCEPT_BOUNDED_EVIDENCE",
    }
    payload = DOMAINS[role] + _canonical(unsigned)
    return {**unsigned, "signature": _signature(sign(key_id, payload))}


def build_reviewer_envelope(**kwargs: Any) -> dict[str, Any]:
    return _build_envelope(schema=REVIEW_SCHEMA, role="INDEPENDENT_REVIEWER",
                           review_envelope_sha256=None, **kwargs)


def build_owner_envelope(*, review_envelope: Mapping[str, Any], **kwargs: Any) -> dict[str, Any]:
    return _build_envelope(schema=OWNER_SCHEMA, role="ACCOUNTABLE_OWNER",
                           review_envelope_sha256=_sha(dict(review_envelope)), **kwargs)


def verify_decision(*, statement: Mapping[str, Any], reviewer: Mapping[str, Any],
                    owner: Mapping[str, Any], registry: Mapping[str, Mapping[str, Any]],
                    expected_keyring_sha256: str, current_input_sha256: str,
                    now_epoch: int, verify_signature: Callable[[str, bytes, bytes], None],
                    consume_pair: Callable[[tuple[str, str], tuple[str, str], str], bool],
                    trust_environment: str,
                    expected_source_observed_at_epoch: int | None = None,
                    expected_source_expires_at_epoch: int | None = None) -> dict[str, Any]:
    safe = {"status": "INVALID", "route": ROUTE, "syntheticProtocolValid": False,
            "authenticatedOwnerReviewerGo": False, "boundedEvidenceAccepted": False,
            "packagePreparationEligible": False, "productionExpandAuthorized": False,
            "cutoverAuthorized": False, "actionAllowed": False, "reasonCodes": ["INVALID"]}
    try:
        frozen = _validate_statement(statement, now_epoch=now_epoch,
                                     current_input_sha256=current_input_sha256,
                                     expected_source_observed_at_epoch=expected_source_observed_at_epoch,
                                     expected_source_expires_at_epoch=expected_source_expires_at_epoch)
        if (trust_environment == "PRODUCTION_AUTHENTICATED"
                and frozen["schemaVersion"] != STATEMENT_SCHEMA):
            raise ValueError("legacy_statement_not_production_eligible")
        envelopes = ((dict(reviewer), REVIEW_SCHEMA, "INDEPENDENT_REVIEWER"),
                     (dict(owner), OWNER_SCHEMA, "ACCOUNTABLE_OWNER"))
        verified = []
        for envelope, schema, role in envelopes:
            signature = envelope.pop("signature", None)
            if (set(envelope) != {"schemaVersion", "route", "role", "statementSha256",
                    "reviewEnvelopeSha256", "keyId", "identityId", "trustDomain",
                    "keyringSha256", "issuedAtEpoch", "expiresAtEpoch", "nonce", "decision"}
                    or envelope["schemaVersion"] != schema or envelope["route"] != ROUTE
                    or envelope["role"] != role or envelope["decision"] != "ACCEPT_BOUNDED_EVIDENCE"
                    or envelope["statementSha256"] != frozen["statementSha256"]
                    or envelope["keyringSha256"] != expected_keyring_sha256
                    or not envelope["issuedAtEpoch"] <= now_epoch < envelope["expiresAtEpoch"]
                    or envelope["issuedAtEpoch"] < frozen["issuedAtEpoch"]
                    or envelope["expiresAtEpoch"] > frozen["expiresAtEpoch"]
                    or envelope["expiresAtEpoch"] > envelope["issuedAtEpoch"] + MAX_LIFETIME_SECONDS):
                raise ValueError("invalid_envelope")
            key = registry.get(envelope["keyId"])
            if (not key or key.get("status") != "ACTIVE" or key.get("role") != role
                    or key.get("identityId") != envelope["identityId"]
                    or key.get("trustDomain") != envelope["trustDomain"]
                    or key.get("trustEnvironment") != trust_environment):
                raise ValueError("untrusted_signer")
            verify_signature(envelope["keyId"], _decode_signature(signature),
                             DOMAINS[role] + _canonical(envelope))
            verified.append((envelope, signature))
        review_unsigned, review_sig = verified[0]
        owner_unsigned, owner_sig = verified[1]
        full_review = {**review_unsigned, "signature": review_sig}
        if owner_unsigned["reviewEnvelopeSha256"] != _sha(full_review):
            raise ValueError("owner_review_binding_mismatch")
        if review_unsigned["reviewEnvelopeSha256"] is not None:
            raise ValueError("invalid_review_binding")
        if (review_unsigned["keyId"] == owner_unsigned["keyId"]
                or review_unsigned["identityId"] == owner_unsigned["identityId"]
                or review_unsigned["trustDomain"] == owner_unsigned["trustDomain"]):
            raise ValueError("four_eyes_not_independent")
        decision_id = hashlib.sha256((frozen["statementSha256"] +
            _sha(full_review) + _sha(dict(owner))).encode()).hexdigest()
        if not consume_pair((review_unsigned["keyId"], review_unsigned["nonce"]),
                            (owner_unsigned["keyId"], owner_unsigned["nonce"]), decision_id):
            raise ValueError("replay_or_ledger_unavailable")
        production = trust_environment == "PRODUCTION_AUTHENTICATED"
        return {**safe, "status": "ACCEPTED" if production else "SYNTHETIC_VALID",
                "syntheticProtocolValid": True,
                "authenticatedOwnerReviewerGo": production,
                "boundedEvidenceAccepted": production,
                "packagePreparationEligible": production,
                "reasonCodes": [] if production else ["SYNTHETIC_KEYS_ONLY"]}
    except Exception:
        return safe
