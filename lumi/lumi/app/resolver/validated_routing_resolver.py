import uuid
from typing import List
from lumi.app.schemas.task import TaskRequest
from lumi.app.schemas.decision import StructuredDecision
from lumi.app.schemas.provider import ProviderOutput
from lumi.app.conflict.conflict_detector import ConflictDetector
from lumi.app.conflict.deterministic_resolver import DeterministicResolver


class ValidatedRoutingResolver:
    def __init__(self, runtime):
        self.runtime = runtime
        self.conflict_detector = ConflictDetector()
        self.deterministic_resolver = DeterministicResolver()

    def resolve(self, task_request: TaskRequest) -> StructuredDecision:
        task_id = task_request.taskId or str(uuid.uuid4())
        task_request.taskId = task_id
        classification = self.runtime.classify_task(task_request)
        self.runtime.audit_log.add_entry("task_classified", task_id=task_id, summary=f"Task classified as: {classification.taskClass}", details={"classification": classification.model_dump()})
        requirements = self.runtime.task_requirements_builder.build(classification)
        self.runtime.audit_log.add_entry("task_requirements_built", task_id=task_id, summary=f"Requirements built for {classification.taskClass}", details={"requirements": requirements.model_dump()})
        route_plan = self.runtime.build_route(task_request, classification=classification, requirements=requirements)
        if route_plan.routeStatus in {"NO_ROUTE", "BLOCKED"}:
            no_enabled = len(self.runtime.registry.list_enabled_providers()) == 0
            return self._process_requested_action(StructuredDecision(
                decisionId=str(uuid.uuid4()), taskId=task_id, status="WAIT", actionAllowed=False, confidence=0.0, riskLevel=classification.riskLevel,
                winningRule="no_enabled_providers" if no_enabled else "no_route_available",
                summary=f"No route available: {route_plan.reason}", requiredNextStep="register_provider" if no_enabled else "register_provider_with_required_capabilities",
                errors=["no_enabled_providers" if no_enabled else route_plan.reason],
                metadata={"routePlan": route_plan.model_dump(), "taskClassification": classification.model_dump(), "taskRequirements": requirements.model_dump(), "routingWarnings": route_plan.warnings, "validationPipeline": {"status": "no_outputs", "reason": "no_route"}, "validationSummary": "No outputs to validate"},
            ), task_request)
        raw_outputs: list[ProviderOutput] = []
        provider_profiles = []
        errors: list[str] = []
        for provider_id in route_plan.selectedProviders:
            try:
                profile = self.runtime.registry.get_provider(provider_id)
                provider_profiles.append(profile)
                adapter = self.runtime.get_adapter(profile)
                output = adapter.invoke(task_request, profile)
                raw_outputs.append(output)
                self.runtime.audit_log.add_entry("provider_invoked", task_id=task_id, provider_id=provider_id, summary=f"Provider {provider_id} invoked with role {output.role}, status: {output.status}")
            except Exception as exc:
                errors.append(f"Provider {provider_id} failed: {exc}")
                self.runtime.audit_log.add_entry("error_recorded", task_id=task_id, provider_id=provider_id, status="error", summary=f"Provider {provider_id} invocation failed: {exc}")
        validation_result = self.runtime.validation_pipeline.validate_outputs(raw_outputs, task_request, provider_profiles, requirements, route_plan)
        accepted_outputs = [r.normalizedOutput for r in validation_result.results if not r.rejected and r.normalizedOutput is not None]
        rejected_outputs = [r.normalizedOutput for r in validation_result.results if r.rejected and r.normalizedOutput is not None]
        if not accepted_outputs and rejected_outputs:
            reasons = [r.rejectionReason or "rejected" for r in validation_result.results if r.rejected]
            return self._process_requested_action(StructuredDecision(decisionId=str(uuid.uuid4()), taskId=task_id, status="SAFE_DEFAULT", actionAllowed=False, confidence=0.0, riskLevel="high", winningRule="all_outputs_rejected_by_validation", summary="All provider outputs rejected by validation", requiredNextStep="review_provider_outputs", errors=reasons + errors, providerOutputsCount=len(raw_outputs), validProviderOutputsCount=0, metadata={"routePlan": route_plan.model_dump(), "taskClassification": classification.model_dump(), "taskRequirements": requirements.model_dump(), "validationPipeline": validation_result.model_dump(), "validationSummary": validation_result.summary, "acceptedProviderIds": [], "rejectedProviderIds": validation_result.rejectedProviderIds}), task_request)
        if not accepted_outputs:
            return self._process_requested_action(StructuredDecision(decisionId=str(uuid.uuid4()), taskId=task_id, status="SAFE_DEFAULT", actionAllowed=False, confidence=0.0, riskLevel="high", winningRule="no_valid_outputs", summary="No valid outputs from providers", requiredNextStep="review_providers", errors=errors, providerOutputsCount=len(raw_outputs), validProviderOutputsCount=0, metadata={"routePlan": route_plan.model_dump(), "taskClassification": classification.model_dump(), "taskRequirements": requirements.model_dump(), "validationPipeline": validation_result.model_dump(), "validationSummary": validation_result.summary, "acceptedProviderIds": [], "rejectedProviderIds": validation_result.rejectedProviderIds}), task_request)
        conflict_report = self.conflict_detector.analyze(task_id, accepted_outputs, validation_result)
        self.runtime.audit_log.add_entry(
            "conflict_analysis_completed",
            task_id=task_id,
            summary=f"Conflict analysis: {conflict_report.primaryConflictType}, detected={conflict_report.conflictDetected}",
            details={"conflictReport": conflict_report.model_dump()},
        )
        for finding in conflict_report.findings:
            self.runtime.audit_log.add_entry(
                "conflict_detected",
                task_id=task_id,
                summary=f"{finding.conflictType}: {finding.reason}",
                details=finding.model_dump(),
            )

        resolution = self.deterministic_resolver.resolve(task_id, accepted_outputs, validation_result, conflict_report, route_plan)
        self.runtime.audit_log.add_entry(
            "deterministic_resolution_completed",
            task_id=task_id,
            summary=f"Deterministic resolution: {resolution.status} by {resolution.winningRule}",
            details={"resolution": resolution.model_dump()},
        )
        decision = StructuredDecision(
            decisionId=str(uuid.uuid4()),
            taskId=task_id,
            status=resolution.status,
            actionAllowed=resolution.actionAllowed,
            confidence=resolution.confidence,
            riskLevel=resolution.riskLevel,
            conflictDetected=resolution.conflictDetected,
            conflictType=None if resolution.conflictType == "NONE" else resolution.conflictType,
            winningRule=resolution.winningRule,
            summary=resolution.summary,
            requiredNextStep=resolution.requiredNextStep,
            userApprovalRequired=resolution.userApprovalRequired,
            auditRequired=True,
            providerOutputsCount=len(validation_result.results),
            validProviderOutputsCount=len([o for o in accepted_outputs if o.status == "success"]),
            errors=errors,
            metadata={
                "routePlan": route_plan.model_dump(),
                "taskClassification": classification.model_dump(),
                "taskRequirements": requirements.model_dump(),
                "routingWarnings": route_plan.warnings,
                "selectedProviders": list(route_plan.selectedProviders),
                "validationPipeline": validation_result.model_dump(),
                "validationSummary": validation_result.summary,
                "acceptedProviderIds": validation_result.acceptedProviderIds,
                "rejectedProviderIds": validation_result.rejectedProviderIds,
                "conflictReport": conflict_report.model_dump(),
                "deterministicResolution": resolution.model_dump(),
            },
        )
        # Critical secret/forbidden content should already reject all offending outputs. If any such issue appears, fail closed.
        if any(any("forbidden" in issue.code.lower() or "secret" in issue.code.lower() for issue in r.issues) for r in validation_result.results):
            decision.status = "SAFE_DEFAULT"
            decision.actionAllowed = False
            decision.riskLevel = "high"
            decision.winningRule = "unsafe_content_detected"
            decision.summary = "Unsafe content detected in provider output, defaulting to safe"
        return self._process_requested_action(decision, task_request)


    def _process_requested_action(self, decision: StructuredDecision, task_request: TaskRequest) -> StructuredDecision:
        requested_action = (task_request.metadata or {}).get("requestedAction")
        if not requested_action:
            return decision
        action_id = requested_action.get("actionId")
        if not action_id:
            return decision
        mode = requested_action.get("mode", "proposal")
        action_input = requested_action.get("input", {})
        try:
            gateway_result = self.runtime.action_gateway.propose_action(
                action_id=action_id,
                task_request=task_request,
                decision=decision,
                proposed_input=action_input,
                requested_mode=mode,
            )
            decision.metadata["actionGatewayResult"] = gateway_result.model_dump()
            decision.metadata["policyCheck"] = gateway_result.policyCheck.model_dump() if gateway_result.policyCheck else None
            if gateway_result.approvalPrompt:
                decision.metadata["approvalPrompt"] = gateway_result.approvalPrompt.model_dump()
                decision.metadata["approvalRequired"] = True
                if not decision.requiredNextStep:
                    decision.requiredNextStep = "await_approval"
            if gateway_result.status == "blocked":
                decision.actionAllowed = False
                if decision.status == "APPROVE":
                    decision.status = "WAIT"
                    decision.winningRule = "action_blocked_by_policy"
                    decision.summary += " (Requested action was blocked by policy.)"
                    decision.requiredNextStep = "review_blocked_action"
        except Exception as exc:
            decision.metadata["actionGatewayError"] = self.runtime.redaction.redact_secret_like(str(exc))
            decision.actionAllowed = False
        return decision

    def _build_decision(self, task_id: str, accepted_outputs: List[ProviderOutput], errors: List[str], route_plan, classification, validation_result) -> StructuredDecision:
        effective_outputs: list[ProviderOutput] = []
        for output in accepted_outputs:
            for vr in validation_result.results:
                if vr.providerId == output.providerId:
                    if vr.validationStatus == "degraded":
                        output.confidence = min(output.confidence, vr.validationScore)
                    break
            effective_outputs.append(output)
        valid = [o for o in effective_outputs if o.status == "success"]
        avg = round(sum(o.confidence for o in valid) / len(valid), 4) if valid else 0.0
        suggested = {o.suggestedStatus for o in valid if o.suggestedStatus}
        if not valid:
            status, allowed, risk, rule, summary, next_step = "SAFE_DEFAULT", False, "high", "no_valid_outputs", "No valid provider outputs, defaulting to safe", "review_providers"
        elif "REJECT" in suggested:
            status, allowed, risk, rule, summary, next_step = "REJECT", False, "high", "provider_reject_suggestion", "At least one selected provider recommended reject", "review_rejection_reason"
        elif avg >= 0.75 and "APPROVE" in suggested:
            status, allowed, risk, rule, summary, next_step = "APPROVE", True, "low", "high_confidence_approve", f"Validated resolver approved with {len(valid)} valid outputs", None
        elif route_plan.fallbackUsed:
            status, allowed, risk, rule, summary, next_step = "WAIT", False, "medium", "fallback_provider_used", "Fallback provider used; waiting for stronger route", "register_primary_provider"
        else:
            status, allowed, risk, rule, summary, next_step = "WAIT", False, "medium", "low_confidence_wait", "Confidence below threshold or no approval suggestion", "human_review"
        return StructuredDecision(decisionId=str(uuid.uuid4()), taskId=task_id, status=status, actionAllowed=allowed, confidence=avg, riskLevel=risk, winningRule=rule, summary=summary, requiredNextStep=next_step, providerOutputsCount=len(validation_result.results), validProviderOutputsCount=len(valid), errors=errors, metadata={"routeStatus": route_plan.routeStatus, "strategy": route_plan.strategy, "fallbackUsed": route_plan.fallbackUsed, "validationStatus": validation_result.overallValidationStatus})
