from typing import List
from lumi.app.schemas.provider import ProviderOutput
from lumi.app.schemas.validation import ValidationIssue


class ValidationScorer:
    def __init__(self):
        self.severity_penalties = {"info": 0.02, "warning": 0.08, "error": 0.25, "critical": 0.6}

    def score(self, issues: List[ValidationIssue], normalized_output: ProviderOutput, task_requirements=None) -> float:
        score = 1.0
        for issue in issues:
            score -= self.severity_penalties.get(issue.severity, 0.0)
        if normalized_output.status == "success" and not normalized_output.answer:
            score -= 0.3
        if normalized_output.confidence is None or normalized_output.confidence == 0.0:
            score -= 0.1
        if normalized_output.suggestedStatus == "APPROVE" and normalized_output.confidence >= 0.75 and not normalized_output.evidenceRefs and not normalized_output.assumptions:
            score -= 0.15
        return max(0.0, min(1.0, score))

    def get_validation_status(self, score: float) -> str:
        if score >= 0.8:
            return "valid"
        if score >= 0.45:
            return "degraded"
        return "rejected"
