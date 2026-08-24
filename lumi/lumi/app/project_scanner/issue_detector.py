from typing import List
from lumi.app.schemas.project_scanner import ProjectIssue

class IssueDetector:
    def normalize_issues(self, issues: List[ProjectIssue]) -> List[ProjectIssue]:
        return issues
    def deduplicate_issues(self, issues: List[ProjectIssue]) -> List[ProjectIssue]:
        seen = set(); result = []
        for issue in issues:
            key = (issue.category, issue.filePath or "", issue.title)
            if key not in seen:
                seen.add(key); result.append(issue)
        return result
    def severity_counts(self, issues: List[ProjectIssue]) -> dict:
        out = {}
        for issue in issues: out[issue.severity] = out.get(issue.severity, 0) + 1
        return out
    def category_counts(self, issues: List[ProjectIssue]) -> dict:
        out = {}
        for issue in issues: out[issue.category] = out.get(issue.category, 0) + 1
        return out
