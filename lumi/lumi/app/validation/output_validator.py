from typing import Optional
from lumi.app.schemas.task import TaskRequest
from lumi.app.schemas.routing import TaskRequirements, RoutePlan
from lumi.app.schemas.validation import ProviderOutputValidationResult, NormalizedOutputEnvelope
from lumi.app.validation.validation_rules import ValidationRules
from lumi.app.validation.validation_score import ValidationScorer


class OutputValidator:
    def __init__(self):
        self.rules = ValidationRules()
        self.scorer = ValidationScorer()

    def validate(self, normalized_envelope: NormalizedOutputEnvelope, task_request: Optional[TaskRequest] = None, task_requirements: Optional[TaskRequirements] = None, route_plan: Optional[RoutePlan] = None) -> ProviderOutputValidationResult:
        output = normalized_envelope.output
        task_id = task_request.taskId if task_request else None
        issues = self.rules.run_all_rules(output)
        # Treat normalization warnings as validation warnings, but not all are severe.
        for warning in normalized_envelope.normalizationWarnings:
            if warning not in {"plain_string_normalized"}:
                from uuid import uuid4
                from lumi.app.schemas.validation import ValidationIssue
                issues.append(ValidationIssue(issueId=str(uuid4()), code=f"NORMALIZATION_{warning.upper().replace(':','_')}", severity="warning", message=f"Normalization warning: {warning}", recoverable=True))
        validation_score = self.scorer.score(issues, output, task_requirements)
        validation_status = self.scorer.get_validation_status(validation_score)
        critical_issues = [i for i in issues if i.severity == "critical"]
        rejected = bool(critical_issues) or validation_status == "rejected"
        rejection_reason = None
        if critical_issues:
            rejection_reason = "Critical issues: " + ", ".join(i.code for i in critical_issues)
        elif rejected:
            rejection_reason = f"Validation score too low: {validation_score:.2f}"
        warnings = [i.message for i in issues if i.severity in {"warning", "info"}]
        return ProviderOutputValidationResult(providerId=output.providerId, taskId=task_id, validationStatus=validation_status, validationScore=round(validation_score, 4), issues=issues, normalizedOutput=output, rejected=rejected, rejectionReason=rejection_reason, warnings=warnings, metadata={"originalStatus": normalized_envelope.originalStatus, "normalizationWarnings": normalized_envelope.normalizationWarnings, "taskClass": task_requirements.taskClass if task_requirements else None, "routeId": route_plan.routeId if route_plan else None})
