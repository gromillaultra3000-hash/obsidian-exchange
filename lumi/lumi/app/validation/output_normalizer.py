from typing import Optional, Dict, Any
from pydantic import ValidationError
from lumi.app.schemas.provider import ProviderProfile, ProviderOutput
from lumi.app.schemas.task import TaskRequest
from lumi.app.schemas.validation import NormalizedOutputEnvelope
from lumi.app.providers.redaction import RedactionUtil


class OutputNormalizer:
    def __init__(self, redaction: Optional[RedactionUtil] = None):
        self.redaction = redaction or RedactionUtil()
        self.allowed_statuses = {"success", "error", "timeout", "invalid"}
        self.allowed_suggested = {"APPROVE", "REJECT", "WAIT", "ESCALATE", "SAFE_DEFAULT", "ASK_USER"}

    def normalize_provider_output(self, raw_output: Any, provider_profile: ProviderProfile, task_request: Optional[TaskRequest] = None) -> NormalizedOutputEnvelope:
        task_id = task_request.taskId if task_request else None
        if raw_output is None:
            return self._none(provider_profile.providerId, task_id)
        if isinstance(raw_output, str):
            return self._string(raw_output, provider_profile, task_id)
        if isinstance(raw_output, ProviderOutput):
            return self._dict(raw_output.model_dump(), provider_profile, task_id, source="ProviderOutput")
        if isinstance(raw_output, dict):
            return self._dict(raw_output, provider_profile, task_id, source="dict")
        return self._error(provider_profile.providerId, task_id, f"unknown_output_type:{type(raw_output).__name__}")

    def _none(self, provider_id: str, task_id: Optional[str]) -> NormalizedOutputEnvelope:
        output = ProviderOutput(providerId=provider_id, status="invalid", answer=None, confidence=0.0, suggestedStatus="WAIT", errors=["empty_output"])
        return NormalizedOutputEnvelope(providerId=provider_id, taskId=task_id, originalStatus=None, normalizedStatus="invalid", output=output, normalizationWarnings=["none_output"], rawOutputRedacted={})

    def _string(self, text: str, profile: ProviderProfile, task_id: Optional[str]) -> NormalizedOutputEnvelope:
        stripped = text.strip()
        status = "success" if stripped else "invalid"
        output = ProviderOutput(providerId=profile.providerId, role=profile.roles[0] if profile.roles else None, status=status, answer=self.redaction.redact_secret_like(text), confidence=0.5 if stripped else 0.0, suggestedStatus="WAIT", errors=[] if stripped else ["empty_string"], rawOutputRedacted={"original_string": self.redaction.redact_secret_like(text)})
        return NormalizedOutputEnvelope(providerId=profile.providerId, taskId=task_id, originalStatus=None, normalizedStatus=status, output=output, normalizationWarnings=["plain_string_normalized"] + ([] if stripped else ["empty_string"]), rawOutputRedacted={"original_string": self.redaction.redact_secret_like(text)}, metadata={"normalized_from": "string"})

    def _dict(self, raw: Dict[str, Any], profile: ProviderProfile, task_id: Optional[str], source: str) -> NormalizedOutputEnvelope:
        warnings: list[str] = []
        redacted = self.redaction.redact_dict(raw)
        original_status = raw.get("status")
        status = raw.get("status", "success")
        if status not in self.allowed_statuses:
            warnings.append(f"unknown_status:{status}")
            status = "invalid"
        confidence = raw.get("confidence")
        if confidence is None:
            confidence = 0.0
            warnings.append("missing_confidence")
        elif not isinstance(confidence, (int, float)):
            confidence = 0.0
            warnings.append("invalid_confidence_type")
        elif confidence < 0:
            confidence = 0.0
            warnings.append("confidence_clamped")
        elif confidence > 1:
            confidence = 1.0
            warnings.append("confidence_clamped")
        suggested = raw.get("suggestedStatus")
        if suggested is None:
            suggested = "WAIT"
            warnings.append("missing_suggested_status")
        def as_list(name: str):
            value = raw.get(name, [])
            if isinstance(value, list):
                return [self.redaction.redact_secret_like(str(v)) if isinstance(v, str) else v for v in value]
            warnings.append(f"{name}_not_list")
            return [self.redaction.redact_secret_like(str(value))] if value else []
        answer = raw.get("answer")
        if isinstance(answer, str):
            redacted_answer = self.redaction.redact_secret_like(answer)
            if redacted_answer != answer:
                warnings.append("secret_like_content_redacted")
            answer = redacted_answer
        try:
            output = ProviderOutput(
                providerId=raw.get("providerId") or profile.providerId,
                role=raw.get("role") or (profile.roles[0] if profile.roles else None),
                status=status,
                answer=answer,
                confidence=confidence,
                suggestedStatus=suggested,
                riskFlags=as_list("riskFlags"),
                assumptions=as_list("assumptions"),
                evidenceRefs=as_list("evidenceRefs"),
                errors=as_list("errors"),
                rawOutputRedacted=redacted,
            )
        except ValidationError as exc:
            warnings.append("provider_output_schema_validation_error")
            output = ProviderOutput(providerId=profile.providerId, status="invalid", confidence=0.0, suggestedStatus="WAIT", errors=[str(exc)], rawOutputRedacted=redacted)
            status = "invalid"
        return NormalizedOutputEnvelope(providerId=output.providerId, taskId=task_id, originalStatus=original_status, normalizedStatus=status, output=output, normalizationWarnings=warnings, rawOutputRedacted=redacted, metadata={"normalized_from": source})

    def _error(self, provider_id: str, task_id: Optional[str], message: str) -> NormalizedOutputEnvelope:
        output = ProviderOutput(providerId=provider_id, status="invalid", confidence=0.0, suggestedStatus="WAIT", errors=[message])
        return NormalizedOutputEnvelope(providerId=provider_id, taskId=task_id, normalizedStatus="invalid", output=output, normalizationWarnings=["unknown_type_error"], rawOutputRedacted={})
