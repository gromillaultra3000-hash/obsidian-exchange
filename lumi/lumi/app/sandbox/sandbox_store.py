from typing import Optional, List
from lumi.app.schemas.sandbox import SandboxWorkspace

class SandboxStore:
    def __init__(self, audit_log=None):
        self._workspaces: dict[str, SandboxWorkspace] = {}
        self.audit_log = audit_log

    def add_workspace(self, workspace: SandboxWorkspace) -> SandboxWorkspace:
        self._workspaces[workspace.workspaceId] = workspace
        if self.audit_log:
            self.audit_log.add_entry("sandbox_workspace_created", summary=f"Sandbox workspace {workspace.workspaceId} created", details={"projectId": workspace.projectId, "files": len(workspace.files)})
        return workspace

    def get_workspace(self, workspace_id: str) -> Optional[SandboxWorkspace]:
        return self._workspaces.get(workspace_id)

    def list_workspaces(self, project_id: Optional[str] = None) -> List[SandboxWorkspace]:
        vals = list(self._workspaces.values())
        return [w for w in vals if w.projectId == project_id] if project_id else vals

    def update_workspace(self, workspace: SandboxWorkspace) -> SandboxWorkspace:
        self._workspaces[workspace.workspaceId] = workspace
        return workspace

    def discard_workspace(self, workspace_id: str) -> Optional[SandboxWorkspace]:
        workspace = self._workspaces.get(workspace_id)
        if workspace:
            workspace.status = "discarded"
            self._workspaces.pop(workspace_id, None)
            if self.audit_log:
                self.audit_log.add_entry("sandbox_workspace_discarded", summary=f"Sandbox workspace {workspace_id} discarded")
        return workspace

    def clear_for_tests(self):
        self._workspaces.clear()
