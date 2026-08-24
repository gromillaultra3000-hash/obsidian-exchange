import uuid
from typing import Optional, List
from lumi.app.schemas.patch_planner import PatchRequest, PatchPlanResult, PatchProposal, DiffPreview, TestPlan, TestRunPreview, RollbackMetadata
from lumi.app.schemas.task import TaskRequest

class PatchRuntime:
    def __init__(self, runtime, project_registry, snapshot_store, request_normalizer, safety_guard, proposal_builder, diff_builder, test_plan_builder, test_runner, rollback_builder, action_gateway, audit_log, redaction):
        self.runtime = runtime
        self.project_registry = project_registry
        self.snapshot_store = snapshot_store
        self.request_normalizer = request_normalizer
        self.safety_guard = safety_guard
        self.proposal_builder = proposal_builder
        self.diff_builder = diff_builder
        self.test_plan_builder = test_plan_builder
        self.test_runner = test_runner
        self.rollback_builder = rollback_builder
        self.action_gateway = action_gateway
        self.audit_log = audit_log
        self.redaction = redaction
        self._patch_results: dict[str, PatchPlanResult] = {}
        self._diff_previews: dict[str, DiffPreview] = {}
        self._test_plans: dict[str, TestPlan] = {}
        self._test_run_previews: dict[str, TestRunPreview] = {}
        self._rollback_metadata: dict[str, RollbackMetadata] = {}
        self._patch_proposals: dict[str, PatchProposal] = {}

    def plan_patch(self, request: PatchRequest | dict) -> PatchPlanResult:
        result_id = str(uuid.uuid4())
        normalized = self.request_normalizer.normalize_request(request.model_dump() if hasattr(request, "model_dump") else request)
        if self.audit_log:
            self.audit_log.add_entry("patch_plan_requested", summary=f"Patch plan requested for project {normalized.projectId}", details={"source": normalized.source})
            self.audit_log.add_entry("patch_request_normalized", summary="Patch request normalized", details={"requestId": normalized.requestId, "projectId": normalized.projectId})
        profile = self.project_registry.get_project(normalized.projectId)
        if not profile:
            return self._blocked_result(result_id, normalized.projectId, [f"Project {normalized.projectId} not found"])
        if profile.status == "disabled":
            return self._blocked_result(result_id, normalized.projectId, [f"Project {normalized.projectId} is disabled"])
        snapshots = self.snapshot_store.list_snapshots(normalized.projectId)
        safety = self.safety_guard.validate_patch_request(normalized, profile, snapshots)
        if self.audit_log:
            self.audit_log.add_entry("patch_safety_checked", summary=f"Patch safety checked for {normalized.projectId}", details={"valid": safety.get("valid"), "warnings": safety.get("warnings", [])})
        if not safety.get("valid"):
            if self.audit_log:
                self.audit_log.add_entry("patch_safety_blocked", summary="Patch safety blocked", details={"errors": safety.get("errors", [])})
            return self._blocked_result(result_id, normalized.projectId, safety.get("errors", []), safety.get("warnings", []))
        try:
            proposal = self.proposal_builder.build_proposal(normalized, safety, self.action_gateway)
            self._patch_proposals[proposal.patchProposalId] = proposal
            if self.audit_log:
                self.audit_log.add_entry("patch_proposal_created", summary=f"Patch proposal created: {proposal.patchProposalId}")
            diff_preview = self.diff_builder.build_diff_preview(normalized.projectId, proposal, snapshots)
            self._diff_previews[diff_preview.diffPreviewId] = diff_preview
            proposal.diffPreviewId = diff_preview.diffPreviewId
            if self.audit_log:
                self.audit_log.add_entry("diff_preview_created", summary=f"Diff preview created: {diff_preview.diffPreviewId}")
            inventory = self.runtime.project_inventory_builder.build_inventory(profile, snapshots) if snapshots else None
            test_plan = self.test_plan_builder.build_test_plan(profile, proposal, inventory)
            self._test_plans[test_plan.testPlanId] = test_plan
            proposal.testPlanId = test_plan.testPlanId
            if self.audit_log:
                self.audit_log.add_entry("test_plan_created", summary=f"Test plan created: {test_plan.testPlanId}")
            test_run = self.test_runner.preview_test_run(normalized.projectId, proposal, test_plan)
            self._test_run_previews[test_run.testRunPreviewId] = test_run
            if self.audit_log:
                self.audit_log.add_entry("test_run_preview_created", summary=f"Test run preview created: {test_run.testRunPreviewId}")
            rollback = self.rollback_builder.build_rollback_metadata(normalized.projectId, proposal, snapshots)
            self._rollback_metadata[rollback.rollbackMetadataId] = rollback
            proposal.rollbackMetadataId = rollback.rollbackMetadataId
            if self.audit_log:
                self.audit_log.add_entry("rollback_metadata_created", summary=f"Rollback metadata created: {rollback.rollbackMetadataId}")
            decision_id = None
            try:
                task = TaskRequest(input=f"Review patch plan preview for host project {normalized.projectId}", context={"projectId": normalized.projectId, "patchProposalId": proposal.patchProposalId, "riskLevel": proposal.riskLevel, "totalFilesChanged": diff_preview.totalFilesChanged, "canApply": False, "canExecute": False}, requirements={}, metadata={"source": "patch_planner", "projectId": normalized.projectId, "patchProposalId": proposal.patchProposalId, "diffPreviewId": diff_preview.diffPreviewId, "testPlanId": test_plan.testPlanId, "rollbackMetadataId": rollback.rollbackMetadataId})
                decision = self.runtime.resolve(task)
                decision_id = decision.decisionId
            except Exception:
                pass
            result = PatchPlanResult(resultId=result_id, projectId=normalized.projectId, status=proposal.status if proposal.status != "planned" else "preview_ready", patchProposal=proposal, diffPreview=diff_preview, testPlan=test_plan, testRunPreview=test_run, rollbackMetadata=rollback, decisionId=decision_id, warnings=safety.get("warnings", []) + diff_preview.warnings, metadata={"source": "patch_planner", "projectId": normalized.projectId, "patchProposalId": proposal.patchProposalId, "diffPreviewId": diff_preview.diffPreviewId, "testPlanId": test_plan.testPlanId, "rollbackMetadataId": rollback.rollbackMetadataId, "canApply": False, "canExecute": False})
            self._patch_results[result_id] = result
            if self.audit_log:
                self.audit_log.add_entry("patch_plan_completed", summary=f"Patch plan completed: {result_id}", details={"status": result.status})
            return result
        except Exception as exc:
            if self.audit_log:
                self.audit_log.add_entry("patch_plan_failed", summary=f"Patch plan failed: {exc}")
            result = PatchPlanResult(resultId=result_id, projectId=normalized.projectId, status="failed", errors=[str(exc)])
            self._patch_results[result_id] = result
            return result

    def _blocked_result(self, result_id: str, project_id: str, errors: List[str], warnings: List[str] | None = None) -> PatchPlanResult:
        if self.audit_log:
            self.audit_log.add_entry("patch_plan_blocked", summary=f"Patch plan blocked for {project_id}", details={"errors": errors})
        result = PatchPlanResult(resultId=result_id, projectId=project_id, status="blocked", errors=errors, warnings=warnings or [], metadata={"canApply": False, "canExecute": False})
        self._patch_results[result_id] = result
        return result

    def get_patch_plan(self, result_id: str) -> Optional[PatchPlanResult]: return self._patch_results.get(result_id)
    def get_patch_proposal(self, patch_proposal_id: str) -> Optional[PatchProposal]: return self._patch_proposals.get(patch_proposal_id)
    def get_diff_preview(self, diff_preview_id: str) -> Optional[DiffPreview]: return self._diff_previews.get(diff_preview_id)
    def get_test_plan(self, test_plan_id: str) -> Optional[TestPlan]: return self._test_plans.get(test_plan_id)
    def get_test_run_preview(self, test_run_preview_id: str) -> Optional[TestRunPreview]: return self._test_run_previews.get(test_run_preview_id)
    def get_rollback_metadata(self, rollback_metadata_id: str) -> Optional[RollbackMetadata]: return self._rollback_metadata.get(rollback_metadata_id)
    def list_patch_plans(self, project_id: Optional[str] = None):
        values = list(self._patch_results.values())
        return [v for v in values if v.projectId == project_id] if project_id else values
    def clear_for_tests(self):
        self._patch_results.clear(); self._diff_previews.clear(); self._test_plans.clear(); self._test_run_previews.clear(); self._rollback_metadata.clear(); self._patch_proposals.clear()
