import uuid
from typing import List
from lumi.app.schemas.task import TaskRequest
from lumi.app.schemas.decision import StructuredDecision
from lumi.app.schemas.provider import ProviderOutput


class RoutingResolver:
    def __init__(self, runtime):
        self.runtime = runtime

    def resolve(self, task_request: TaskRequest) -> StructuredDecision:
        task_id = task_request.taskId or str(uuid.uuid4())
        classification = self.runtime.classify_task(task_request)
        self.runtime.audit_log.add_entry("task_classified", task_id=task_id, summary=f"Task classified as: {classification.taskClass}", details={"classification": classification.model_dump()})
        requirements = self.runtime.task_requirements_builder.build(classification)
        self.runtime.audit_log.add_entry("task_requirements_built", task_id=task_id, summary=f"Requirements built for {classification.taskClass}", details={"requirements": requirements.model_dump()})
        route_plan = self.runtime.build_route(task_request, classification=classification, requirements=requirements)
        if route_plan.routeStatus in {"NO_ROUTE", "BLOCKED"}:
            no_enabled = len(self.runtime.registry.list_enabled_providers()) == 0
            return StructuredDecision(
                decisionId=str(uuid.uuid4()),
                taskId=task_id,
                status="WAIT",
                actionAllowed=False,
                confidence=0.0,
                riskLevel=classification.riskLevel,
                winningRule="no_enabled_providers" if no_enabled else "no_route_available",
                summary=f"No route available: {route_plan.reason}",
                requiredNextStep="register_provider" if no_enabled else "register_provider_with_required_capabilities",
                errors=["no_enabled_providers" if no_enabled else route_plan.reason],
                metadata={
                    "routePlan": route_plan.model_dump(),
                    "taskClassification": classification.model_dump(),
                    "taskRequirements": requirements.model_dump(),
                    "routingWarnings": route_plan.warnings,
                },
            )
        outputs: list[ProviderOutput] = []
        errors: list[str] = []
        for provider_id in route_plan.selectedProviders:
            try:
                profile = self.runtime.registry.get_provider(provider_id)
                adapter = self.runtime.get_adapter(profile)
                output = adapter.invoke(task_request, profile)
                outputs.append(output)
                self.runtime.audit_log.add_entry("provider_invoked", task_id=task_id, provider_id=provider_id, summary=f"Provider {provider_id} invoked with role {output.role}, status: {output.status}")
                self.runtime.audit_log.add_entry("provider_output_validated", task_id=task_id, provider_id=provider_id, summary=f"Provider output accepted as {output.status}", details={"status": output.status, "confidence": output.confidence, "role": output.role})
            except Exception as exc:  # fail closed
                errors.append(f"Provider {provider_id} failed: {exc}")
                self.runtime.audit_log.add_entry("error_recorded", task_id=task_id, provider_id=provider_id, status="error", summary=str(exc))
        decision = self._build_decision(task_id, outputs, errors, route_plan, classification)
        decision.metadata.update({
            "routePlan": route_plan.model_dump(),
            "taskClassification": classification.model_dump(),
            "taskRequirements": requirements.model_dump(),
            "routingWarnings": route_plan.warnings,
            "selectedProviders": list(route_plan.selectedProviders),
        })
        return decision

    def _build_decision(self, task_id: str, outputs: List[ProviderOutput], errors: List[str], route_plan, classification) -> StructuredDecision:
        valid = [o for o in outputs if o.status == "success"]
        avg_confidence = round(sum(o.confidence for o in valid) / len(valid), 4) if valid else 0.0
        suggested = {o.suggestedStatus for o in valid if o.suggestedStatus}
        if not valid:
            status, allowed, risk, rule, summary, next_step = "SAFE_DEFAULT", False, "high", "no_valid_outputs", "No valid provider outputs, defaulting to safe", "review_providers"
        elif "REJECT" in suggested:
            status, allowed, risk, rule, summary, next_step = "REJECT", False, "high", "provider_reject_suggestion", "At least one selected provider recommended reject", "review_rejection_reason"
        elif avg_confidence >= 0.75 and "APPROVE" in suggested:
            status, allowed, risk, rule, summary, next_step = "APPROVE", True, "low", "high_confidence_approve", f"Routing resolver approved with {len(valid)} valid outputs", None
        elif route_plan.fallbackUsed:
            status, allowed, risk, rule, summary, next_step = "WAIT", False, "medium", "fallback_provider_used", "Fallback provider used; waiting for stronger route", "register_primary_provider"
        else:
            status, allowed, risk, rule, summary, next_step = "WAIT", False, "medium", "low_confidence_wait", "Confidence below threshold or no approval suggestion", "human_review"
        return StructuredDecision(
            decisionId=str(uuid.uuid4()),
            taskId=task_id,
            status=status,
            actionAllowed=allowed,
            confidence=avg_confidence,
            riskLevel=risk,
            winningRule=rule,
            summary=summary,
            requiredNextStep=next_step,
            providerOutputsCount=len(outputs),
            validProviderOutputsCount=len(valid),
            errors=errors,
            metadata={"routeStatus": route_plan.routeStatus, "strategy": route_plan.strategy, "fallbackUsed": route_plan.fallbackUsed},
        )
