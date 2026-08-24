import uuid
from datetime import datetime, timezone
from typing import List
from lumi.app.schemas.sandbox import SandboxWorkspaceRequest, SandboxWorkspace, SandboxFile
from lumi.app.schemas.project_scanner import FileSnapshot, HostProjectProfile
from lumi.app.providers.redaction import RedactionUtil

MAX_FILES = 300
MAX_TOTAL_PREVIEW_SIZE = 2_000_000
MAX_PREVIEW_CHARS = 4000

class SandboxWorkspaceBuilder:
    def __init__(self, redaction: RedactionUtil | None = None):
        self.redaction = redaction or RedactionUtil()

    def create_workspace(self, request: SandboxWorkspaceRequest, project_profile: HostProjectProfile, snapshots: List[FileSnapshot]) -> SandboxWorkspace:
        warnings: list[str] = []
        files: list[SandboxFile] = []
        total_preview_size = 0
        for i, snapshot in enumerate(snapshots):
            if i >= MAX_FILES:
                warnings.append(f"File count limit ({MAX_FILES}) reached. Skipping remaining files.")
                break
            preview = None
            if not snapshot.isBinary and snapshot.contentPreview:
                redacted = self.redaction.redact_value("contentPreview", snapshot.contentPreview)
                redacted = redacted[:MAX_PREVIEW_CHARS]
                preview_size = len(redacted.encode("utf-8"))
                if total_preview_size + preview_size > MAX_TOTAL_PREVIEW_SIZE:
                    warnings.append(f"Total preview size limit reached. Skipping preview for {snapshot.path}.")
                else:
                    preview = redacted
                    total_preview_size += preview_size
            files.append(SandboxFile(path=snapshot.path, contentPreview=preview, contentHash=snapshot.contentHash, sizeBytes=snapshot.sizeBytes, isBinary=snapshot.isBinary, isGenerated=getattr(snapshot, "isGenerated", False), isSynthetic=False, metadata=self.redaction.redact_dict(snapshot.metadata or {})))
        if not files:
            warnings.append("No file snapshots available for workspace creation.")
        return SandboxWorkspace(workspaceId=str(uuid.uuid4()), projectId=request.projectId, source=request.source, status="ready" if files else "blocked", createdAt=datetime.now(timezone.utc).isoformat(), files=files, patchPlanResultId=request.patchPlanResultId, diffPreviewId=request.diffPreviewId, warnings=warnings, metadata={"requestId": request.requestId, "hostProjectStatus": project_profile.status})
