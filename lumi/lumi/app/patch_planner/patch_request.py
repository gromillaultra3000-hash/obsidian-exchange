import uuid
from typing import List, Optional, Any
from lumi.app.schemas.patch_planner import PatchRequest
from lumi.app.schemas.project_scanner import ImprovementCandidate, ImprovementPlan, ProjectIssue
from lumi.app.providers.redaction import RedactionUtil

class PatchRequestNormalizer:
    def __init__(self, redaction: RedactionUtil | None = None):
        self.redaction = redaction or RedactionUtil()

    def normalize_request(self, raw_request: PatchRequest | dict) -> PatchRequest:
        if isinstance(raw_request, PatchRequest):
            data = raw_request.model_dump()
        else:
            data = dict(raw_request or {})
        request_id = data.get("requestId") or str(uuid.uuid4())
        return PatchRequest(
            requestId=request_id,
            projectId=data.get("projectId", ""),
            source=data.get("source", "manual"),
            improvementCandidateId=data.get("improvementCandidateId"),
            improvementPlanId=data.get("improvementPlanId"),
            title=data.get("title") or "Untitled Patch Request",
            summary=self.redaction.redact_any(data.get("summary", "")),
            targetFiles=list(data.get("targetFiles") or []),
            requestedChanges=self.redaction.redact_any(list(data.get("requestedChanges") or [])),
            riskLevel=data.get("riskLevel", "unknown"),
            metadata=self.redaction.redact_dict(data.get("metadata") or {}),
        )

    def from_improvement_candidate(self, project_id: str, candidate: ImprovementCandidate | dict, issues: Optional[List[ProjectIssue]] = None) -> PatchRequest:
        if isinstance(candidate, dict):
            candidate = ImprovementCandidate(**candidate)
        related_issues = issues or []
        target_files = sorted(set(i.filePath for i in related_issues if i.filePath))
        changes = []
        for issue in related_issues:
            changes.append({"changeType": "security_fix" if issue.category == "security" else "refactor", "description": issue.suggestedFix or issue.title})
        if not changes:
            changes = [{"changeType": "unknown", "description": candidate.summary or candidate.title}]
        return PatchRequest(
            requestId=str(uuid.uuid4()), projectId=project_id, source="improvement_candidate",
            improvementCandidateId=candidate.candidateId, title=f"Patch Preview: {candidate.title}",
            summary=candidate.summary, targetFiles=target_files,
            requestedChanges=self.redaction.redact_any(changes),
            riskLevel=candidate.riskLevel if candidate.riskLevel in ["low", "medium", "high", "critical"] else "unknown",
            metadata={"candidateId": candidate.candidateId},
        )

    def from_improvement_plan(self, project_id: str, plan: ImprovementPlan) -> PatchRequest:
        target_files = []
        changes = []
        for candidate in plan.candidates:
            target_files.extend(candidate.metadata.get("targetFiles", []))
            changes.append({"changeType": "refactor", "description": candidate.summary or candidate.title})
        return PatchRequest(
            requestId=str(uuid.uuid4()), projectId=project_id, source="improvement_plan", improvementPlanId=plan.planId,
            title=f"Patch Preview: {plan.title}", summary=plan.summary,
            targetFiles=sorted(set(target_files))[:20], requestedChanges=self.redaction.redact_any(changes[:10]),
            riskLevel="medium", metadata={"planId": plan.planId},
        )

    def from_dialog(self, project_id: str, text: str, metadata: Optional[dict] = None) -> PatchRequest:
        metadata = metadata or {}
        return PatchRequest(
            requestId=str(uuid.uuid4()), projectId=project_id, source="dialog", title=metadata.get("title", "Dialog Patch Request"),
            summary=self.redaction.redact_secret_like((text or "")[:500]), targetFiles=metadata.get("targetFiles", []),
            requestedChanges=self.redaction.redact_any(metadata.get("requestedChanges", [{"changeType": "unknown", "description": (text or "")[:200]}])),
            riskLevel=metadata.get("riskLevel", "unknown"), metadata=self.redaction.redact_dict(metadata),
        )
