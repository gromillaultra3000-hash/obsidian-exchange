"""Disabled Relay producer for privacy-minimized E2 shadow submissions."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from datetime import datetime, timezone
from typing import Any

from relay.core.kairos_service_identity import signed_request

_FACT_KEY = re.compile(r"^[a-z][a-z0-9_]{1,47}$")
_FORBIDDEN = (
    "owner", "account", "credential", "secret", "api_key", "address",
    "wallet", "balance", "amount", "email", "phone", "document", "kyc",
)
_VERDICTS = {"ALLOW": 0, "HOLD": 1, "MANUAL": 2, "FREEZE": 3}


class ShadowProducerDisabled(RuntimeError):
    pass


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(timezone.utc)


def build_submission(
    *, observed_at: datetime, subject_kind: str, signal_type: str,
    source_class: str, freshness: str, facts: dict[str, Any],
    hard_verdict: str, advisory_verdict: str, decided_at: datetime,
) -> dict[str, Any]:
    if subject_kind not in {"MARKET_WINDOW", "CONNECTOR_HEALTH", "PERMISSION_POSTURE"}:
        raise ValueError("subject kind is invalid")
    if source_class not in {"DETERMINISTIC", "PROVIDER", "ADVISORY"} \
            or freshness not in {"FRESH", "STALE", "UNKNOWN"}:
        raise ValueError("evidence classification is invalid")
    if not re.fullmatch(r"[A-Z][A-Z0-9_]{2,63}", signal_type) or not 1 <= len(facts) <= 32:
        raise ValueError("shadow signal is invalid")
    for key, value in facts.items():
        if not _FACT_KEY.fullmatch(key) or any(part in key for part in _FORBIDDEN):
            raise ValueError("shadow fact is not privacy-minimized")
        if not (value is None or isinstance(value, (bool, int, float, str))) \
                or isinstance(value, str) and len(value) > 128 \
                or isinstance(value, float) and not math.isfinite(value):
            raise ValueError("shadow fact value is invalid")
    if hard_verdict not in _VERDICTS or advisory_verdict not in _VERDICTS:
        raise ValueError("shadow verdict is invalid")
    observed = _utc(observed_at)
    decided = _utc(decided_at)
    if decided < observed:
        raise ValueError("decision predates evidence")
    evidence_public = {
        "schemaVersion": "evidence-record.v1", "observedAt": observed.isoformat(),
        "subjectKind": subject_kind, "signalType": signal_type,
        "sourceClass": source_class, "freshness": freshness, "facts": facts,
    }
    evidence_id = "ev_" + hashlib.sha256(json.dumps(
        evidence_public, sort_keys=True, separators=(",", ":"),
        ensure_ascii=True).encode()).hexdigest()
    evidence = {**evidence_public, "evidenceId": evidence_id}
    combined = max((hard_verdict, advisory_verdict), key=_VERDICTS.get)
    reasons = ["HARD_GATE_APPLIED"]
    if _VERDICTS[combined] > _VERDICTS[hard_verdict]:
        reasons.append("ADVISORY_TIGHTENED")
    decision = {
        "schemaVersion": "decision-envelope.v1",
        "policyVersion": "e2-monotonic-hard-gate.v1",
        "hardVerdict": hard_verdict, "advisoryVerdict": advisory_verdict,
        "combinedVerdict": combined, "actionAllowed": combined == "ALLOW",
        "evidenceRefs": [evidence_id], "reasonCodes": reasons,
        "decidedAt": decided.isoformat(),
    }
    return {"schemaVersion": "shadow-submission.v1",
            "evidence": [evidence], "decision": decision}


def submit(submission: dict[str, Any], *, principal: str) -> dict[str, Any]:
    if os.getenv("RELAY_E2_SHADOW_PRODUCER_ENABLED", "0") != "1":
        raise ShadowProducerDisabled("Relay E2 shadow producer is disabled")
    result = signed_request(
        "POST", "/internal/v1/shadow-decisions", principal=principal,
        scope="shadow:write", payload=submission, timeout=3.0)
    if set(result) != {
        "schemaVersion", "recordId", "sequence", "recordHash",
        "combinedVerdict", "actionAllowed",
    } or result.get("schemaVersion") != "shadow-submission-result.v1" \
            or result.get("actionAllowed") is not False:
        raise RuntimeError("invalid shadow ingress response")
    return result
