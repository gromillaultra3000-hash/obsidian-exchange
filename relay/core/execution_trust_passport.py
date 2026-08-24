"""Pure, non-authoritative verification for synthetic Execution Trust Passports."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any


SCHEMA = "obsidian-execution-trust-passport.v1"
DECISIONS = {"ALLOW": 0, "HOLD": 1, "MANUAL": 2, "FREEZE": 3}
LANES = {"PRIVATE_EXCHANGE", "VERIFIED_CEX", "SELF_CUSTODY"}
OUTCOMES = {"NOT_SUBMITTED", "SUBMITTED", "CONFIRMED", "REJECTED", "UNKNOWN_REVIEW"}
FINAL_STATES = {"NOT_FINAL", "RECONCILED", "REJECTED", "REVIEW"}

TOP_LEVEL = {
    "schema",
    "passport_id",
    "action_intent",
    "service_lane",
    "identity_custody",
    "quote_or_preview",
    "user_consent",
    "policy_decision",
    "execution_attempt",
    "settlement_or_reconciliation",
    "evidence_chain",
}

SECTION_KEYS = {
    "passport_id": {"action_type", "intent_id", "intent_sha256", "created_at_epoch_ms"},
    "action_intent": {"immutable_parameters_sha256", "idempotency_key_sha256", "actor_subject_sha256"},
    "identity_custody": {"identity_authority", "custody_owner", "executor", "permission_snapshot_sha256"},
    "quote_or_preview": {"market_or_transaction_snapshot_sha256", "fees_sha256", "expires_at_epoch_ms"},
    "user_consent": {"display_sha256", "consent_sha256", "consented_parameters_sha256", "consented_at_epoch_ms"},
    "policy_decision": {"hard_policy_sha256", "hard_decision", "advisory_evidence_sha256", "advisory_decision", "effective_decision", "decision_reason_code"},
    "execution_attempt": {"attempt_id", "attempt_parameters_sha256", "submitted_at_epoch_ms", "provider_evidence_sha256", "outcome"},
    "settlement_or_reconciliation": {"observed_evidence_sha256", "reconciliation_policy_sha256", "final_state", "finalized_at_epoch_ms"},
    "evidence_chain": {"previous_passport_event_sha256", "passport_head_sha256", "independent_checkpoint_sha256"},
}


@dataclass(frozen=True)
class PassportVerification:
    valid: bool
    code: str
    action_authority: str = "NONE"


def _is_digest(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _is_nonempty_text(value: Any, maximum: int = 128) -> bool:
    return isinstance(value, str) and 0 < len(value.encode("utf-8")) <= maximum


def _is_time(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def passport_head(passport: dict[str, Any]) -> str:
    body = {key: passport[key] for key in TOP_LEVEL - {"evidence_chain"}}
    chain = passport["evidence_chain"]
    preimage = b"obsidian.execution-trust-passport.v1\x00"
    preimage += bytes.fromhex(chain["previous_passport_event_sha256"])
    preimage += _canonical_bytes(body)
    return hashlib.sha256(preimage).hexdigest()


def verify_passport(passport: Any) -> PassportVerification:
    if not isinstance(passport, dict) or set(passport) != TOP_LEVEL or passport.get("schema") != SCHEMA:
        return PassportVerification(False, "CLOSED_SCHEMA")
    if passport.get("service_lane") not in LANES:
        return PassportVerification(False, "SERVICE_LANE")

    for section, keys in SECTION_KEYS.items():
        value = passport.get(section)
        if not isinstance(value, dict) or set(value) != keys:
            return PassportVerification(False, f"SECTION_{section.upper()}")

    digest_fields = {
        "passport_id": {"intent_sha256"},
        "action_intent": set(SECTION_KEYS["action_intent"]),
        "identity_custody": {"permission_snapshot_sha256"},
        "quote_or_preview": {"market_or_transaction_snapshot_sha256", "fees_sha256"},
        "user_consent": {"display_sha256", "consent_sha256", "consented_parameters_sha256"},
        "policy_decision": {"hard_policy_sha256", "advisory_evidence_sha256"},
        "execution_attempt": {"attempt_parameters_sha256", "provider_evidence_sha256"},
        "settlement_or_reconciliation": {"observed_evidence_sha256", "reconciliation_policy_sha256"},
        "evidence_chain": set(SECTION_KEYS["evidence_chain"]),
    }
    for section, fields in digest_fields.items():
        if any(not _is_digest(passport[section][field]) for field in fields):
            return PassportVerification(False, "DIGEST")

    identity = passport["identity_custody"]
    if any(not _is_nonempty_text(identity[field]) for field in ["identity_authority", "custody_owner", "executor"]):
        return PassportVerification(False, "IDENTITY_CUSTODY")

    passport_id = passport["passport_id"]
    attempt = passport["execution_attempt"]
    policy = passport["policy_decision"]
    settlement = passport["settlement_or_reconciliation"]
    if not all(_is_nonempty_text(value) for value in [passport_id["action_type"], passport_id["intent_id"], attempt["attempt_id"], policy["decision_reason_code"]]):
        return PassportVerification(False, "IDENTIFIER")
    if attempt["outcome"] not in OUTCOMES or settlement["final_state"] not in FINAL_STATES:
        return PassportVerification(False, "STATE_ENUM")
    if any(policy[field] not in DECISIONS for field in ["hard_decision", "advisory_decision", "effective_decision"]):
        return PassportVerification(False, "DECISION_ENUM")
    expected_decision = max([policy["hard_decision"], policy["advisory_decision"]], key=DECISIONS.__getitem__)
    if policy["effective_decision"] != expected_decision:
        return PassportVerification(False, "POLICY_WEAKENED")

    immutable = passport["action_intent"]["immutable_parameters_sha256"]
    if passport["user_consent"]["consented_parameters_sha256"] != immutable or attempt["attempt_parameters_sha256"] != immutable:
        return PassportVerification(False, "PARAMETER_DRIFT")

    created = passport_id["created_at_epoch_ms"]
    expires = passport["quote_or_preview"]["expires_at_epoch_ms"]
    consented = passport["user_consent"]["consented_at_epoch_ms"]
    submitted = attempt["submitted_at_epoch_ms"]
    finalized = settlement["finalized_at_epoch_ms"]
    if not all(_is_time(value) for value in [created, expires, consented, submitted, finalized]):
        return PassportVerification(False, "TIME_TYPE")
    if not created <= consented <= expires or submitted < consented or finalized < submitted:
        return PassportVerification(False, "TIME_ORDER")

    if attempt["outcome"] == "CONFIRMED" and settlement["final_state"] not in {"RECONCILED", "REVIEW"}:
        return PassportVerification(False, "FINAL_STATE")
    if policy["effective_decision"] != "ALLOW" and attempt["outcome"] not in {"NOT_SUBMITTED", "REJECTED"}:
        return PassportVerification(False, "POLICY_EXECUTION_CONFLICT")
    if attempt["outcome"] == "UNKNOWN_REVIEW" and settlement["final_state"] != "REVIEW":
        return PassportVerification(False, "UNCERTAIN_NOT_REVIEW")
    if attempt["outcome"] == "REJECTED" and settlement["final_state"] != "REJECTED":
        return PassportVerification(False, "REJECTION_DRIFT")
    if attempt["outcome"] == "NOT_SUBMITTED" and settlement["final_state"] != "NOT_FINAL":
        return PassportVerification(False, "NOT_SUBMITTED_FINALIZED")

    if passport_head(passport) != passport["evidence_chain"]["passport_head_sha256"]:
        return PassportVerification(False, "HASH_CHAIN")
    return PassportVerification(True, "VERIFIED_NON_AUTHORITATIVE")
