"""Pure cross-package E2 replay; validates and projects without I/O."""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from app.evidence_contracts import DecisionEnvelope, EvidenceRecord, HardVerdict, combine_decision
from app.shadow_advisory_wire import AdvisoryResponse, build_request, dispatch
from app.shadow_decision_journal import (
    GENESIS_HASH, ShadowJournalError, project_record, verify_record_projection,
)
from app.shadow_ingress import ShadowSubmission
from lumi.app.integration.shadow_advisory import evaluate
from relay.core.shadow_observations import PLAN_VERSION, plan_observation

REPLAY_SCHEMA = "shadow-offline-replay.v1"
BATCH_SCHEMA = "shadow-offline-batch.v1"
VERIFY_SCHEMA = "shadow-offline-batch-verification.v1"
_PLAN_KEYS = {
    "schemaVersion", "catalogVersion", "observationId", "triggerId",
    "bucketStart", "bucketSeconds", "submission",
}


def replay(
    plan_value: Any, *, requested_at: datetime, evaluated_at: datetime,
    decided_at: datetime, recorded_at: datetime, sequence: int = 1,
    previous_hash: str = GENESIS_HASH,
) -> dict[str, Any]:
    """Replay a frozen observation and return its exact genesis projection."""
    if not isinstance(plan_value, dict) or set(plan_value) != _PLAN_KEYS \
            or plan_value.get("schemaVersion") != PLAN_VERSION:
        raise ValueError("offline observation plan fields differ")
    submission = ShadowSubmission.model_validate_json(json.dumps(
        plan_value.get("submission"), sort_keys=True, separators=(",", ":")))
    if len(submission.evidence) != 1:
        raise ValueError("offline replay requires exactly one evidence record")
    evidence = submission.evidence[0]
    rebuilt = plan_observation(
        trigger_id=plan_value["triggerId"], observed_at=evidence.observedAt,
        facts=evidence.facts, hard_verdict=submission.decision.hardVerdict.value,
        advisory_verdict=submission.decision.advisoryVerdict.value,
        freshness=evidence.freshness,
    )
    if rebuilt != plan_value:
        raise ValueError("offline observation plan identity mismatch")

    request = build_request(
        requested_at=requested_at, hard_verdict=submission.decision.hardVerdict,
        evidence=[EvidenceRecord.model_validate(evidence)],
    )
    response: dict[str, Any] | None = None

    def local_transport(payload: dict[str, Any], timeout: float) -> dict[str, Any]:
        nonlocal response
        if timeout != 0.75:
            raise ValueError("offline advisory timeout drift")
        response = evaluate(payload, evaluated_at=evaluated_at)
        return response

    result = dispatch(request, transport=local_transport, decided_at=decided_at)
    if response is None or result["status"] != "OK":
        raise ValueError("offline advisory evaluation failed")
    decision: DecisionEnvelope = combine_decision(
        hard_verdict=request.hardVerdict,
        advisory_verdict=HardVerdict(result["advisoryVerdict"]),
        advisory_status=result["status"],
        evidence_refs=[evidence.evidenceId], decided_at=decided_at,
    )
    record = project_record(
        evidence=[evidence], decision=decision, sequence=sequence,
        previous_hash=previous_hash, recorded_at=recorded_at,
    )
    output = {
        "schemaVersion": REPLAY_SCHEMA,
        "observationId": plan_value["observationId"],
        "requestId": request.requestId,
        "advisoryResponse": response,
        "dispatch": result,
        "projectedRecord": record,
        "projectionOnly": True,
        "executionEffect": "NONE",
        "actionAllowed": False,
    }
    json.dumps(output, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return output


def replay_many(
    items: list[dict[str, Any]], *, base_sequence: int = 0,
    base_hash: str = GENESIS_HASH,
) -> dict[str, Any]:
    """Project an idempotent hash chain over frozen observations without I/O."""
    if not isinstance(items, list) or not 1 <= len(items) <= 64:
        raise ValueError("offline batch size is invalid")
    if not isinstance(base_sequence, int) or isinstance(base_sequence, bool) \
            or base_sequence < 0:
        raise ValueError("offline batch base sequence is invalid")
    if not isinstance(base_hash, str) or len(base_hash) != 64:
        raise ValueError("offline batch base hash is invalid")
    try:
        bytes.fromhex(base_hash)
    except ValueError as exc:
        raise ValueError("offline batch base hash is invalid") from exc

    expected_keys = {
        "plan", "requestedAt", "evaluatedAt", "decidedAt", "recordedAt",
    }
    head = base_hash
    projected: list[dict[str, Any]] = []
    seen: dict[str, dict[str, Any]] = {}
    duplicates: list[str] = []
    for item in items:
        if not isinstance(item, dict) or set(item) != expected_keys:
            raise ValueError("offline batch item fields differ")
        result = replay(
            item["plan"], requested_at=item["requestedAt"],
            evaluated_at=item["evaluatedAt"], decided_at=item["decidedAt"],
            recorded_at=item["recordedAt"],
            sequence=base_sequence + len(projected) + 1, previous_hash=head,
        )
        observation_id = result["observationId"]
        if observation_id in seen:
            first = seen[observation_id]
            comparable = ("requestId", "advisoryResponse", "dispatch")
            if any(result[key] != first[key] for key in comparable) \
                    or result["projectedRecord"]["decision"] \
                    != first["projectedRecord"]["decision"]:
                raise ValueError("offline duplicate observation drift")
            duplicates = [*duplicates, observation_id]
            continue
        seen[observation_id] = result
        projected = [*projected, result]
        head = result["projectedRecord"]["recordHash"]
    return {
        "schemaVersion": BATCH_SCHEMA,
        "baseSequence": base_sequence, "baseHash": base_hash,
        "inputCount": len(items), "projectedCount": len(projected),
        "duplicateCount": len(duplicates), "duplicateObservationIds": duplicates,
        "lastSequence": base_sequence + len(projected), "headHash": head,
        "results": projected, "projectionOnly": True,
        "executionEffect": "NONE", "actionAllowed": False,
    }


def verify_batch(value: Any) -> dict[str, Any]:
    """Strictly verify a frozen batch result and its projected hash chain."""
    batch_keys = {
        "schemaVersion", "baseSequence", "baseHash", "inputCount",
        "projectedCount", "duplicateCount", "duplicateObservationIds",
        "lastSequence", "headHash", "results", "projectionOnly",
        "executionEffect", "actionAllowed",
    }
    result_keys = {
        "schemaVersion", "observationId", "requestId", "advisoryResponse",
        "dispatch", "projectedRecord", "projectionOnly", "executionEffect",
        "actionAllowed",
    }
    dispatch_keys = {
        "schemaVersion", "requestId", "status", "advisoryVerdict",
        "combinedVerdict", "reasonCodes", "modelVersion", "executionEffect",
        "actionAllowed",
    }
    if not isinstance(value, dict) or set(value) != batch_keys \
            or value.get("schemaVersion") != BATCH_SCHEMA:
        raise ValueError("offline batch result fields differ")
    counts = (value.get("inputCount"), value.get("projectedCount"),
              value.get("duplicateCount"), value.get("lastSequence"))
    if any(not isinstance(item, int) or isinstance(item, bool) or item < 0
           for item in counts):
        raise ValueError("offline batch result counts are invalid")
    results = value.get("results")
    duplicates = value.get("duplicateObservationIds")
    if not isinstance(results, list) or not isinstance(duplicates, list) \
            or not 1 <= len(results) <= 64 \
            or value["projectedCount"] != len(results) \
            or value["duplicateCount"] != len(duplicates) \
            or value["inputCount"] != len(results) + len(duplicates):
        raise ValueError("offline batch result cardinality differs")
    if value.get("projectionOnly") is not True \
            or value.get("executionEffect") != "NONE" \
            or value.get("actionAllowed") is not False:
        raise ValueError("offline batch result is not projection-only")

    observations: list[str] = []
    records: list[dict[str, Any]] = []
    for item in results:
        if not isinstance(item, dict) or set(item) != result_keys \
                or item.get("schemaVersion") != REPLAY_SCHEMA \
                or item.get("projectionOnly") is not True \
                or item.get("executionEffect") != "NONE" \
                or item.get("actionAllowed") is not False \
                or not re.fullmatch(r"obs_[a-f0-9]{64}", str(item.get("observationId"))):
            raise ValueError("offline replay result fields differ")
        response = AdvisoryResponse.model_validate(item.get("advisoryResponse"))
        dispatch_value = item.get("dispatch")
        if not isinstance(dispatch_value, dict) or set(dispatch_value) != dispatch_keys \
                or dispatch_value.get("schemaVersion") != "shadow-advisory-dispatch.v1" \
                or dispatch_value.get("status") != "OK" \
                or dispatch_value.get("executionEffect") != "NONE" \
                or dispatch_value.get("actionAllowed") is not False:
            raise ValueError("offline dispatch result fields differ")
        record = item.get("projectedRecord")
        if not isinstance(record, dict):
            raise ValueError("offline projected record is invalid")
        decision = record.get("decision") if isinstance(record, dict) else None
        if not isinstance(decision, dict) \
                or item.get("requestId") != response.requestId \
                or dispatch_value.get("requestId") != response.requestId \
                or dispatch_value.get("advisoryVerdict") != response.advisoryVerdict.value \
                or dispatch_value.get("modelVersion") != response.modelVersion \
                or dispatch_value.get("advisoryVerdict") != decision.get("advisoryVerdict") \
                or dispatch_value.get("combinedVerdict") != decision.get("combinedVerdict") \
                or dispatch_value.get("reasonCodes") != decision.get("reasonCodes"):
            raise ValueError("offline result bindings differ")
        observations = [*observations, item["observationId"]]
        records = [*records, record]
    if len(set(observations)) != len(observations):
        raise ValueError("offline projected observations are duplicated")
    if any(not isinstance(item, str) or item not in observations for item in duplicates):
        raise ValueError("offline duplicate observations are invalid")

    try:
        verification = verify_record_projection(
            records, base_sequence=value.get("baseSequence"),
            base_hash=value.get("baseHash"))
    except ShadowJournalError as exc:
        raise ValueError("offline projected chain is invalid") from exc
    if value["lastSequence"] != verification["lastSequence"] \
            or value.get("headHash") != verification["headHash"]:
        raise ValueError("offline batch head differs")
    return {
        "schemaVersion": VERIFY_SCHEMA, "valid": True,
        "inputCount": value["inputCount"],
        "projectedCount": value["projectedCount"],
        "duplicateCount": value["duplicateCount"],
        "baseSequence": verification["baseSequence"],
        "lastSequence": verification["lastSequence"],
        "baseHash": verification["baseHash"], "headHash": verification["headHash"],
        "policyVersions": verification["policyVersions"],
        "projectionOnly": True, "executionEffect": "NONE", "actionAllowed": False,
    }
