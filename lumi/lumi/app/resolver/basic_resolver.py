import uuid
from lumi.app.schemas.task import TaskRequest
from lumi.app.schemas.decision import StructuredDecision
from lumi.app.providers.mock_adapter import MockProviderAdapter
from lumi.app.providers.redaction import RedactionUtil


class BasicResolver:
    def __init__(self, runtime):
        self.runtime = runtime
        self.redaction = RedactionUtil()

    def resolve(self, task_request: TaskRequest) -> StructuredDecision:
        task_id = task_request.taskId or str(uuid.uuid4())
        enabled_providers = self.runtime.registry.list_enabled_providers()

        if not enabled_providers:
            self.runtime.audit_log.add_entry("no_provider_available", task_id=task_id, summary="No enabled providers available")
            return StructuredDecision(
                decisionId=str(uuid.uuid4()),
                taskId=task_id,
                status="WAIT",
                actionAllowed=False,
                confidence=0.0,
                riskLevel="unknown",
                winningRule="no_enabled_providers",
                summary="No enabled providers available for resolution",
                requiredNextStep="register_provider",
                userApprovalRequired=False,
                errors=["no_enabled_providers"],
            )

        outputs = []
        errors_list = []
        for profile in enabled_providers:
            try:
                adapter = self.runtime.get_adapter(profile)
                validation = adapter.validate_config(profile)
                if not validation.get("valid", False):
                    errors_list.extend(validation.get("errors", []))
                    self.runtime.audit_log.add_entry(
                        "provider_output_validated",
                        task_id=task_id,
                        provider_id=profile.providerId,
                        status="invalid",
                        summary=f"Provider {profile.providerId} config invalid",
                        details=validation,
                    )
                    continue
                output = adapter.invoke(task_request, profile)
                outputs.append(output)
                self.runtime.audit_log.add_entry(
                    "provider_invoked",
                    task_id=task_id,
                    provider_id=profile.providerId,
                    summary=f"Provider {profile.providerId} invoked, status: {output.status}",
                    details={"outputStatus": output.status, "confidence": output.confidence},
                )
                self.runtime.audit_log.add_entry(
                    "provider_output_validated",
                    task_id=task_id,
                    provider_id=profile.providerId,
                    status="ok" if output.status == "success" else output.status,
                    summary=f"Provider output validation status: {output.status}",
                )
            except Exception as exc:  # fail-closed
                errors_list.append(str(exc))
                self.runtime.audit_log.add_entry("error_recorded", task_id=task_id, status="error", summary=str(exc))

        if not outputs:
            return StructuredDecision(
                decisionId=str(uuid.uuid4()),
                taskId=task_id,
                status="SAFE_DEFAULT",
                actionAllowed=False,
                confidence=0.0,
                riskLevel="high",
                winningRule="all_providers_failed",
                summary="All provider invocations failed",
                requiredNextStep="review_providers",
                providerOutputsCount=0,
                validProviderOutputsCount=0,
                errors=errors_list or ["all_providers_failed"],
            )

        return self._build_decision(task_id, outputs, errors_list)

    def _build_decision(self, task_id: str, outputs: list, errors_list: list) -> StructuredDecision:
        decision_id = str(uuid.uuid4())
        valid_outputs = [o for o in outputs if o.status == "success"]
        avg_confidence = sum(o.confidence for o in valid_outputs) / len(valid_outputs) if valid_outputs else 0.0

        if not valid_outputs:
            status = "SAFE_DEFAULT"
            action_allowed = False
            risk_level = "high"
            winning_rule = "no_valid_outputs"
            summary = "No valid provider outputs, defaulting to safe result"
            next_step = "review_providers"
        elif any(o.suggestedStatus == "SAFE_DEFAULT" for o in valid_outputs):
            status = "SAFE_DEFAULT"
            action_allowed = False
            risk_level = "high"
            winning_rule = "provider_requested_safe_default"
            summary = "Provider requested safe default"
            next_step = "review_task_context"
        elif avg_confidence >= 0.75 and any(o.suggestedStatus == "APPROVE" for o in valid_outputs):
            status = "APPROVE"
            action_allowed = True
            risk_level = "low"
            winning_rule = "high_confidence_approve"
            summary = "High confidence approval from providers"
            next_step = None
        elif avg_confidence < 0.75:
            status = "WAIT"
            action_allowed = False
            risk_level = "medium"
            winning_rule = "low_confidence_wait"
            summary = "Confidence below threshold, waiting for review"
            next_step = "human_review"
        else:
            status = "WAIT"
            action_allowed = False
            risk_level = "medium"
            winning_rule = "default_wait"
            summary = "Defaulting to WAIT"
            next_step = "review"

        return StructuredDecision(
            decisionId=decision_id,
            taskId=task_id,
            status=status,
            actionAllowed=action_allowed,
            confidence=round(avg_confidence, 4),
            riskLevel=risk_level,
            winningRule=winning_rule,
            summary=summary,
            requiredNextStep=next_step,
            providerOutputsCount=len(outputs),
            validProviderOutputsCount=len(valid_outputs),
            errors=errors_list,
            metadata={"providerOutputStatuses": [o.status for o in outputs]},
        )
