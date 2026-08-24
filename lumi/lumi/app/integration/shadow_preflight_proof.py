"""Pure fail-closed preflight proof for the dormant shadow transport."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Callable

from lumi.app.integration.shadow_transport_readiness import CHECKS, READINESS_SCHEMA

SCHEMA = "shadow-preflight-proof.v1"
SELF_TEST_SCHEMA = "shadow-mutual-auth-transcript.v1"
_KEYS = {
    "schemaVersion", "proofId", "status", "eligible", "blockers",
    "readiness", "selfTest", "selfTestPassed", "executionEffect",
    "actionAllowed",
}


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def _validate_readiness(value: Any) -> dict[str, Any]:
    keys = {
        "schemaVersion", "status", "ready", "checks", "blockers",
        "executionEffect", "actionAllowed",
    }
    if not isinstance(value, dict) or set(value) != keys \
            or value.get("schemaVersion") != READINESS_SCHEMA \
            or value.get("status") not in {"GO", "NO_GO"} \
            or type(value.get("ready")) is not bool \
            or value.get("executionEffect") != "NONE" \
            or value.get("actionAllowed") is not False:
        raise ValueError("shadow preflight readiness differs")
    checks = value.get("checks")
    expected_ids = [check_id for check_id, _, _ in CHECKS]
    if not isinstance(checks, list) or len(checks) != len(CHECKS) \
            or any(not isinstance(item, dict) or set(item) != {"checkId", "ready"}
                   or type(item.get("ready")) is not bool
                   for item in checks) \
            or [item["checkId"] for item in checks] != expected_ids:
        raise ValueError("shadow preflight readiness checks differ")
    expected_blockers = [
        blocker for item, (_, _, blocker) in zip(checks, CHECKS)
        if not item["ready"]
    ]
    if value.get("blockers") != expected_blockers \
            or value["ready"] != (not expected_blockers) \
            or value["status"] != ("GO" if not expected_blockers else "NO_GO"):
        raise ValueError("shadow preflight readiness result is inconsistent")
    return value


def _proof_id(value: dict[str, Any]) -> str:
    unsigned = {key: item for key, item in value.items() if key != "proofId"}
    return "pf_" + hashlib.sha256(_canonical(unsigned)).hexdigest()


def build_preflight_proof(
    readiness: Any, self_test: Any, *,
    validate_self_test: Callable[[Any], dict[str, Any]],
) -> dict[str, Any]:
    ready = _validate_readiness(readiness)
    try:
        transcript = validate_self_test(self_test)
    except Exception as exc:
        raise ValueError("shadow preflight self-test failed") from exc
    if not isinstance(transcript, dict) \
            or transcript.get("schemaVersion") != SELF_TEST_SCHEMA \
            or not re.fullmatch(r"rt_[a-f0-9]{64}", str(transcript.get("transcriptId"))) \
            or transcript.get("executionEffect") != "NONE" \
            or transcript.get("actionAllowed") is not False:
        raise ValueError("shadow preflight self-test differs")
    eligible = ready["ready"]
    value = {
        "schemaVersion": SCHEMA,
        "status": "ELIGIBLE" if eligible else "INELIGIBLE",
        "eligible": eligible, "blockers": list(ready["blockers"]),
        "readiness": ready,
        "selfTest": {
            "schemaVersion": SELF_TEST_SCHEMA,
            "transcriptId": transcript["transcriptId"],
            "requestId": transcript["requestId"],
            "requestHash": transcript["requestHash"],
            "responseHash": transcript["responseHash"],
            "executionEffect": "NONE", "actionAllowed": False,
        },
        "selfTestPassed": True, "executionEffect": "NONE",
        "actionAllowed": False,
    }
    value["proofId"] = _proof_id(value)
    return validate_preflight_proof(value)


def validate_preflight_proof(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != _KEYS \
            or value.get("schemaVersion") != SCHEMA \
            or value.get("status") not in {"ELIGIBLE", "INELIGIBLE"} \
            or type(value.get("eligible")) is not bool \
            or value.get("selfTestPassed") is not True \
            or value.get("executionEffect") != "NONE" \
            or value.get("actionAllowed") is not False \
            or not re.fullmatch(r"pf_[a-f0-9]{64}", str(value.get("proofId"))):
        raise ValueError("shadow preflight proof fields differ")
    readiness = _validate_readiness(value.get("readiness"))
    summary = value.get("selfTest")
    summary_keys = {
        "schemaVersion", "transcriptId", "requestId", "requestHash",
        "responseHash", "executionEffect", "actionAllowed",
    }
    if not isinstance(summary, dict) or set(summary) != summary_keys \
            or summary.get("schemaVersion") != SELF_TEST_SCHEMA \
            or not re.fullmatch(r"rt_[a-f0-9]{64}", str(summary.get("transcriptId"))) \
            or not re.fullmatch(r"ar_[a-f0-9]{64}", str(summary.get("requestId"))) \
            or not re.fullmatch(r"[a-f0-9]{64}", str(summary.get("requestHash"))) \
            or not re.fullmatch(r"[a-f0-9]{64}", str(summary.get("responseHash"))) \
            or summary.get("executionEffect") != "NONE" \
            or summary.get("actionAllowed") is not False:
        raise ValueError("shadow preflight self-test summary differs")
    eligible = readiness["ready"]
    if value["eligible"] != eligible \
            or value["status"] != ("ELIGIBLE" if eligible else "INELIGIBLE") \
            or value.get("blockers") != readiness["blockers"]:
        raise ValueError("shadow preflight eligibility differs")
    if value["proofId"] != _proof_id(value):
        raise ValueError("shadow preflight proof hash differs")
    return value
