import uuid
from typing import List
from lumi.app.schemas.project_scanner import ProjectIssue, ImprovementCandidate

CATEGORY_MAP = {
    "documentation": ("Add or update project README/documentation", "medium", "low"),
    "testing": ("Add basic test coverage", "medium", "low"),
    "security": ("Remove or secure sensitive-looking content", "critical", "high"),
    "configuration": ("Add explicit project configuration", "medium", "low"),
    "maintainability": ("Improve project maintainability", "medium", "medium"),
    "structure": ("Clarify application entrypoint and structure", "medium", "medium"),
    "quality": ("Improve project quality hygiene", "low", "low"),
}
SEVERITY_PRIORITY = {"critical": "critical", "error": "high", "warning": "medium", "info": "low"}

class ImprovementCandidateBuilder:
    def build_candidates(self, project_id: str, issues: List[ProjectIssue]) -> List[ImprovementCandidate]:
        grouped: dict[str, list[ProjectIssue]] = {}
        for issue in issues:
            grouped.setdefault(issue.category, []).append(issue)
        candidates = []
        for category, items in grouped.items():
            title, default_priority, risk = CATEGORY_MAP.get(category, ("Review project issue category", "low", "low"))
            priority = default_priority
            for issue in items:
                p = SEVERITY_PRIORITY.get(issue.severity, "low")
                if ["low", "medium", "high", "critical"].index(p) > ["low", "medium", "high", "critical"].index(priority):
                    priority = p
            candidates.append(ImprovementCandidate(
                candidateId=str(uuid.uuid4()), projectId=project_id,
                relatedIssueIds=[i.issueId for i in items], title=title,
                summary=f"{len(items)} issue(s) mapped to improvement category '{category}'.",
                priority=priority, expectedImpact=f"Address {len(items)} {category} issue(s).",
                riskLevel="high" if priority == "critical" else risk,
                requiresApproval=priority in {"high", "critical"} or risk in {"medium", "high"},
                proposedActionId="create_patch_preview" if priority in {"medium", "high", "critical"} else None,
                metadata={"category": category},
            ))
        return candidates
