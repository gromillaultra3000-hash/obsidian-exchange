from __future__ import annotations
import os
import uuid
import shutil
from datetime import datetime, timezone
from typing import List, Optional
from lumi.app.schemas.real_apply import RollbackPackage, RollbackPreview, RollbackResult

class RollbackService:
    def __init__(self, backup_service, audit_log=None):
        self._packages: dict[str, RollbackPackage] = {}
        self.backup_service = backup_service
        self.audit_log = audit_log

    def create_rollback_package(self, apply_result, backup_record, file_changes) -> RollbackPackage:
        rp_id = str(uuid.uuid4())
        package = RollbackPackage(rollbackPackageId=rp_id, applyId=apply_result.applyId, workspaceId=apply_result.workspaceId, createdAt=datetime.now(timezone.utc).isoformat(), status="available", files=[{"path": c.path, "operation": c.operation} for c in file_changes], canRollback=True, backupId=backup_record.backupId if backup_record else None, warnings=[], blockers=[], metadata={"contentExcluded": True})
        self._packages[rp_id] = package
        if self.audit_log:
            self.audit_log.add_entry("rollback_package_created", summary=f"Rollback package {rp_id} created", details={"rollbackPackageId": rp_id, "filesCount": len(package.files)})
        return package

    def get_rollback_package(self, rollback_package_id: str) -> Optional[RollbackPackage]:
        return self._packages.get(rollback_package_id)

    def list_rollback_packages(self, workspace_id: str | None = None) -> List[RollbackPackage]:
        rows = list(self._packages.values())
        return [p for p in rows if p.workspaceId == workspace_id] if workspace_id else rows

    def preview_rollback(self, rollback_package_id: str) -> Optional[RollbackPreview]:
        pkg = self._packages.get(rollback_package_id)
        if not pkg:
            return None
        restore = [f["path"] for f in pkg.files if f.get("operation") in ("update", "delete")]
        delete = [f["path"] for f in pkg.files if f.get("operation") == "create"]
        blockers = [] if pkg.canRollback else ["Rollback package is not available"]
        preview = RollbackPreview(rollbackPackageId=rollback_package_id, workspaceId=pkg.workspaceId, canRollback=pkg.canRollback, filesToRestore=restore, filesToDelete=delete, blockers=blockers)
        if self.audit_log:
            self.audit_log.add_entry("rollback_preview_created", summary=f"Rollback preview created: {rollback_package_id}", details={"filesToRestore": len(restore), "filesToDelete": len(delete)})
        return preview

    def execute_rollback(self, request, workspace) -> RollbackResult:
        pkg = self._packages.get(request.rollbackPackageId)
        if not pkg or not pkg.canRollback:
            return RollbackResult(rollbackId=str(uuid.uuid4()), rollbackPackageId=request.rollbackPackageId, workspaceId=workspace.workspaceId if workspace else "", status="blocked", errors=["Rollback package unavailable"])
        if not request.approvalPromptId:
            return RollbackResult(rollbackId=str(uuid.uuid4()), rollbackPackageId=request.rollbackPackageId, workspaceId=workspace.workspaceId, status="blocked", errors=["Approval required for rollback"])
        backup = self.backup_service.get_backup(pkg.backupId) if pkg.backupId else None
        root = os.path.realpath(workspace.normalizedRootPath)
        restored, deleted, failed = [], [], []
        for f in pkg.files:
            rel = f["path"]
            dst = os.path.realpath(os.path.join(root, rel))
            try:
                if os.path.commonpath([root, dst]) != root:
                    failed.append({"path": rel, "error": "Path outside workspace"}); continue
                if f.get("operation") in ("update", "delete"):
                    if not backup:
                        failed.append({"path": rel, "error": "Backup missing"}); continue
                    src = os.path.realpath(os.path.join(backup.backupRoot, rel))
                    if os.path.exists(src):
                        os.makedirs(os.path.dirname(dst), exist_ok=True)
                        shutil.copy2(src, dst)
                        restored.append(rel)
                    else:
                        failed.append({"path": rel, "error": "Backup file missing"})
                elif f.get("operation") == "create":
                    if os.path.isfile(dst):
                        os.remove(dst)
                        deleted.append(rel)
            except Exception as e:
                failed.append({"path": rel, "error": str(e)[:500]})
        status = "rolled_back" if not failed else "failed"
        pkg.status = status
        result = RollbackResult(rollbackId=str(uuid.uuid4()), rollbackPackageId=request.rollbackPackageId, workspaceId=workspace.workspaceId, status=status, restoredFiles=restored, deletedFiles=deleted, failedFiles=failed, errors=[f["error"] for f in failed])
        if self.audit_log:
            self.audit_log.add_entry("rollback_completed" if status == "rolled_back" else "rollback_failed", summary=f"Rollback {request.rollbackPackageId}: {status}", details={"restoredCount": len(restored), "deletedCount": len(deleted), "failedCount": len(failed)})
        return result

    def clear_for_tests(self):
        self._packages.clear()
