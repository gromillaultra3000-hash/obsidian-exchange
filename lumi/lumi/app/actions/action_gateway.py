import uuid
from typing import Optional
from lumi.app.schemas.actions import ActionGatewayResult
from lumi.app.schemas.task import TaskRequest
from lumi.app.schemas.decision import StructuredDecision
from lumi.app.schemas.policy import PolicyCheckRequest, PolicyCheckResult
from lumi.app.actions.action_registry import ActionRegistry
from lumi.app.policy.policy_engine import PolicyEngine
from lumi.app.actions.action_proposal import ActionProposalBuilder
from lumi.app.actions.approval_prompt import ApprovalPromptManager
from lumi.app.providers.redaction import RedactionUtil


class ActionGateway:
    def __init__(self, action_registry: ActionRegistry, policy_engine: PolicyEngine, proposal_builder: ActionProposalBuilder, approval_manager: ApprovalPromptManager, audit_log=None, redaction: RedactionUtil | None = None):
        self.action_registry = action_registry
        self.policy_engine = policy_engine
        self.proposal_builder = proposal_builder
        self.approval_manager = approval_manager
        self.audit_log = audit_log
        self.redaction = redaction or RedactionUtil()

    def propose_action(self, action_id: str, task_request: Optional[TaskRequest] = None, decision: Optional[StructuredDecision] = None, proposed_input: Optional[dict] = None, requested_mode: str = "proposal") -> ActionGatewayResult:
        gateway_id = str(uuid.uuid4())
        task_id = task_request.taskId if task_request else None
        if self.audit_log:
            self.audit_log.add_entry("action_gateway_checked", task_id=task_id, summary=f"Action gateway check for {action_id}", details={"mode": requested_mode})
        action_def = self.action_registry.get_action(action_id)
        proposal = self.proposal_builder.create_proposal(action_id, task_request, decision, proposed_input, requested_mode)
        policy_check = self._check_policy(action_id, task_request, decision, proposed_input, requested_mode)
        proposal.policyCheck = policy_check
        proposal.actionAllowed = policy_check.actionAllowed
        proposal.approvalRequired = policy_check.approvalRequired
        proposal.blockedReasons = list(policy_check.reasons)

        if self.audit_log:
            self.audit_log.add_entry("action_proposal_created", task_id=task_id, summary=f"Action proposal created for {action_id}", details={"proposal": proposal.model_dump()})

        if policy_check.status == "BLOCK":
            proposal.status = "blocked"
            proposal.requiredNextStep = policy_check.requiredNextStep or "review_blocked_action"
            if self.audit_log:
                self.audit_log.add_entry("action_blocked", task_id=task_id, summary=f"Action {action_id} blocked", details={"reasons": policy_check.reasons})
            return ActionGatewayResult(gatewayResultId=gateway_id, proposalId=proposal.proposalId, actionId=action_id, status="blocked", actionAllowed=False, approvalRequired=False, policyCheck=policy_check, errors=policy_check.reasons, metadata={"proposedInput": proposal.proposedInput})

        if policy_check.status == "REQUIRE_APPROVAL":
            proposal.status = "approval_required"
            proposal.requiredNextStep = "await_approval"
            prompt = self.approval_manager.build_prompt(proposal, policy_check)
            if self.audit_log:
                self.audit_log.add_entry("action_approval_required", task_id=task_id, summary=f"Action {action_id} requires approval")
                if requested_mode == "execute":
                    self.audit_log.add_entry("execute_blocked_by_default", task_id=task_id, summary=f"Execute mode blocked for {action_id}")
            return ActionGatewayResult(gatewayResultId=gateway_id, proposalId=proposal.proposalId, actionId=action_id, status="approval_required", actionAllowed=False, approvalRequired=True, approvalPrompt=prompt, policyCheck=policy_check, metadata={"proposedInput": proposal.proposedInput})

        if policy_check.status == "ALLOW":
            if requested_mode == "dry_run" and action_def and action_def.supportsDryRun:
                proposal.status = "dry_run_ready"
                proposal.actionAllowed = True
                if self.audit_log:
                    self.audit_log.add_entry("dry_run_ready", task_id=task_id, summary=f"Dry-run ready for {action_id}")
                return ActionGatewayResult(gatewayResultId=gateway_id, proposalId=proposal.proposalId, actionId=action_id, status="dry_run_ready", actionAllowed=True, approvalRequired=False, policyCheck=policy_check, result={"dryRunReady": True, "realSideEffects": False}, metadata={"proposedInput": proposal.proposedInput})
            # proposal mode is allowed but does not allow real side effects
            return ActionGatewayResult(gatewayResultId=gateway_id, proposalId=proposal.proposalId, actionId=action_id, status="proposal_created", actionAllowed=False, approvalRequired=False, policyCheck=policy_check, metadata={"proposedInput": proposal.proposedInput})

        return ActionGatewayResult(gatewayResultId=gateway_id, proposalId=proposal.proposalId, actionId=action_id, status="blocked", actionAllowed=False, approvalRequired=False, policyCheck=policy_check, errors=["Fail-closed action gateway default"], metadata={"proposedInput": proposal.proposedInput})

    def check_action_policy(self, action_id: str, task_request: Optional[TaskRequest] = None, decision: Optional[StructuredDecision] = None, proposed_input: Optional[dict] = None, requested_mode: str = "proposal") -> PolicyCheckResult:
        return self._check_policy(action_id, task_request, decision, proposed_input, requested_mode)

    def _check_policy(self, action_id: str, task_request: Optional[TaskRequest], decision: Optional[StructuredDecision], proposed_input: Optional[dict], requested_mode: str) -> PolicyCheckResult:
        action_def = self.action_registry.get_action(action_id)
        policy_request = PolicyCheckRequest(taskId=task_request.taskId if task_request else None, decisionId=decision.decisionId if decision else None, actionId=action_id, hostAppId=action_def.hostAppId if action_def else None, riskLevel=action_def.riskLevel if action_def else "unknown", requestedMode=requested_mode, context={"supportsDryRun": action_def.supportsDryRun if action_def else False, "supportsRollback": action_def.supportsRollback if action_def else False}, metadata={"containsSecret": self._contains_secret(proposed_input or {})})
        return self.policy_engine.check_action(policy_request, action_def, decision, proposed_input or {})

    def _contains_secret(self, action_input: dict) -> bool:
        if not action_input:
            return False
        text = str(action_input).lower()
        return any(marker in text for marker in ["api_key", "apikey", "secret", "token", "password", "bearer", "authorization", "sk-"])
