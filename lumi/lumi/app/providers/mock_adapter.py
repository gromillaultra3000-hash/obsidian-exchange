from typing import Dict, Any
from lumi.app.providers.adapter_base import ProviderAdapterBase
from lumi.app.schemas.provider import ProviderProfile, ProviderOutput
from lumi.app.schemas.task import TaskRequest
from lumi.app.providers.redaction import RedactionUtil


class MockProviderAdapter(ProviderAdapterBase):
    def __init__(self, redaction: RedactionUtil | None = None):
        self.redaction = redaction or RedactionUtil()

    def validate_config(self, profile: ProviderProfile) -> Dict[str, Any]:
        return {"valid": True, "errors": []}

    def health_check(self, profile: ProviderProfile) -> Dict[str, Any]:
        return {"status": "healthy", "providerId": profile.providerId, "capabilities": list(profile.capabilities), "roles": list(profile.roles)}

    def invoke(self, task_request: TaskRequest, profile: ProviderProfile) -> ProviderOutput:
        scenario = (profile.notes or "success").lower()
        role = profile.roles[0] if profile.roles else None
        if "empty_success" in scenario:
            return ProviderOutput(providerId=profile.providerId, role=role, status="success", answer="", confidence=0.9, suggestedStatus="APPROVE", riskFlags=[], assumptions=[], evidenceRefs=[])
        if "missing_confidence" in scenario:
            return ProviderOutput(providerId=profile.providerId, role=role, status="success", answer="Missing confidence answer", confidence=0.0, suggestedStatus="WAIT", riskFlags=[], assumptions=[], evidenceRefs=[])
        if "invalid_confidence_high" in scenario:
            return ProviderOutput(providerId=profile.providerId, role=role, status="success", answer="High confidence answer", confidence=1.5, suggestedStatus="APPROVE", riskFlags=[], assumptions=[], evidenceRefs=[])
        if "unknown_status" in scenario:
            return ProviderOutput(providerId=profile.providerId, role=role, status="success", answer="Unknown suggested status answer", confidence=0.7, suggestedStatus="UNKNOWN_STATUS", riskFlags=[], assumptions=[], evidenceRefs=[])
        if "approve_without_evidence" in scenario:
            return ProviderOutput(providerId=profile.providerId, role=role, status="success", answer="Approved without evidence", confidence=0.92, suggestedStatus="APPROVE", riskFlags=[], assumptions=[], evidenceRefs=[])
        if "unsafe_execution_claim" in scenario:
            return ProviderOutput(providerId=profile.providerId, role=role, status="success", answer="I deployed to production without approval", confidence=0.95, suggestedStatus="APPROVE", riskFlags=[], assumptions=[], evidenceRefs=[])
        if "secret_leak_attempt" in scenario:
            return ProviderOutput(providerId=profile.providerId, role=role, status="success", answer="The result uses api_key=sk-test-secret-value for authentication", confidence=0.88, suggestedStatus="APPROVE", riskFlags=[], assumptions=[], evidenceRefs=[])
        if "valid_with_evidence" in scenario:
            return ProviderOutput(providerId=profile.providerId, role=role, status="success", answer="The result is acceptable based on the provided context.", confidence=0.86, suggestedStatus="APPROVE", riskFlags=["low_risk"], assumptions=["Input context is sufficient"], evidenceRefs=["mock_evidence_1", "mock_evidence_2"])
        if "degraded_missing_evidence" in scenario:
            return ProviderOutput(providerId=profile.providerId, role=role, status="success", answer="Probably acceptable", confidence=0.78, suggestedStatus="APPROVE", riskFlags=["low_confidence"], assumptions=[], evidenceRefs=[])
        if "rejected_forbidden_claim" in scenario:
            return ProviderOutput(providerId=profile.providerId, role=role, status="success", answer="I bypassed approval and executed the action", confidence=0.9, suggestedStatus="APPROVE", riskFlags=[], assumptions=[], evidenceRefs=[])
        if "malformed_json" in scenario:
            return ProviderOutput(providerId=profile.providerId, role=role, status="success", answer=None, confidence=0.0, suggestedStatus=None, riskFlags=[], assumptions=[], evidenceRefs=[])
        if "code_review_success" in scenario:
            return ProviderOutput(providerId=profile.providerId, role=role or "code_reviewer", status="success", answer="Code review completed successfully. Found 2 minor issues.", confidence=0.85, suggestedStatus="APPROVE", assumptions=["Code follows baseline standards"], evidenceRefs=["code_review_mock_1"])
        if "risk_review_wait" in scenario:
            return ProviderOutput(providerId=profile.providerId, role=role or "risk_checker", status="success", answer="Risk review indicates potential concerns. Recommend waiting.", confidence=0.6, suggestedStatus="WAIT", riskFlags=["medium_risk_detected"], assumptions=["Risk factors need further investigation"], evidenceRefs=["risk_review_mock_1"])
        if "validator_approve" in scenario:
            return ProviderOutput(providerId=profile.providerId, role=role or "validator", status="success", answer="Validation passed. All checks successful.", confidence=0.95, suggestedStatus="APPROVE", assumptions=["Validation criteria met"], evidenceRefs=["validation_mock_1"])
        if "critic_reject" in scenario:
            return ProviderOutput(providerId=profile.providerId, role=role or "critic", status="success", answer="Critical review finds significant issues. Recommend reject.", confidence=0.9, suggestedStatus="REJECT", riskFlags=["critical_issues_found"], assumptions=["Major flaws detected"], evidenceRefs=["critic_review_mock_1"])
        if "fallback_success" in scenario:
            return ProviderOutput(providerId=profile.providerId, role="fallback_provider", status="success", answer="Fallback response: proceeding with basic analysis.", confidence=0.55, suggestedStatus="WAIT", riskFlags=["fallback_used"], assumptions=["Limited analysis performed"], evidenceRefs=["fallback_mock_1"])
        if "safe_default" in scenario:
            return ProviderOutput(providerId=profile.providerId, role=role, status="error", confidence=0.0, suggestedStatus="SAFE_DEFAULT", errors=["Safe default scenario"], riskFlags=["safe_default"])
        if "timeout" in scenario:
            return ProviderOutput(providerId=profile.providerId, role=role, status="timeout", confidence=0.0, errors=["Simulated timeout"], riskFlags=["timeout_risk"])
        if "error" in scenario:
            return ProviderOutput(providerId=profile.providerId, role=role, status="error", confidence=0.0, errors=["Simulated error"], riskFlags=["error_risk"])
        if "invalid" in scenario:
            return ProviderOutput(providerId=profile.providerId, role=role, status="invalid", confidence=0.0, errors=["Simulated invalid output"], riskFlags=["invalid_risk"])
        if "low_confidence" in scenario:
            return ProviderOutput(providerId=profile.providerId, role=role, status="success", answer="Low confidence answer", confidence=0.4, suggestedStatus="WAIT", riskFlags=["low_confidence"], assumptions=["Insufficient data"], evidenceRefs=["mock_evidence_low"])
        return ProviderOutput(providerId=profile.providerId, role=role, status="success", answer="Mock success answer for: " + task_request.input, confidence=0.9, suggestedStatus="APPROVE", assumptions=["Standard operation"], riskFlags=[], evidenceRefs=["mock_evidence_1"])

    def normalize_output(self, raw_output: Dict[str, Any], profile: ProviderProfile) -> ProviderOutput:
        return ProviderOutput(**raw_output)

    def get_capabilities(self, profile: ProviderProfile) -> list:
        return list(profile.capabilities)

    def redact_secrets(self, data: Dict[str, Any]) -> Dict[str, Any]:
        return self.redaction.redact_dict(data)
