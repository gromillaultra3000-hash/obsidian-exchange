from typing import List, Optional, Any
from lumi.app.schemas.task import TaskRequest
from lumi.app.schemas.provider import ProviderProfile, ProviderOutput
from lumi.app.schemas.routing import TaskRequirements, RoutePlan
from lumi.app.schemas.validation import ValidationPipelineResult, NormalizedOutputEnvelope
from lumi.app.audit.audit_log import AuditLog
from lumi.app.providers.redaction import RedactionUtil
from lumi.app.validation.output_normalizer import OutputNormalizer
from lumi.app.validation.output_validator import OutputValidator


class ValidationPipeline:
    def __init__(self, audit_log: AuditLog, redaction: RedactionUtil):
        self.audit_log = audit_log
        self.redaction = redaction
        self.normalizer = OutputNormalizer(redaction)
        self.validator = OutputValidator()

    def validate_outputs(self, provider_outputs: List[Any], task_request: TaskRequest, provider_profiles: Optional[List[ProviderProfile]] = None, task_requirements: Optional[TaskRequirements] = None, route_plan: Optional[RoutePlan] = None) -> ValidationPipelineResult:
        task_id = task_request.taskId or "unknown"
        self.audit_log.add_entry("validation_pipeline_started", task_id=task_id, summary=f"Validation pipeline started for {len(provider_outputs)} outputs")
        profiles = {p.providerId: p for p in (provider_profiles or [])}
        results = []
        for index, raw_output in enumerate(provider_outputs):
            provider_id = self._extract_provider_id(raw_output)
            if not provider_id and index < len(provider_profiles or []):
                provider_id = (provider_profiles or [])[index].providerId
            profile = profiles.get(provider_id or "") or ProviderProfile(providerId=provider_id or f"unknown-{index}", displayName="Unknown Provider", providerType="mock", apiFormat="json", enabled=True, roles=[], capabilities=[], costProfile={}, latencyProfile={}, reliabilityScore=0.0)
            try:
                normalized = self.normalizer.normalize_provider_output(raw_output, profile, task_request)
                self.audit_log.add_entry("provider_output_normalized", task_id=task_id, provider_id=profile.providerId, summary=f"Output normalized for {profile.providerId}", details={"warnings": normalized.normalizationWarnings, "rawOutputRedacted": normalized.rawOutputRedacted})
            except Exception as exc:
                normalized = NormalizedOutputEnvelope(providerId=profile.providerId, taskId=task_id, normalizedStatus="invalid", output=ProviderOutput(providerId=profile.providerId, status="invalid", suggestedStatus="WAIT", errors=[str(exc)]), normalizationWarnings=[f"Normalization failed: {exc}"], rawOutputRedacted={})
                self.audit_log.add_entry("malformed_output_detected", task_id=task_id, provider_id=profile.providerId, status="error", summary="Malformed output detected", details={"error": str(exc)})
            result = self.validator.validate(normalized, task_request, task_requirements, route_plan)
            if result.rejected:
                self.audit_log.add_entry("provider_output_rejected", task_id=task_id, provider_id=profile.providerId, status="rejected", summary=f"Output rejected for {profile.providerId}: {result.rejectionReason}", details={"issues": [i.model_dump() for i in result.issues]})
            else:
                self.audit_log.add_entry("provider_output_validated", task_id=task_id, provider_id=profile.providerId, summary=f"Output validated for {profile.providerId}: {result.validationStatus}", details={"score": result.validationScore, "status": result.validationStatus})
            for issue in result.issues:
                self.audit_log.add_entry("validation_issue_detected", task_id=task_id, provider_id=profile.providerId, status=issue.severity, summary=f"Issue: {issue.code}", details=issue.model_dump())
                if "forbidden" in issue.code.lower() or "unsafe" in issue.code.lower():
                    self.audit_log.add_entry("unsafe_wording_detected", task_id=task_id, provider_id=profile.providerId, status="critical", summary=f"Unsafe wording: {issue.code}")
                if "secret" in issue.code.lower():
                    self.audit_log.add_entry("secret_like_content_detected", task_id=task_id, provider_id=profile.providerId, status="critical", summary=f"Secret-like content: {issue.code}")
            results.append(result)
        valid = sum(1 for r in results if r.validationStatus == "valid" and not r.rejected)
        degraded = sum(1 for r in results if r.validationStatus == "degraded" and not r.rejected)
        rejected = sum(1 for r in results if r.rejected or r.validationStatus == "rejected")
        accepted_ids = [r.providerId for r in results if not r.rejected and r.validationStatus != "rejected"]
        rejected_ids = [r.providerId for r in results if r.rejected or r.validationStatus == "rejected"]
        if not accepted_ids:
            overall = "rejected"
        elif rejected or degraded:
            overall = "degraded"
        else:
            overall = "valid"
        summary = f"Validation complete: {valid} valid, {degraded} degraded, {rejected} rejected out of {len(results)}"
        pipeline_result = ValidationPipelineResult(taskId=task_id, totalOutputs=len(results), validOutputs=valid, degradedOutputs=degraded, rejectedOutputs=rejected, results=results, acceptedProviderIds=accepted_ids, rejectedProviderIds=rejected_ids, overallValidationStatus=overall, summary=summary, metadata={"taskClass": task_requirements.taskClass if task_requirements else None, "routeStatus": route_plan.routeStatus if route_plan else None})
        self.audit_log.add_entry("validation_pipeline_completed", task_id=task_id, summary=summary, details={"overallStatus": overall, "acceptedProviderIds": accepted_ids, "rejectedProviderIds": rejected_ids})
        return pipeline_result

    def _extract_provider_id(self, raw_output: Any) -> Optional[str]:
        if isinstance(raw_output, ProviderOutput):
            return raw_output.providerId
        if isinstance(raw_output, dict):
            return raw_output.get("providerId")
        return None
