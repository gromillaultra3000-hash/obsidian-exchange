import uuid
from typing import List
from lumi.app.schemas.provider import ProviderOutput
from lumi.app.schemas.validation import ValidationIssue
from lumi.app.validation.unsafe_wording import UnsafeWordingDetector


class ValidationRules:
    def __init__(self):
        self.unsafe_detector = UnsafeWordingDetector()
        self.allowed_statuses = {"success", "error", "timeout", "invalid"}
        self.allowed_suggested_statuses = {"APPROVE", "REJECT", "WAIT", "ESCALATE", "SAFE_DEFAULT", "ASK_USER"}

    def _issue(self, code: str, severity: str, message: str, field: str | None = None, recoverable: bool = True, details: dict | None = None) -> ValidationIssue:
        return ValidationIssue(issueId=str(uuid.uuid4()), code=code, severity=severity, message=message, field=field, recoverable=recoverable, details=details or {})

    def check_schema_validity(self, output: ProviderOutput) -> List[ValidationIssue]:
        issues: list[ValidationIssue] = []
        if not output.providerId:
            issues.append(self._issue("SCHEMA_MISSING_PROVIDER_ID", "error", "ProviderOutput missing providerId", "providerId", False))
        if output.status not in self.allowed_statuses:
            issues.append(self._issue("SCHEMA_INVALID_STATUS", "error", f"Invalid status: {output.status}", "status", False, {"invalid_status": output.status}))
        if output.suggestedStatus and output.suggestedStatus not in self.allowed_suggested_statuses:
            issues.append(self._issue("SCHEMA_INVALID_SUGGESTED_STATUS", "warning", f"Invalid suggestedStatus: {output.suggestedStatus}", "suggestedStatus", True, {"invalid_suggested_status": output.suggestedStatus}))
        for field in ["riskFlags", "assumptions", "evidenceRefs", "errors"]:
            if not isinstance(getattr(output, field), list):
                issues.append(self._issue(f"SCHEMA_{field.upper()}_NOT_LIST", "warning", f"{field} is not a list", field, True))
        return issues

    def check_non_empty_answer(self, output: ProviderOutput) -> List[ValidationIssue]:
        if output.status == "success" and not (output.answer or "").strip():
            severity = "critical" if output.confidence and output.confidence > 0.3 else "error"
            return [self._issue("EMPTY_ANSWER_FOR_SUCCESS", severity, "Empty answer for success status", "answer", severity != "critical", {"confidence": output.confidence})]
        return []

    def check_confidence_range(self, output: ProviderOutput) -> List[ValidationIssue]:
        if output.confidence is None:
            return [self._issue("MISSING_CONFIDENCE", "warning", "Confidence is missing", "confidence", True)]
        if output.confidence < 0 or output.confidence > 1:
            return [self._issue("CONFIDENCE_OUT_OF_RANGE", "error", f"Confidence {output.confidence} out of range 0-1", "confidence", False, {"confidence": output.confidence})]
        return []

    def check_evidence_required_for_approval(self, output: ProviderOutput) -> List[ValidationIssue]:
        if output.suggestedStatus == "APPROVE" and output.confidence >= 0.75 and not output.evidenceRefs and not output.assumptions:
            return [self._issue("MISSING_EVIDENCE_FOR_APPROVAL", "error", "APPROVE with high confidence requires evidence or assumptions", "evidenceRefs/assumptions", True, {"confidence": output.confidence})]
        return []

    def check_errors_required_for_error_status(self, output: ProviderOutput) -> List[ValidationIssue]:
        if output.status in {"error", "timeout", "invalid"} and not output.errors:
            return [self._issue("MISSING_ERRORS_FOR_ERROR_STATUS", "warning", f"No errors provided for status: {output.status}", "errors", True, {"status": output.status})]
        return []

    def check_unsafe_wording(self, output: ProviderOutput) -> List[ValidationIssue]:
        if not output.answer:
            return []
        return self.unsafe_detector.detect_unsafe_wording(output.answer)


    def check_redacted_secret_warning(self, output: ProviderOutput) -> List[ValidationIssue]:
        warnings = []
        raw = output.rawOutputRedacted or {}
        if isinstance(raw, dict) and "answer" in raw and "***REDACTED***" in str(raw.get("answer")):
            warnings.append(self._issue("SECRET_LIKE_CONTENT", "critical", "Secret-like content was redacted from provider answer", "answer", False, {"redacted": True}))
        return warnings

    def check_no_fake_success(self, output: ProviderOutput) -> List[ValidationIssue]:
        if output.status == "success" and not output.answer and output.confidence > 0.7 and not output.evidenceRefs and not output.assumptions:
            return [self._issue("FAKE_SUCCESS_DETECTED", "critical", "High confidence success with no evidence or content", "answer", False, {"confidence": output.confidence})]
        return []

    def run_all_rules(self, output: ProviderOutput) -> List[ValidationIssue]:
        issues: list[ValidationIssue] = []
        issues.extend(self.check_schema_validity(output))
        issues.extend(self.check_non_empty_answer(output))
        issues.extend(self.check_confidence_range(output))
        issues.extend(self.check_evidence_required_for_approval(output))
        issues.extend(self.check_errors_required_for_error_status(output))
        issues.extend(self.check_unsafe_wording(output))
        issues.extend(self.check_redacted_secret_warning(output))
        issues.extend(self.check_no_fake_success(output))
        return issues
