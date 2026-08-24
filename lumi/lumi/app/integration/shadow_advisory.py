"""Pure deterministic validator/adapter for the frozen KAIROS shadow wire."""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, timezone
from typing import Any

REQUEST_SCHEMA = "shadow-advisory-request.v1"
RESPONSE_SCHEMA = "shadow-advisory-response.v1"
POLICY_VERSION = "e2-monotonic-hard-gate.v1"
MODEL_VERSION = "lumi-shadow-rules-v1"
VERDICTS = ("ALLOW", "HOLD", "MANUAL", "FREEZE")
_FORBIDDEN = (
    "owner", "account", "credential", "secret", "api_key", "address",
    "wallet", "balance", "amount", "email", "phone", "document", "kyc",
)
_REQUEST_KEYS = {
    "schemaVersion", "requestId", "policyVersion", "requestedAt",
    "hardVerdict", "evidence",
}
_EVIDENCE_KEYS = {
    "schemaVersion", "evidenceId", "observedAt", "subjectKind", "signalType",
    "sourceClass", "freshness", "facts",
}
_CATALOG_FACTS = {
    "PERMISSION_DRIFT": {"permission_valid": ("BOOL",), "withdrawal_enabled": ("BOOL",)},
    "CONNECTOR_DEGRADED": {"failure_count": ("INT_0_1000",), "reachable": ("BOOL",)},
    "PROVIDER_RATE_LIMIT": {"rate_limited": ("BOOL",),
                            "retry_bucket": ("LT_1M", "M1_5", "OVER_5M")},
    "MARKET_DATA_STALE": {"age_bucket": ("S60_299", "S300_899", "S900_PLUS"),
                          "source_count": ("INT_0_1000",)},
    "ADVISORY_UNAVAILABLE": {"failure_class": ("TIMEOUT", "ERROR", "MALFORMED", "UNKNOWN"),
                             "latency_bucket": ("LT_250MS", "MS250_999", "S1_3", "OVER_3S", "TIMEOUT")},
}


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True).encode()


def _time(value: Any, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} is invalid") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{label} is invalid")
    return parsed.astimezone(timezone.utc)


def _validate_evidence(value: Any, requested: datetime) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != _EVIDENCE_KEYS \
            or value.get("schemaVersion") != "evidence-record.v1":
        raise ValueError("advisory evidence fields differ")
    if value.get("subjectKind") not in {
        "MARKET_WINDOW", "CONNECTOR_HEALTH", "PERMISSION_POSTURE",
    } or value.get("sourceClass") not in {"DETERMINISTIC", "PROVIDER", "ADVISORY"} \
            or value.get("freshness") not in {"FRESH", "STALE", "UNKNOWN"} \
            or not re.fullmatch(r"[A-Z][A-Z0-9_]{2,63}", str(value.get("signalType"))):
        raise ValueError("advisory evidence classification is invalid")
    observed = _time(value.get("observedAt"), "observedAt")
    if observed > requested:
        raise ValueError("advisory request predates evidence")
    facts = value.get("facts")
    if not isinstance(facts, dict) or len(facts) > 32:
        raise ValueError("advisory facts are invalid")
    for key, item in facts.items():
        if not re.fullmatch(r"[a-z][a-z0-9_]{1,47}", key) \
                or any(part in key for part in _FORBIDDEN) \
                or not (item is None or isinstance(item, (bool, int, float, str))) \
                or isinstance(item, str) and len(item) > 128 \
                or isinstance(item, float) and not math.isfinite(item):
            raise ValueError("advisory facts are not privacy-minimized")
    rules = _CATALOG_FACTS.get(value["signalType"])
    if rules is None or set(facts) != set(rules):
        raise ValueError("advisory signal facts differ from frozen catalog")
    for key, item in facts.items():
        allowed = rules[key]
        valid = (allowed == ("BOOL",) and isinstance(item, bool)) \
            or (allowed == ("INT_0_1000",) and isinstance(item, int)
                and not isinstance(item, bool) and 0 <= item <= 1000) \
            or item in allowed
        if not valid:
            raise ValueError("advisory fact value is outside frozen buckets")
    evidence_unsigned = {
        "schemaVersion": "evidence-record.v1",
        "observedAt": observed.isoformat(), "subjectKind": value["subjectKind"],
        "signalType": value["signalType"], "sourceClass": value["sourceClass"],
        "freshness": value["freshness"], "facts": facts,
    }
    expected = "ev_" + hashlib.sha256(_canonical(evidence_unsigned)).hexdigest()
    if value.get("evidenceId") != expected:
        raise ValueError("advisory evidence hash mismatch")
    return value


