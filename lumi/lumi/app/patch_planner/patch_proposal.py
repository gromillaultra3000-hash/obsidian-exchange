import uuid
from lumi.app.schemas.patch_planner import PatchRequest, PatchProposal
from lumi.app.providers.redaction import RedactionUtil

class PatchProposalBuilder:
    def __init__(self, action_gateway=None, redaction: RedactionUtil | None = None):
        self.action_gateway = action_gateway
        self.redaction = redaction or RedactionUtil()

    def build_proposal(self, request: PatchRequest, safety_result: dict, action_gateway=None) -> PatchProposal:
        gateway = action_gateway or self.action_gateway
        proposal_id = str(uuid.uuid4())
        risk_level = safety_result.get("riskLevel") or request.riskLevel
        errors = safety_result.get("errors", [])
        if errors:
            status = "blocked"
        elif risk_level in ["high", "critical"]:
            status = "approval_required"
        else:
            status = "planned"
        proposal = PatchProposal(
            patchProposalId=proposal_id, projectId=request.projectId, requestId=request.requestId or str(uuid.uuid4()),
            title=request.title, summary=self.redaction.redact_secret_like(request.summary), status=status, riskLevel=risk_level,
            targetFiles=request.targetFiles, proposedChanges=self.redaction.redact_any(request.requestedChanges),
            canApply=False, applyBlockedReason="real_file_write_disabled_in_v0_9" if not errors else "; ".join(errors),
            metadata={"source": request.source},
        )
        if gateway:
            try:
                result = gateway.propose_action("create_patch_preview", proposed_input={
                    "projectId": request.projectId, "patchProposalId": proposal_id, "title": request.title,
                    "summary": request.summary, "targetFiles": request.targetFiles, "riskLevel": risk_level,
                }, requested_mode="proposal")
                proposal.actionGatewayResult = result.model_dump() if hasattr(result, "model_dump") else result.dict()
                if getattr(result, "approvalPrompt", None):
                    proposal.approvalPrompt = result.approvalPrompt.model_dump() if hasattr(result.approvalPrompt, "model_dump") else result.approvalPrompt.dict()
            except Exception as exc:
                proposal.metadata["actionGatewayNote"] = "create_patch_preview action not registered or unavailable"
        return proposal
