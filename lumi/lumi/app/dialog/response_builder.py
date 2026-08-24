import uuid
from typing import Optional, List
from lumi.app.schemas.dialog import DialogResponse


class DialogResponseBuilder:
    def build_from_decision(self, session_id: str, message_id: str, decision, explanation=None) -> DialogResponse:
        metadata = decision.metadata or {}
        route = metadata.get("routePlan", {}) if isinstance(metadata.get("routePlan"), dict) else {}
        validation = metadata.get("validationPipeline", {}) if isinstance(metadata.get("validationPipeline"), dict) else {}
        action_result = metadata.get("actionGatewayResult", {}) if isinstance(metadata.get("actionGatewayResult"), dict) else {}
        approval = metadata.get("approvalPrompt") if isinstance(metadata.get("approvalPrompt"), dict) else None
        short = explanation.shortAnswer if explanation else decision.summary
        decision_summary = explanation.userFacingSummary if explanation else decision.summary
        text = [short or decision.summary, f"Status: {decision.status}", f"Confidence: {decision.confidence:.0%}", f"Risk: {decision.riskLevel}"]
        if decision.requiredNextStep:
            text.append(f"Next step: {decision.requiredNextStep}")
        if approval:
            text.append("Approval prompt is ready. Use approve/reject after review.")
        return DialogResponse(
            responseId=str(uuid.uuid4()), sessionId=session_id, messageId=message_id, commandType="resolve_task", text="\n".join(text), decisionId=decision.decisionId, taskId=decision.taskId, status=decision.status, shortAnswer=short or "", decisionSummary=decision_summary, routeSummary=self._route(route), validationSummary=self._validation(validation, metadata), conflictSummary=self._conflict(decision), policySummary=self._policy(action_result), actionSummary=self._action(action_result), approvalPrompt=approval, requiredNextStep=decision.requiredNextStep, metadata={"decisionId": decision.decisionId})

    def build_status_response(self, session_id: str, message_id: str, runtime_status) -> DialogResponse:
        text = f"Lumi runtime status\nVersion: {runtime_status.version}\nStatus: {runtime_status.status}\nProviders: {runtime_status.enabledProvidersCount}/{runtime_status.providersCount}\nActions: {runtime_status.enabledActionsCount}/{runtime_status.actionsCount}\nDecisions: {getattr(runtime_status, 'decisionsCount', 0)}\nDialog sessions: {getattr(runtime_status, 'activeDialogSessionsCount', 0)}/{getattr(runtime_status, 'dialogSessionsCount', 0)}"
        return DialogResponse(responseId=str(uuid.uuid4()), sessionId=session_id, messageId=message_id, commandType="show_status", text=text, shortAnswer=f"Lumi v{runtime_status.version} is running", metadata={"status": runtime_status.model_dump()})

    def build_history_response(self, session_id: str, message_id: str, records: List) -> DialogResponse:
        if not records:
            return DialogResponse(responseId=str(uuid.uuid4()), sessionId=session_id, messageId=message_id, commandType="show_history", text="No previous decisions found.", shortAnswer="No history available", metadata={"recordCount": 0})
        lines = [f"Recent decisions ({len(records)}):"]
        for i, rec in enumerate(records[:5], 1):
            lines.append(f"{i}. [{rec.status}] {rec.summary[:120]} ({rec.confidence:.0%})")
        return DialogResponse(responseId=str(uuid.uuid4()), sessionId=session_id, messageId=message_id, commandType="show_history", text="\n".join(lines), shortAnswer=f"Showing {min(len(records), 5)} recent decisions", metadata={"recordCount": len(records)})

    def build_explanation_response(self, session_id: str, message_id: str, explanation_result) -> DialogResponse:
        exp = explanation_result.explanation
        text = f"{exp.title}\n\n{exp.shortAnswer}\n\n{exp.statusExplanation}\n{exp.confidenceExplanation}"
        if exp.requiredNextStep:
            text += f"\nNext step: {exp.requiredNextStep}"
        return DialogResponse(responseId=str(uuid.uuid4()), sessionId=session_id, messageId=message_id, commandType="explain_decision", text=text, decisionId=exp.decisionId, taskId=exp.taskId, shortAnswer=exp.shortAnswer, decisionSummary=exp.userFacingSummary, requiredNextStep=exp.requiredNextStep, metadata={"explanationId": exp.explanationId})

    def build_text_response(self, session_id: str, message_id: str, command_type: str, text: str, short: str, metadata: dict | None = None, decision_id: str | None = None, task_id: str | None = None) -> DialogResponse:
        return DialogResponse(responseId=str(uuid.uuid4()), sessionId=session_id, messageId=message_id, commandType=command_type, text=text, shortAnswer=short, decisionId=decision_id, taskId=task_id, metadata=metadata or {})

    def _route(self, route):
        if not route: return None
        return f"Route: {route.get('routeStatus', 'unknown')} with {len(route.get('selectedProviders', []))} provider(s)"
    def _validation(self, validation, metadata):
        if not validation: return None
        return f"Validation: {validation.get('overallValidationStatus') or validation.get('status', 'unknown')} ({len(metadata.get('acceptedProviderIds', []))} accepted, {len(metadata.get('rejectedProviderIds', []))} rejected)"
    def _conflict(self, decision):
        return f"Conflict detected: {decision.conflictType}" if decision.conflictDetected else "No conflicts detected"
    def _policy(self, action):
        if not action: return None
        pc = action.get('policyCheck') if isinstance(action, dict) else None
        return f"Policy: {pc.get('status', 'unknown')}" if isinstance(pc, dict) else None
    def _action(self, action):
        if not action: return None
        return f"Action: {action.get('status', 'unknown')}"