def validate_request(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != _REQUEST_KEYS \
            or value.get("schemaVersion") != REQUEST_SCHEMA \
            or value.get("policyVersion") != POLICY_VERSION \
            or value.get("hardVerdict") not in VERDICTS:
        raise ValueError("advisory request fields differ")
    requested = _time(value.get("requestedAt"), "requestedAt")
    evidence = value.get("evidence")
    if not isinstance(evidence, list) or not 1 <= len(evidence) <= 8:
        raise ValueError("advisory evidence count is invalid")
    validated = [_validate_evidence(item, requested) for item in evidence]
    ids = [item["evidenceId"] for item in validated]
    if len(set(ids)) != len(ids):
        raise ValueError("advisory evidence is duplicated")
    unsigned = {key: item for key, item in value.items() if key != "requestId"}
    expected = "ar_" + hashlib.sha256(_canonical(unsigned)).hexdigest()
    if value.get("requestId") != expected:
        raise ValueError("advisory request id mismatch")
    return value


def _rule_verdict(request: dict[str, Any]) -> tuple[str, list[str]]:
    level = "ALLOW"
    reasons = ["DETERMINISTIC_RULES_APPLIED"]
    for evidence in request["evidence"]:
        facts = evidence["facts"]
        signal = evidence["signalType"]
        if signal == "PERMISSION_DRIFT" and (
            facts.get("permission_valid") is False
            or facts.get("withdrawal_enabled") is True
        ):
            level = "FREEZE"
            reasons.append("PERMISSION_DRIFT_BLOCKED")
        elif signal == "CONNECTOR_DEGRADED" and facts.get("reachable") is False:
            candidate = "MANUAL" if int(facts.get("failure_count") or 0) >= 3 else "HOLD"
            level = max((level, candidate), key=VERDICTS.index)
            reasons.append("CONNECTOR_HEALTH_REVIEW")
        elif signal in {"PROVIDER_RATE_LIMIT", "MARKET_DATA_STALE", "ADVISORY_UNAVAILABLE"} \
                or evidence["freshness"] in {"STALE", "UNKNOWN"}:
            level = max((level, "HOLD"), key=VERDICTS.index)
            reasons.append("FRESHNESS_OR_PROVIDER_HOLD")
    hard = request["hardVerdict"]
    level = max((level, hard), key=VERDICTS.index)
    if level == hard:
        reasons.append("HARD_FLOOR_APPLIED")
    return level, list(dict.fromkeys(reasons))


def evaluate(request_value: Any, *, evaluated_at: datetime) -> dict[str, Any]:
    request = validate_request(request_value)
    evaluated = evaluated_at.astimezone(timezone.utc) if evaluated_at.tzinfo else None
    requested = _time(request["requestedAt"], "requestedAt")
    if evaluated is None or evaluated < requested:
        raise ValueError("advisory evaluation time is invalid")
    verdict, reasons = _rule_verdict(request)
    return {
        "schemaVersion": RESPONSE_SCHEMA, "requestId": request["requestId"],
        "advisoryVerdict": verdict, "reasonCodes": reasons[:8],
        "evaluatedAt": evaluated.isoformat().replace("+00:00", "Z"),
        "modelVersion": MODEL_VERSION,
    }
