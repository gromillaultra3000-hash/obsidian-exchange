import uuid
from typing import Optional
from lumi.app.schemas.actions import ActionProposal
from lumi.app.schemas.task import TaskRequest
from lumi.app.schemas.decision import StructuredDecision
from lumi.app.actions.action_registry import ActionRegistry
from lumi.app.providers.redaction import RedactionUtil


class ActionProposalBuilder:
    def __init__(self, action_registry: ActionRegistry, redaction: RedactionUtil | None = None):
        self.action_registry = action_registry
        self.redaction = redaction or RedactionUtil()

    def create_proposal(self, action_id: str, task_request: Optional[TaskRequest] = None, decision: Optional[StructuredDecision] = None, proposed_input: Optional[dict] = None, requested_mode: str = "proposal") -> ActionProposal:
        action_def = self.action_registry.get_action(action_id)
        safe_input = self.redaction.redact_dict(proposed_input or {})
        if not action_def:
            return ActionProposal(proposalId=str(uuid.uuid4()), actionId=action_id, taskId=task_request.taskId if task_request else None, decisionId=decision.decisionId if decision else None, title=f"Unknown Action: {action_id}", summary="Action is not registered in the action registry.", proposedInput=safe_input, riskLevel="unknown", requestedMode=requested_mode, status="blocked", approvalRequired=False, actionAllowed=False, blockedReasons=["Unknown action"], requiredNextStep="register_action")
        return ActionProposal(proposalId=str(uuid.uuid4()), actionId=action_id, taskId=task_request.taskId if task_request else None, decisionId=decision.decisionId if decision else None, hostAppId=action_def.hostAppId, title=action_def.title, summary=f"Proposal for {action_def.title}: {action_def.description}", proposedInput=safe_input, riskLevel=action_def.riskLevel, requestedMode=requested_mode, status="proposal_created", approvalRequired=action_def.requiresApproval or action_def.riskLevel in {"high", "critical"}, actionAllowed=False, requiredNextStep="await_policy_check", metadata={"actionCategory": action_def.category, "supportsDryRun": action_def.supportsDryRun, "supportsRollback": action_def.supportsRollback})
