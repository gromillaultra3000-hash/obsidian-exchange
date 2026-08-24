from __future__ import annotations
from uuid import uuid4
from typing import Iterable
from lumi.app.schemas.provider import ProviderOutput
from lumi.app.schemas.routing import RoutePlan
from lumi.app.schemas.validation import ValidationPipelineResult
from lumi.app.schemas.conflict import ConflictAnalysisReport, DeterministicResolution

class DeterministicResolver:
    def resolve(self, task_id: str, accepted_outputs: Iterable[ProviderOutput], validation_result: ValidationPipelineResult, conflict_report: ConflictAnalysisReport, route_plan: RoutePlan | None = None) -> DeterministicResolution:
        outputs = list(accepted_outputs)
        accepted_ids = list(validation_result.acceptedProviderIds)
        rejected_ids = list(validation_result.rejectedProviderIds)
        valid = [o for o in outputs if o.status == "success"]
        avg_confidence = round(sum(o.confidence for o in valid) / len(valid), 4) if valid else 0.0
        suggestions = [o.suggestedStatus or "WAIT" for o in valid]
        approve_count = suggestions.count("APPROVE")
        reject_count = suggestions.count("REJECT")
        wait_count = suggestions.count("WAIT")
        route_fallback = bool(route_plan and route_plan.fallbackUsed)

        # Fail-closed rules first.
        if not outputs:
            return DeterministicResolution(resolutionId=f"res-{uuid4().hex[:12]}", taskId=task_id, status="SAFE_DEFAULT", actionAllowed=False, confidence=0.0, riskLevel="high", conflictDetected=conflict_report.conflictDetected, conflictType=conflict_report.primaryConflictType, winningRule="no_accepted_outputs", summary="No accepted provider outputs after validation", requiredNextStep="review_provider_outputs", acceptedProviderIds=accepted_ids, rejectedProviderIds=rejected_ids)
        if not valid:
            return DeterministicResolution(resolutionId=f"res-{uuid4().hex[:12]}", taskId=task_id, status="SAFE_DEFAULT", actionAllowed=False, confidence=0.0, riskLevel="high", conflictDetected=conflict_report.conflictDetected, conflictType=conflict_report.primaryConflictType, winningRule="no_valid_outputs", summary="No valid success provider outputs after validation", requiredNextStep="review_provider_outputs", acceptedProviderIds=accepted_ids, rejectedProviderIds=rejected_ids)
        if conflict_report.primaryConflictType in {"RISK_CONFLICT", "POLICY_CONFLICT"}:
            return DeterministicResolution(resolutionId=f"res-{uuid4().hex[:12]}", taskId=task_id, status="WAIT", actionAllowed=False, confidence=min(avg_confidence, 0.5), riskLevel="high", conflictDetected=True, conflictType=conflict_report.primaryConflictType, winningRule="risk_or_policy_conflict_defaults_to_wait", summary="Risk/policy conflict detected; conservative WAIT decision", requiredNextStep="collect_more_evidence_or_manual_review", userApprovalRequired=True, acceptedProviderIds=accepted_ids, rejectedProviderIds=rejected_ids, metadata={"disagreementScore": conflict_report.disagreementScore})
        if conflict_report.primaryConflictType == "ACTION_CONFLICT":
            return DeterministicResolution(resolutionId=f"res-{uuid4().hex[:12]}", taskId=task_id, status="ASK_USER", actionAllowed=False, confidence=min(avg_confidence, 0.6), riskLevel="medium", conflictDetected=True, conflictType="ACTION_CONFLICT", winningRule="approve_reject_conflict_asks_user", summary="Action conflict detected between provider outputs", requiredNextStep="operator_or_host_review", userApprovalRequired=True, acceptedProviderIds=accepted_ids, rejectedProviderIds=rejected_ids, metadata={"disagreementScore": conflict_report.disagreementScore})
        if conflict_report.primaryConflictType in {"DATA_CONFLICT", "CONFIDENCE_CONFLICT", "VALIDATION_CONFLICT"} and conflict_report.disagreementScore >= 0.35:
            return DeterministicResolution(resolutionId=f"res-{uuid4().hex[:12]}", taskId=task_id, status="WAIT", actionAllowed=False, confidence=min(avg_confidence, 0.74), riskLevel="medium", conflictDetected=True, conflictType=conflict_report.primaryConflictType, winningRule="data_or_confidence_conflict_requires_wait", summary="Evidence/confidence/validation conflict requires more information", requiredNextStep="collect_more_data", acceptedProviderIds=accepted_ids, rejectedProviderIds=rejected_ids, metadata={"disagreementScore": conflict_report.disagreementScore})
        if reject_count > 0:
            return DeterministicResolution(resolutionId=f"res-{uuid4().hex[:12]}", taskId=task_id, status="REJECT", actionAllowed=False, confidence=min(max(avg_confidence, 0.5), 0.9), riskLevel="high", conflictDetected=conflict_report.conflictDetected, conflictType=conflict_report.primaryConflictType, winningRule="reject_signal_blocks_approval", summary="At least one accepted provider suggested REJECT", requiredNextStep="review_rejection_reason", acceptedProviderIds=accepted_ids, rejectedProviderIds=rejected_ids)
        if route_fallback:
            return DeterministicResolution(resolutionId=f"res-{uuid4().hex[:12]}", taskId=task_id, status="WAIT", actionAllowed=False, confidence=min(avg_confidence, 0.55), riskLevel="medium", conflictDetected=conflict_report.conflictDetected, conflictType=conflict_report.primaryConflictType, winningRule="fallback_route_cannot_approve", summary="Fallback route used; approval is not allowed", requiredNextStep="register_primary_provider", acceptedProviderIds=accepted_ids, rejectedProviderIds=rejected_ids)
        if approve_count > 0 and avg_confidence >= 0.75 and not conflict_report.conflictDetected:
            return DeterministicResolution(resolutionId=f"res-{uuid4().hex[:12]}", taskId=task_id, status="APPROVE", actionAllowed=True, confidence=avg_confidence, riskLevel="low", conflictDetected=False, conflictType="NONE", winningRule="validated_no_conflict_high_confidence_approve", summary="Validated outputs agree without conflict and meet confidence threshold", acceptedProviderIds=accepted_ids, rejectedProviderIds=rejected_ids)
        return DeterministicResolution(resolutionId=f"res-{uuid4().hex[:12]}", taskId=task_id, status="WAIT", actionAllowed=False, confidence=min(avg_confidence, 0.74), riskLevel="medium", conflictDetected=conflict_report.conflictDetected, conflictType=conflict_report.primaryConflictType, winningRule="low_confidence_wait", summary="Confidence below threshold or no approval suggestion", requiredNextStep="collect_more_evidence", acceptedProviderIds=accepted_ids, rejectedProviderIds=rejected_ids, metadata={"approveCount": approve_count, "rejectCount": reject_count, "waitCount": wait_count})
