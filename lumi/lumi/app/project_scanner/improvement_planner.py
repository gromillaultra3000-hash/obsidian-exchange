import uuid
from typing import List
from lumi.app.schemas.project_scanner import ImprovementPlan, ImprovementCandidate, ProjectIssue, HostProjectProfile

class ImprovementPlanner:
    def __init__(self, action_gateway=None):
        self.action_gateway = action_gateway

    def build_plan(self, profile: HostProjectProfile, scan_id: str, issues: List[ProjectIssue], candidates: List[ImprovementCandidate]) -> ImprovementPlan:
        critical = sum(1 for i in issues if i.severity == "critical")
        high_priority = sum(1 for c in candidates if c.priority in {"high", "critical"})
        plan = ImprovementPlan(
            planId=str(uuid.uuid4()), projectId=profile.projectId, scanId=scan_id,
            title=f"Improvement Plan for {profile.displayName}",
            summary=f"Found {len(issues)} issue(s), including {critical} critical. Prepared {len(candidates)} improvement candidate(s).",
            candidates=candidates, totalIssues=len(issues), criticalIssues=critical,
            highPriorityCandidates=high_priority,
            recommendedNextStep="review_improvement_plan" if candidates else "no_improvement_candidates_detected",
            metadata={"projectType": profile.projectType},
        )
        if self.action_gateway and candidates:
            top = [c for c in candidates if c.priority in {"high", "critical", "medium"}]
            if top:
                try:
                    result = self.action_gateway.propose_action(
                        "create_patch_preview",
                        proposed_input={
                            "projectId": profile.projectId,
                            "candidateSummaries": [c.summary for c in top[:5]],
                            "targetFiles": [],
                            "changeSummary": plan.summary,
                        },
                        requested_mode="proposal",
                    )
                    plan.actionGatewayResult = result.model_dump()
                    if result.approvalPrompt:
                        plan.approvalPrompt = result.approvalPrompt.model_dump()
                    plan.recommendedNextStep = "review_action_gateway_result_for_patch_preview"
                except Exception as exc:
                    plan.metadata["actionGatewayWarning"] = str(exc)
                    plan.recommendedNextStep = "register_create_patch_preview_action_or_review_plan"
        return plan
