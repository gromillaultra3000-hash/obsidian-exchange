import uuid
from lumi.app.schemas.sandbox import ApplyPreparationRequest, ApplyPreparationPackage
from lumi.app.schemas.patch_planner import PatchPlanResult, DiffPreview, RollbackMetadata
from lumi.app.schemas.sandbox import SandboxTestRunResult

class ApplyPreparationBuilder:
    def __init__(self, action_gateway=None, audit_log=None):
        self.action_gateway = action_gateway
        self.audit_log = audit_log

    def prepare_apply_package(self, request: ApplyPreparationRequest, patch_plan_result: PatchPlanResult | None = None, diff_preview: DiffPreview | None = None, test_result: SandboxTestRunResult | None = None, rollback_metadata: RollbackMetadata | None = None) -> ApplyPreparationPackage:
        pid = str(uuid.uuid4())
        files: list[str] = []
        risk = "unknown"
        if patch_plan_result and patch_plan_result.patchProposal:
            files = list(patch_plan_result.patchProposal.targetFiles)
            risk = patch_plan_result.patchProposal.riskLevel
        elif diff_preview:
            files = [fd.path for fd in diff_preview.fileDiffs]
        status = "blocked" if not files else "ready_for_review"
        package = ApplyPreparationPackage(applyPackageId=pid, projectId=request.projectId, status=status, patchPlanResultId=request.patchPlanResultId, patchProposalId=request.patchProposalId, diffPreviewId=request.diffPreviewId, testRunResultId=request.testRunResultId, rollbackMetadataId=request.rollbackMetadataId, summary=f"Approval-gated apply preparation for {request.projectId}", filesAffected=files, riskLevel=risk, approvalRequired=True, canApplyToHost=False, applyBlockedReason="host_project_apply_disabled_in_v1_0", rollbackAvailable=rollback_metadata is not None, metadata={"testPassed": test_result.passed if test_result else False})
        if status == "blocked":
            if self.audit_log:
                self.audit_log.add_entry("apply_preparation_blocked", summary=f"Apply preparation blocked for {request.projectId}: no files affected")
            return package
        if self.action_gateway:
            try:
                result = self.action_gateway.propose_action("prepare_apply_package", proposed_input={"projectId": request.projectId, "applyPackageId": pid, "filesAffected": files, "riskLevel": risk}, requested_mode="proposal")
                package.actionGatewayResult = result.model_dump()
                if result.approvalPrompt:
                    package.approvalPrompt = result.approvalPrompt.model_dump()
                    package.status = "approval_required"
            except Exception:
                pass
        if self.audit_log:
            self.audit_log.add_entry("apply_preparation_package_created", summary=f"Apply preparation package {pid} created", details={"projectId": request.projectId, "filesAffected": len(files), "canApplyToHost": False})
            self.audit_log.add_entry("apply_preparation_requires_approval", summary=f"Apply preparation requires approval for {request.projectId}")
        return package
