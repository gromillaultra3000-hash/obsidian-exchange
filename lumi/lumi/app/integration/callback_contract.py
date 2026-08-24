import uuid
from typing import Optional
from lumi.app.schemas.integration import DecisionCallbackConfig, DecisionCallbackPayload, DecisionCallbackResult
from lumi.app.schemas.decision import StructuredDecision
from lumi.app.providers.redaction import RedactionUtil


class DecisionCallbackService:
    def __init__(self, audit_log=None, redaction: RedactionUtil | None = None):
        self._callbacks: dict[str, DecisionCallbackConfig] = {}
        self.audit_log = audit_log
        self.redaction = redaction or RedactionUtil()

    def register_callback(self, config: DecisionCallbackConfig) -> DecisionCallbackConfig:
        if config.callbackId in self._callbacks:
            raise ValueError(f"Callback {config.callbackId} already exists")
        safe = config.model_copy(deep=True)
        safe.metadata = self.redaction.redact_dict(config.metadata)
        if safe.mode == "http":
            # Contract exists, but outbound HTTP is not implemented in v0.7.
            safe.mode = "mock"
            safe.url = None
        else:
            safe.url = None
        self._callbacks[safe.callbackId] = safe
        if self.audit_log:
            self.audit_log.add_entry("decision_callback_registered", summary=f"Callback {safe.callbackId} registered", details={"hostAppId": safe.hostAppId, "mode": safe.mode})
        return safe

    def list_callbacks(self, host_app_id: Optional[str] = None):
        items = list(self._callbacks.values())
        return [c for c in items if c.hostAppId == host_app_id] if host_app_id else items

    def build_callback_payload(self, decision: StructuredDecision, host_app_id: str, callback_id: str) -> DecisionCallbackPayload:
        metadata = self.redaction.redact_dict(decision.metadata or {})
        action_result = metadata.get("actionGatewayResult", {})
        approval_prompt = metadata.get("approvalPrompt", {})
        payload = DecisionCallbackPayload(
            callbackId=callback_id,
            hostAppId=host_app_id,
            decisionId=decision.decisionId,
            taskId=decision.taskId,
            status=decision.status,
            summary=self.redaction.redact_secret_like(decision.summary or ""),
            actionGatewayStatus=action_result.get("status") if isinstance(action_result, dict) else None,
            approvalPromptId=approval_prompt.get("promptId") if isinstance(approval_prompt, dict) else None,
            metadata=metadata,
        )
        if self.audit_log:
            self.audit_log.add_entry("decision_callback_payload_created", decision_id=decision.decisionId, summary=f"Callback payload created for {callback_id}")
        return payload

    def deliver_callback(self, payload: DecisionCallbackPayload, mode: str = "mock") -> DecisionCallbackResult:
        result_id = str(uuid.uuid4())
        callback = self._callbacks.get(payload.callbackId)
        if not callback or not callback.enabled:
            if self.audit_log:
                self.audit_log.add_entry("decision_callback_blocked", summary=f"Callback {payload.callbackId} blocked")
            return DecisionCallbackResult(callbackResultId=result_id, callbackId=payload.callbackId, delivered=False, mode="none", status="blocked", errors=["Callback not found or disabled"])
        if mode == "http" or callback.mode == "http":
            if self.audit_log:
                self.audit_log.add_entry("decision_callback_blocked", summary="HTTP callback delivery blocked in v0.7")
            return DecisionCallbackResult(callbackResultId=result_id, callbackId=payload.callbackId, delivered=False, mode="http", status="blocked", errors=["HTTP callback delivery is not implemented in v0.7"])
        if self.audit_log:
            self.audit_log.add_entry("decision_callback_mock_delivered", summary=f"Callback {payload.callbackId} mock delivered")
        return DecisionCallbackResult(callbackResultId=result_id, callbackId=payload.callbackId, delivered=True, mode="mock", status="delivered_mock")

    def clear_for_tests(self):
        self._callbacks.clear()
