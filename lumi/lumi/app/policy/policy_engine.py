import uuid
from typing import Optional
from lumi.app.schemas.policy import PolicyCheckRequest, PolicyCheckResult
from lumi.app.schemas.actions import ActionDefinition
from lumi.app.schemas.decision import StructuredDecision
from lumi.app.policy.policy_registry import PolicyRegistry
from lumi.app.policy.limits import LimitsChecker
from lumi.app.providers.redaction import RedactionUtil


class PolicyEngine:
    def __init__(self, policy_registry: PolicyRegistry, limits_checker: LimitsChecker, audit_log=None, redaction: RedactionUtil | None = None):
        self.policy_registry = policy_registry
        self.limits_checker = limits_checker
        self.audit_log = audit_log
        self.redaction = redaction or RedactionUtil()

    def check_action(self, check_request: PolicyCheckRequest, action_definition: Optional[ActionDefinition] = None, decision: Optional[StructuredDecision] = None, action_input: Optional[dict] = None) -> PolicyCheckResult:
        policy_check_id = str(uuid.uuid4())
        if self.audit_log:
            self.audit_log.add_entry("policy_check_started", task_id=check_request.taskId, summary=f"Policy check started for {check_request.actionId}", details={"requestedMode": check_request.requestedMode, "riskLevel": check_request.riskLevel})

        matched: list[str] = []
        blocked_by: list[str] = []
        reasons: list[str] = []
        approval_required = False
        dry_run_only = False
        action_allowed = False
        status = "UNKNOWN"
        required_next_step = None

        contains_secret = self._contains_secret(action_input or {})
        if contains_secret:
            check_request.metadata["containsSecret"] = True

        limit_issues = self.limits_checker.check_limits(check_request, action_definition, self.policy_registry.list_limits())
        for issue in limit_issues:
            blocked_by.append(issue["limitId"])
            reasons.append(issue["reason"])

        def add_rule(rule_id: str, block: bool = False, approve: bool = False):
            rule = self.policy_registry.get_rule(rule_id)
            if rule and rule.enabled:
                matched.append(rule.ruleId)
                reasons.append(rule.reason)
                if block:
                    blocked_by.append(rule.ruleId)
                if approve:
                    nonlocal approval_required
                    approval_required = True

        # Fail-closed hard blockers.
        if action_definition is None:
            add_rule("unknown_action_block", block=True)
        elif not action_definition.enabled:
            add_rule("disabled_action_block", block=True)
        if contains_secret:
            add_rule("no_raw_secret_in_action_input", block=True)
        if action_definition and self._missing_required_fields(action_definition, action_input or {}):
            add_rule("missing_required_context_blocks", block=True)

        decision_status = decision.status if decision else None
        if decision:
            fallback_used = bool(decision.metadata.get("fallbackUsed") or decision.metadata.get("routePlan", {}).get("fallbackUsed"))
            if fallback_used and check_request.requestedMode == "execute":
                add_rule("fallback_route_cannot_execute", block=True)
            if decision_status == "SAFE_DEFAULT":
                add_rule("safe_default_decision_blocks_action", block=True)
            elif decision_status == "REJECT":
                add_rule("rejected_decision_blocks_action", block=True)
            elif decision_status == "WAIT" and check_request.requestedMode in {"dry_run", "execute"}:
                add_rule("wait_decision_blocks_execution", block=True)
            elif decision_status == "ASK_USER":
                add_rule("ask_user_decision_requires_approval", approve=True)
            elif decision_status == "APPROVE":
                add_rule("approve_decision_still_checks_policy")

        if action_definition:
            if action_definition.riskLevel == "critical":
                add_rule("critical_action_requires_approval", approve=True)
            elif action_definition.riskLevel == "high":
                add_rule("high_risk_requires_approval", approve=True)
            if action_definition.requiresApproval:
                approval_required = True
                reasons.append("Action definition requires approval.")
            if check_request.requestedMode not in action_definition.allowedModes:
                blocked_by.append("requested_mode_not_allowed")
                reasons.append(f"Requested mode {check_request.requestedMode} is not allowed for this action.")

        if check_request.requestedMode == "execute":
            add_rule("execute_mode_blocked_by_default", approve=True)
            # v0.5 has no real execution. Keep actionAllowed false even with approval required.
            action_allowed = False
        elif check_request.requestedMode == "dry_run":
            if action_definition and action_definition.supportsDryRun and not blocked_by:
                add_rule("dry_run_allowed_if_supported")
                action_allowed = not approval_required
                dry_run_only = True
            else:
                blocked_by.append("dry_run_not_supported")
                reasons.append("Dry-run is not supported for this action.")
        elif check_request.requestedMode == "proposal":
            if action_definition and action_definition.enabled and not blocked_by:
                add_rule("proposal_mode_allowed_for_registered_action")
                action_allowed = False
        else:
            blocked_by.append("invalid_requested_mode")
            reasons.append("Invalid requested mode.")

        if blocked_by:
            status = "BLOCK"
            action_allowed = False
            approval_required = False
            required_next_step = "review_blocked_action"
        elif approval_required:
            status = "REQUIRE_APPROVAL"
            action_allowed = False
            required_next_step = "await_approval"
        elif check_request.requestedMode == "dry_run" and action_allowed:
            status = "ALLOW"
        elif check_request.requestedMode == "proposal" and action_definition:
            status = "ALLOW"
            action_allowed = False
            required_next_step = "review_proposal"
        else:
            status = "BLOCK"
            blocked_by.append("fail_closed_default")
            reasons.append("Fail-closed default: no allow rule matched.")
            required_next_step = "review_blocked_action"

        result = PolicyCheckResult(policyCheckId=policy_check_id, status=status, actionAllowed=action_allowed, approvalRequired=approval_required, dryRunOnly=dry_run_only, riskLevel=action_definition.riskLevel if action_definition else check_request.riskLevel, matchedRules=matched, blockedBy=blocked_by, reasons=list(dict.fromkeys(reasons)), requiredNextStep=required_next_step, metadata={"requestedMode": check_request.requestedMode, "containsSecret": contains_secret})
        self._audit_result(result, check_request)
        return result

    def _missing_required_fields(self, action_definition: ActionDefinition, action_input: dict) -> bool:
        required = action_definition.inputSchema.get("required", []) if action_definition.inputSchema else []
        return any(field not in action_input for field in required)

    def _contains_secret(self, action_input: dict) -> bool:
        if not action_input:
            return False
        text = str(action_input).lower()
        return any(marker in text for marker in ["api_key", "apikey", "secret", "token", "password", "bearer", "authorization", "sk-"])

    def _audit_result(self, result: PolicyCheckResult, check_request: PolicyCheckRequest):
        if not self.audit_log:
            return
        self.audit_log.add_entry("policy_check_completed", task_id=check_request.taskId, summary=f"Policy check completed: {result.status}", details={"result": result.model_dump()})
        if result.status == "BLOCK":
            self.audit_log.add_entry("policy_blocked_action", task_id=check_request.taskId, summary="Action blocked by policy", details={"blockedBy": result.blockedBy, "reasons": result.reasons})
        if result.approvalRequired:
            self.audit_log.add_entry("policy_required_approval", task_id=check_request.taskId, summary="Policy requires approval", details={"reasons": result.reasons})
