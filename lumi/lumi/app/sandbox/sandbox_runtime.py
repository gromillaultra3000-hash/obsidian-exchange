from lumi.app.schemas.sandbox import SandboxWorkspaceRequest, SandboxTestRunRequest, ApplyPreparationRequest
from lumi.app.schemas.task import TaskRequest

class SandboxRuntime:
    def __init__(self, runtime, project_registry, snapshot_store, patch_runtime, workspace_builder, sandbox_store, patch_applier, command_guard, test_runner, result_store, apply_preparation_builder, apply_package_service, audit_log, redaction):
        self.runtime=runtime; self.project_registry=project_registry; self.snapshot_store=snapshot_store; self.patch_runtime=patch_runtime; self.workspace_builder=workspace_builder; self.sandbox_store=sandbox_store; self.patch_applier=patch_applier; self.command_guard=command_guard; self.test_runner=test_runner; self.result_store=result_store; self.apply_preparation_builder=apply_preparation_builder; self.apply_package_service=apply_package_service; self.audit_log=audit_log; self.redaction=redaction

    def create_workspace(self, request: SandboxWorkspaceRequest):
        if self.audit_log: self.audit_log.add_entry("sandbox_workspace_requested", summary=f"Sandbox workspace requested: {request.projectId}")
        project = self.project_registry.get_project(request.projectId)
        if not project: raise ValueError(f"Project {request.projectId} not found")
        if project.status == "disabled": raise ValueError(f"Project {request.projectId} is disabled")
        snapshots = self.snapshot_store.list_snapshots(request.projectId) if request.includeSnapshots else []
        workspace = self.workspace_builder.create_workspace(request, project, snapshots)
        if workspace.status == "blocked": raise ValueError("Workspace creation blocked: " + "; ".join(workspace.warnings))
        return self.sandbox_store.add_workspace(workspace)

    def apply_patch_preview(self, workspace_id: str, diff_preview_id: str):
        workspace = self.sandbox_store.get_workspace(workspace_id)
        if not workspace: raise ValueError(f"Workspace {workspace_id} not found")
        diff = self.patch_runtime.get_diff_preview(diff_preview_id)
        if not diff: raise ValueError(f"Diff preview {diff_preview_id} not found")
        result = self.patch_applier.apply_diff_preview_to_workspace(workspace, diff)
        self.sandbox_store.update_workspace(workspace)
        return result

    def run_sandbox_tests(self, request: SandboxTestRunRequest):
        workspace = self.sandbox_store.get_workspace(request.workspaceId) if request.workspaceId else None
        if request.workspaceId and not workspace: raise ValueError(f"Workspace {request.workspaceId} not found")
        project_id = workspace.projectId if workspace else request.projectId
        project = self.project_registry.get_project(project_id)
        if not project: raise ValueError(f"Project {project_id} not found")
        test_plan = self.patch_runtime.get_test_plan(request.testPlanId) if request.testPlanId else None
        result = self.test_runner.run_tests(request, workspace, project, test_plan)
        return self.result_store.add_test_result(result)

    def prepare_apply_package(self, request: ApplyPreparationRequest):
        if self.audit_log: self.audit_log.add_entry("apply_preparation_requested", summary=f"Apply preparation requested: {request.projectId}")
        project = self.project_registry.get_project(request.projectId)
        if not project: raise ValueError(f"Project {request.projectId} not found")
        if project.status == "disabled": raise ValueError(f"Project {request.projectId} is disabled")
        plan = self.patch_runtime.get_patch_plan(request.patchPlanResultId) if request.patchPlanResultId else None
        diff = self.patch_runtime.get_diff_preview(request.diffPreviewId) if request.diffPreviewId else None
        test = self.result_store.get_test_result(request.testRunResultId) if request.testRunResultId else None
        rollback = self.patch_runtime.get_rollback_metadata(request.rollbackMetadataId) if request.rollbackMetadataId else None
        package = self.apply_preparation_builder.prepare_apply_package(request, plan, diff, test, rollback)
        self.result_store.add_apply_package(package)
        try:
            decision = self.runtime.resolve(TaskRequest(input=f"Review apply preparation package for project {request.projectId}", context={"projectId": request.projectId, "applyPackageId": package.applyPackageId, "canApplyToHost": False, "approvalRequired": True}, metadata={"source": "sandbox_apply_preparation", "projectId": request.projectId, "applyPackageId": package.applyPackageId, "canApplyToHost": False, "approvalRequired": True}))
            package.metadata["decisionId"] = decision.decisionId
        except Exception:
            pass
        return package
