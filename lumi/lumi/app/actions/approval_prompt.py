import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from lumi.app.schemas.actions import ApprovalPrompt, ApprovalDecision, ActionProposal
from lumi.app.schemas.policy import PolicyCheckResult
from lumi.app.providers.redaction import RedactionUtil


class ApprovalPromptManager:
    def __init__(self, audit_log=None, redaction: RedactionUtil | None = None):
        self._prompts: dict[str, ApprovalPrompt] = {}
        self._decisions: dict[str, ApprovalDecision] = {}
        self.audit_log = audit_log
        self.redaction = redaction or RedactionUtil()

    def build_prompt(self, action_proposal: ActionProposal, policy_check: PolicyCheckResult) -> ApprovalPrompt:
        prompt_id = str(uuid.uuid4())
        if policy_check.status == "BLOCK":
            buttons, default_button, status, explicit = ["details", "close"], "close", "cancelled", False
        else:
            buttons, default_button, status, explicit = ["approve", "reject", "details"], "reject", "pending", True
        parts = [
            f"Action: {action_proposal.title}",
            f"Risk Level: {action_proposal.riskLevel.upper()}",
            f"Mode: {action_proposal.requestedMode}",
        ]
        if policy_check.reasons:
            parts.append("Policy: " + "; ".join(policy_check.reasons[:3]))
        if policy_check.requiredNextStep:
            parts.append("Next Step: " + policy_check.requiredNextStep)
        parts.append("Default is reject/close. Explicit approval is required where applicable.")
        prompt = ApprovalPrompt(promptId=prompt_id, proposalId=action_proposal.proposalId, actionId=action_proposal.actionId, decisionId=action_proposal.decisionId, taskId=action_proposal.taskId, title=("Approval Required: " if explicit else "Action Blocked: ") + action_proposal.title, message=self.redaction.redact_secret_like("\n".join(parts)), riskLevel=action_proposal.riskLevel, buttons=buttons, defaultButton=default_button, requiresExplicitApproval=explicit, expiresAt=(datetime.now(timezone.utc) + timedelta(hours=24)).isoformat(), status=status, metadata={"policyStatus": policy_check.status, "policyCheckId": policy_check.policyCheckId})
        self._prompts[prompt_id] = prompt
        if self.audit_log:
            self.audit_log.add_entry("approval_prompt_created", task_id=action_proposal.taskId, summary=f"Approval prompt created for {action_proposal.actionId}", details={"prompt": prompt.model_dump()})
        return prompt

    def record_decision(self, prompt_id: str, decision: str, user_id: Optional[str] = None, reason: Optional[str] = None, metadata: Optional[dict] = None) -> ApprovalDecision | None:
        if prompt_id not in self._prompts:
            return None
        prompt = self._prompts[prompt_id]
        prompt.status = "approved" if decision == "approve" else "rejected" if decision == "reject" else "cancelled"
        approval_decision = ApprovalDecision(promptId=prompt_id, decision=decision, userId=user_id, reason=reason, metadata=metadata or {})
        self._decisions[prompt_id] = approval_decision
        if self.audit_log:
            self.audit_log.add_entry("approval_decision_recorded", summary=f"Approval decision {decision} recorded", details={"promptId": prompt_id, "decision": decision, "userId": user_id})
        return approval_decision

    def get_prompt(self, prompt_id: str) -> ApprovalPrompt | None:
        return self._prompts.get(prompt_id)

    def list_all(self) -> List[ApprovalPrompt]:
        return list(self._prompts.values())

    def list_pending(self) -> List[ApprovalPrompt]:
        return [p for p in self._prompts.values() if p.status == "pending"]

    def clear_for_tests(self):
        self._prompts.clear()
        self._decisions.clear()
