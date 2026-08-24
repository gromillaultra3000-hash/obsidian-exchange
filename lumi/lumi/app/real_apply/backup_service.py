from __future__ import annotations
import os
import uuid
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional
from lumi.app.schemas.real_apply import BackupPlan, BackupRecord

class BackupService:
    def __init__(self, audit_log=None, redaction=None, backup_root: str = "backups"):
        self._backups: dict[str, BackupRecord] = {}
        self.audit_log = audit_log
        self.redaction = redaction
        self.backup_root = backup_root

    def _safe_meta_path(self, path: str) -> str:
        return str(path).replace('\\','/')

    def build_backup_plan(self, workspace, file_changes: List) -> BackupPlan:
        blockers, warnings, paths, estimated = [], [], [], 0
        if not workspace:
            blockers.append("Workspace not found")
            return BackupPlan(backupPlanId=str(uuid.uuid4()), workspaceId="", blockers=blockers)
        for c in file_changes:
            if c.operation in ("update", "delete"):
                p = os.path.realpath(os.path.join(workspace.normalizedRootPath, c.path))
                if os.path.exists(p):
                    paths.append(c.path)
                    try: estimated += os.path.getsize(p)
                    except OSError: pass
                else:
                    warnings.append(f"Existing file not found for backup: {c.path}")
        plan = BackupPlan(backupPlanId=str(uuid.uuid4()), workspaceId=workspace.workspaceId, filesToBackup=paths, estimatedBytes=estimated, warnings=warnings, blockers=blockers)
        if self.audit_log:
            self.audit_log.add_entry("backup_plan_created", summary=f"Backup plan created for workspace {workspace.workspaceId}", details={"filesCount": len(paths), "estimatedBytes": estimated})
        return plan

    def create_backup(self, workspace, file_changes: List) -> Optional[BackupRecord]:
        if not workspace:
            return None
        backup_id = str(uuid.uuid4())
        backup_dir = os.path.realpath(os.path.join(self.backup_root, workspace.workspaceId, backup_id))
        os.makedirs(backup_dir, exist_ok=True)
        files_meta = []
        for change in file_changes:
            if change.operation not in ("update", "delete"):
                continue
            src = os.path.realpath(os.path.join(workspace.normalizedRootPath, change.path))
            root = os.path.realpath(workspace.normalizedRootPath)
            try:
                if os.path.commonpath([root, src]) != root:
                    continue
            except ValueError:
                continue
            if os.path.exists(src) and os.path.isfile(src):
                rel = change.path.replace('\\','/')
                dst = os.path.realpath(os.path.join(backup_dir, rel))
                if os.path.commonpath([backup_dir, dst]) != backup_dir:
                    continue
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src, dst)
                files_meta.append({"path": rel, "sizeBytes": os.path.getsize(src), "operation": change.operation})
        record = BackupRecord(backupId=backup_id, workspaceId=workspace.workspaceId, createdAt=datetime.now(timezone.utc).isoformat(), files=files_meta, backupRoot=backup_dir, redacted=True, metadata={"contentExcluded": True})
        self._backups[backup_id] = record
        if self.audit_log:
            self.audit_log.add_entry("backup_created", summary=f"Backup {backup_id} created", details={"backupId": backup_id, "filesCount": len(files_meta)})
        return record

    def get_backup(self, backup_id: str) -> Optional[BackupRecord]:
        return self._backups.get(backup_id)

    def list_backups(self, workspace_id: str | None = None) -> List[BackupRecord]:
        rows = list(self._backups.values())
        return [b for b in rows if b.workspaceId == workspace_id] if workspace_id else rows

    def clear_for_tests(self):
        self._backups.clear()
