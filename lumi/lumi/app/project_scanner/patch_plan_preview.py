import uuid
from typing import List
from lumi.app.schemas.project_scanner import PatchPlanPreview, ImprovementCandidate, ProjectIssue

class PatchPlanPreviewBuilder:
    def build_previews(self, project_id: str, candidates: List[ImprovementCandidate], issues: List[ProjectIssue]) -> List[PatchPlanPreview]:
        previews = []
        for candidate in candidates:
            related = [i for i in issues if i.issueId in candidate.relatedIssueIds]
            targets = sorted({i.filePath for i in related if i.filePath})
            lower = (candidate.title + " " + candidate.summary).lower()
            changes = []
            if "readme" in lower or "documentation" in lower:
                changes.append({"action": "create_or_update_readme", "description": "Prepare README/documentation update preview"})
            if "test" in lower:
                changes.append({"action": "add_basic_tests", "description": "Prepare basic test coverage preview"})
            if "sensitive" in lower or "secret" in lower or "security" in lower:
                changes.append({"action": "remove_sensitive_content", "description": "Prepare sensitive-content remediation preview"})
            if "configuration" in lower or "config" in lower:
                changes.append({"action": "add_config_file", "description": "Prepare project configuration preview"})
            if "maintain" in lower or "structure" in lower:
                changes.append({"action": "split_or_review_files", "description": "Prepare maintainability/structure review preview"})
            if not changes:
                changes.append({"action": "review", "description": "Review related project issue(s)"})
            previews.append(PatchPlanPreview(
                patchPlanId=str(uuid.uuid4()), projectId=project_id,
                improvementCandidateId=candidate.candidateId,
                title=f"Patch Plan Preview: {candidate.title}", summary=candidate.summary,
                targetFiles=targets, proposedChanges=changes, riskLevel=candidate.riskLevel,
                requiresApproval=True, canApply=False, applyBlockedReason="real_file_write_disabled_in_v0_8",
            ))
        return previews
