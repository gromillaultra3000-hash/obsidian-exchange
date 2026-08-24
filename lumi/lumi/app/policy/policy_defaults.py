from lumi.app.schemas.policy import PolicyRule, LimitDefinition


def get_default_policy_rules() -> list[PolicyRule]:
    return [
        PolicyRule(ruleId="unknown_action_block", title="Unknown Action Block", description="Block unregistered actions", priority=100, conditionType="action_exists", condition={"actionExists": False}, effect="BLOCK", reason="Unknown action is blocked by default."),
        PolicyRule(ruleId="disabled_action_block", title="Disabled Action Block", description="Block disabled actions", priority=100, conditionType="action_enabled", condition={"actionEnabled": False}, effect="BLOCK", reason="Disabled action is blocked."),
        PolicyRule(ruleId="critical_action_requires_approval", title="Critical Action Requires Approval", description="Critical actions require explicit approval", priority=90, conditionType="risk_level", condition={"riskLevel": "critical"}, effect="REQUIRE_APPROVAL", reason="Critical risk action requires explicit approval."),
        PolicyRule(ruleId="high_risk_requires_approval", title="High Risk Requires Approval", description="High risk actions require approval", priority=85, conditionType="risk_level", condition={"riskLevel": "high"}, effect="REQUIRE_APPROVAL", reason="High risk action requires approval."),
        PolicyRule(ruleId="execute_mode_blocked_by_default", title="Execute Mode Blocked By Default", description="Execute mode is not allowed without explicit approval", priority=95, conditionType="requested_mode", condition={"requestedMode": "execute"}, effect="REQUIRE_APPROVAL", reason="Execute mode requires explicit approval and has no real side effects in v0.5."),
        PolicyRule(ruleId="dry_run_allowed_if_supported", title="Dry Run Allowed If Supported", description="Dry run is allowed only for actions that support dry run", priority=70, conditionType="dry_run_supported", condition={"supportsDryRun": True}, effect="ALLOW", reason="Dry run is supported and allowed."),
        PolicyRule(ruleId="proposal_mode_allowed_for_registered_action", title="Proposal Mode Allowed", description="Proposal mode is allowed for registered enabled actions", priority=60, conditionType="requested_mode", condition={"requestedMode": "proposal"}, effect="ALLOW", reason="Proposal mode is allowed for registered actions."),
        PolicyRule(ruleId="fallback_route_cannot_execute", title="Fallback Route Cannot Execute", description="Fallback route cannot execute actions", priority=80, conditionType="decision_metadata", condition={"fallbackUsed": True}, effect="BLOCK", reason="Fallback route decisions cannot execute actions."),
        PolicyRule(ruleId="safe_default_decision_blocks_action", title="SAFE_DEFAULT Blocks Action", description="SAFE_DEFAULT decision blocks actions", priority=90, conditionType="decision_status", condition={"decisionStatus": "SAFE_DEFAULT"}, effect="BLOCK", reason="SAFE_DEFAULT decision blocks action."),
        PolicyRule(ruleId="wait_decision_blocks_execution", title="WAIT Decision Blocks Execution", description="WAIT blocks dry-run/execute but can allow proposal", priority=75, conditionType="decision_status", condition={"decisionStatus": "WAIT"}, effect="BLOCK", reason="WAIT decision blocks execution."),
        PolicyRule(ruleId="ask_user_decision_requires_approval", title="ASK_USER Requires Approval", description="ASK_USER requires explicit approval", priority=80, conditionType="decision_status", condition={"decisionStatus": "ASK_USER"}, effect="REQUIRE_APPROVAL", reason="ASK_USER decision requires approval."),
        PolicyRule(ruleId="rejected_decision_blocks_action", title="REJECT Blocks Action", description="REJECT decision blocks actions", priority=90, conditionType="decision_status", condition={"decisionStatus": "REJECT"}, effect="BLOCK", reason="REJECT decision blocks action."),
        PolicyRule(ruleId="approve_decision_still_checks_policy", title="APPROVE Still Checks Policy", description="APPROVE does not bypass policy", priority=50, conditionType="decision_status", condition={"decisionStatus": "APPROVE"}, effect="ALLOW", reason="APPROVE decision allows proposal, but policy still applies."),
        PolicyRule(ruleId="missing_required_context_blocks", title="Missing Required Context Blocks", description="Missing required input fields blocks action", priority=85, conditionType="input_validation", condition={"missingRequiredFields": True}, effect="BLOCK", reason="Required input fields are missing."),
        PolicyRule(ruleId="no_raw_secret_in_action_input", title="No Raw Secret In Action Input", description="Secret-like action input is blocked", priority=100, conditionType="secret_in_input", condition={"containsSecret": True}, effect="BLOCK", reason="Action input contains secret-like content."),
    ]


def get_default_limits() -> list[LimitDefinition]:
    return [
        LimitDefinition(limitId="max_actions_per_task", title="Max Actions Per Task", description="Maximum action proposals per task", limitType="count", value=5, unit="actions"),
        LimitDefinition(limitId="max_high_risk_actions_per_task", title="Max High Risk Actions Per Task", description="Maximum high/critical risk action proposals per task", limitType="count", value=2, unit="actions"),
        LimitDefinition(limitId="allow_execute_mode", title="Allow Execute Mode", description="Whether execute mode is globally allowed", limitType="custom", value=False),
        LimitDefinition(limitId="allow_dry_run_mode", title="Allow Dry Run Mode", description="Whether dry-run mode is globally allowed", limitType="custom", value=True),
        LimitDefinition(limitId="require_approval_for_high_risk", title="Require Approval For High Risk", description="High risk actions need approval", limitType="custom", value=True),
        LimitDefinition(limitId="require_approval_for_critical_risk", title="Require Approval For Critical Risk", description="Critical actions need approval", limitType="custom", value=True),
        LimitDefinition(limitId="allow_unknown_actions", title="Allow Unknown Actions", description="Whether unknown actions are allowed", limitType="custom", value=False),
        LimitDefinition(limitId="allow_secret_like_action_input", title="Allow Secret-Like Action Input", description="Whether action input can contain secrets", limitType="custom", value=False),
    ]
