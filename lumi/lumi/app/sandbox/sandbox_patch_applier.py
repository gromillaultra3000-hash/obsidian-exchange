import uuid
from lumi.app.schemas.sandbox import SandboxWorkspace, SandboxPatchApplyPreview
from lumi.app.schemas.patch_planner import DiffPreview

class SandboxPatchApplierPreview:
    def __init__(self, audit_log=None):
        self.audit_log = audit_log

    def apply_diff_preview_to_workspace(self, workspace: SandboxWorkspace, diff_preview: DiffPreview | None) -> SandboxPatchApplyPreview:
        apply_id = str(uuid.uuid4())
        if not diff_preview or not diff_preview.fileDiffs:
            if self.audit_log:
                self.audit_log.add_entry("sandbox_patch_preview_blocked", summary="Diff preview application blocked: no diff data")
            return SandboxPatchApplyPreview(applyPreviewId=apply_id, workspaceId=workspace.workspaceId, projectId=workspace.projectId, diffPreviewId=diff_preview.diffPreviewId if diff_preview else "unknown", status="blocked", warnings=["No diff preview data available"], canAffectHost=False)
        files_affected: list[str] = []
        changes: list[dict] = []
        for fd in diff_preview.fileDiffs:
            files_affected.append(fd.path)
            for line in fd.lines:
                changes.append({"path": fd.path, "lineType": line.lineType, "content": (line.content or "")[:200], "isSynthetic": True})
        workspace.status = "patched"
        if self.audit_log:
            self.audit_log.add_entry("sandbox_patch_preview_applied", summary=f"Synthetic diff preview applied to sandbox {workspace.workspaceId}", details={"filesAffected": len(files_affected)})
        return SandboxPatchApplyPreview(applyPreviewId=apply_id, workspaceId=workspace.workspaceId, projectId=workspace.projectId, diffPreviewId=diff_preview.diffPreviewId, status="patched", filesAffected=files_affected, appliedSyntheticChanges=changes, canAffectHost=False, hostWriteBlockedReason="host_project_write_disabled_in_v1_0")
