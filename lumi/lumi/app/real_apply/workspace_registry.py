from __future__ import annotations
import os
import uuid
from datetime import datetime, timezone
from typing import Optional, List
from lumi.app.schemas.real_apply import SafeWorkspace, RegisterWorkspaceRequest, RegisterWorkspaceResult

class SafeWorkspaceRegistry:
    def __init__(self, audit_log=None):
        self._workspaces: dict[str, SafeWorkspace] = {}
        self.audit_log = audit_log

    def normalize_root_path(self, path: str) -> str:
        return os.path.realpath(os.path.abspath(os.path.expanduser(path)))

    def verify_workspace_exists(self, path: str) -> bool:
        return os.path.isdir(path)

    def register_workspace(self, request: RegisterWorkspaceRequest) -> RegisterWorkspaceResult:
        warnings = []
        if not os.path.isabs(os.path.expanduser(request.rootPath)):
            warnings.append("Workspace rootPath should be absolute; stored as normalized absolute path.")
        normalized = self.normalize_root_path(request.rootPath)
        status = "registered" if self.verify_workspace_exists(normalized) else "missing"
        ws_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        workspace = SafeWorkspace(
            workspaceId=ws_id,
            displayName=request.displayName,
            rootPath=request.rootPath,
            normalizedRootPath=normalized,
            status=status,
            allowApply=bool(request.allowApply) and status == "registered",
            createdAt=now,
            updatedAt=now,
            allowedPathPrefixes=request.allowedPathPrefixes,
            blockedPathPrefixes=request.blockedPathPrefixes,
            metadata=request.metadata,
        )
        self._workspaces[ws_id] = workspace
        if self.audit_log:
            self.audit_log.add_entry("workspace_registered", summary=f"Workspace {ws_id} registered", details={"workspaceId": ws_id, "status": status, "allowApply": workspace.allowApply})
        return RegisterWorkspaceResult(workspace=workspace, warnings=warnings)

    def get_workspace(self, workspace_id: str) -> Optional[SafeWorkspace]:
        return self._workspaces.get(workspace_id)

    def list_workspaces(self) -> List[SafeWorkspace]:
        return list(self._workspaces.values())

    def enable_workspace_apply(self, workspace_id: str) -> Optional[SafeWorkspace]:
        ws = self._workspaces.get(workspace_id)
        if ws:
            ws.allowApply = True if ws.status == "registered" else False
            ws.updatedAt = datetime.now(timezone.utc).isoformat()
            if self.audit_log:
                self.audit_log.add_entry("workspace_apply_enabled", summary=f"Apply enabled for {workspace_id}", details={"workspaceId": workspace_id, "status": ws.status})
        return ws

    def disable_workspace_apply(self, workspace_id: str) -> Optional[SafeWorkspace]:
        ws = self._workspaces.get(workspace_id)
        if ws:
            ws.allowApply = False
            ws.updatedAt = datetime.now(timezone.utc).isoformat()
            if self.audit_log:
                self.audit_log.add_entry("workspace_apply_disabled", summary=f"Apply disabled for {workspace_id}", details={"workspaceId": workspace_id})
        return ws

    def block_workspace(self, workspace_id: str, reason: str) -> Optional[SafeWorkspace]:
        ws = self._workspaces.get(workspace_id)
        if ws:
            ws.status = "blocked"
            ws.allowApply = False
            ws.metadata["blockedReason"] = reason
            ws.updatedAt = datetime.now(timezone.utc).isoformat()
        return ws

    def clear_for_tests(self):
        self._workspaces.clear()
