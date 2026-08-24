from __future__ import annotations
import uuid
from lumi.app.schemas.real_apply import ApplyExecutionResult, RollbackResult

class RealApplyRuntime:
    def __init__(self, config_service, workspace_registry, path_guard, file_classifier, diff_validator, apply_gate, backup_service, apply_executor, rollback_service, audit_builder, audit_log=None, redaction=None):
        self.config_service = config_service
        self.workspace_registry = workspace_registry
        self.path_guard = path_guard
        self.file_classifier = file_classifier
        self.diff_validator = diff_validator
        self.apply_gate = apply_gate
        self.backup_service = backup_service
        self.apply_executor = apply_executor
        self.rollback_service = rollback_service
        self.audit_builder = audit_builder
        self.audit_log = audit_log
        self.redaction = redaction

    def get_apply_config(self): return self.config_service.get_config()
    def enable_controlled_apply(self): return self.config_service.enable_controlled_mode()
    def disable_apply(self): return self.config_service.disable_apply()
    def register_workspace(self, request): return self.workspace_registry.register_workspace(request)
    def list_workspaces(self): return self.workspace_registry.list_workspaces()
    def get_workspace(self, workspace_id): return self.workspace_registry.get_workspace(workspace_id)
    def enable_workspace_apply(self, workspace_id): return self.workspace_registry.enable_workspace_apply(workspace_id)
    def disable_workspace_apply(self, workspace_id): return self.workspace_registry.disable_workspace_apply(workspace_id)
    def check_apply_gate(self, request): return self.apply_gate.check_gate(request)

    def build_backup_plan(self, workspace_id, file_changes):
        workspace = self.workspace_registry.get_workspace(workspace_id)
        return self.backup_service.build_backup_plan(workspace, file_changes)

    def create_backup(self, workspace_id, file_changes):
        workspace = self.workspace_registry.get_workspace(workspace_id)
        return self.backup_service.create_backup(workspace, file_changes)

    def execute_apply(self, request):
        if self.audit_log:
            self.audit_log.add_entry("controlled_apply_requested", summary=f"Controlled apply requested for workspace {request.workspaceId}", details={"filesCount": len(request.fileChanges)})
        gate_result = self.apply_gate.check_gate(request)
        if not gate_result.allowed:
            if self.audit_log:
                self.audit_log.add_entry("controlled_apply_blocked", summary="Controlled apply blocked by gate", details={"blockers": gate_result.blockers[:20]})
            return ApplyExecutionResult(applyId=str(uuid.uuid4()), workspaceId=request.workspaceId, status="blocked", skippedFiles=[c.path for c in request.fileChanges], errors=gate_result.blockers, metadata={"gateId": gate_result.gateId})
        workspace = self.workspace_registry.get_workspace(request.workspaceId)
        backup_record = None
        if self.config_service.get_config().requireBackup:
            backup_record = self.backup_service.create_backup(workspace, request.fileChanges)
            if backup_record is None:
                return ApplyExecutionResult(applyId=str(uuid.uuid4()), workspaceId=request.workspaceId, status="blocked", errors=["Backup required but backup failed"], metadata={"gateId": gate_result.gateId})
        result = self.apply_executor.execute(request, workspace, gate_result, backup_record)
        if result.status in ("applied", "partial"):
            rp = self.rollback_service.create_rollback_package(result, backup_record, request.fileChanges)
            result.rollbackPackageId = rp.rollbackPackageId
        return result

    def list_apply_results(self): return self.apply_executor.list_results()
    def get_apply_result(self, apply_id): return self.apply_executor.get_result(apply_id)
    def list_backups(self, workspace_id=None): return self.backup_service.list_backups(workspace_id)
    def get_backup(self, backup_id): return self.backup_service.get_backup(backup_id)
    def list_rollback_packages(self, workspace_id=None): return self.rollback_service.list_rollback_packages(workspace_id)
    def get_rollback_package(self, rollback_package_id): return self.rollback_service.get_rollback_package(rollback_package_id)
    def preview_rollback(self, rollback_package_id): return self.rollback_service.preview_rollback(rollback_package_id)

    def execute_rollback(self, request):
        if self.audit_log:
            self.audit_log.add_entry("rollback_requested", summary=f"Rollback requested: {request.rollbackPackageId}")
        pkg = self.rollback_service.get_rollback_package(request.rollbackPackageId)
        if not pkg:
            return RollbackResult(rollbackId=str(uuid.uuid4()), rollbackPackageId=request.rollbackPackageId, workspaceId="", status="blocked", errors=["Rollback package not found"])
        workspace = self.workspace_registry.get_workspace(pkg.workspaceId)
        if not workspace:
            return RollbackResult(rollbackId=str(uuid.uuid4()), rollbackPackageId=request.rollbackPackageId, workspaceId=pkg.workspaceId, status="blocked", errors=["Workspace not found"])
        return self.rollback_service.execute_rollback(request, workspace)
