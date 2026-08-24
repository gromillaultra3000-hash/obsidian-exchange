from typing import List
from lumi.app.schemas.project_scanner import FileSnapshot
from lumi.app.providers.redaction import RedactionUtil

MAX_PREVIEW_LENGTH = 4000

class FileSnapshotStore:
    def __init__(self, audit_log=None, redaction: RedactionUtil | None = None):
        self._snapshots: dict[str, FileSnapshot] = {}
        self._by_project: dict[str, list[str]] = {}
        self.audit_log = audit_log
        self.redaction = redaction or RedactionUtil()

    def add_snapshot(self, snapshot: FileSnapshot) -> FileSnapshot:
        safe = self._sanitize(snapshot)
        replacing = safe.snapshotId in self._snapshots
        self._snapshots[safe.snapshotId] = safe
        ids = self._by_project.setdefault(safe.projectId, [])
        if safe.snapshotId not in ids:
            ids.append(safe.snapshotId)
        if self.audit_log:
            self.audit_log.add_entry("file_snapshot_received", summary=f"File snapshot received: {safe.snapshotId}", details={"projectId": safe.projectId, "path": safe.path, "replacing": replacing})
        return safe

    def add_snapshots(self, project_id: str, snapshots: List[FileSnapshot]) -> List[FileSnapshot]:
        results = []
        for snap in snapshots:
            snap.projectId = project_id
            results.append(self.add_snapshot(snap))
        return results

    def list_snapshots(self, project_id: str) -> List[FileSnapshot]:
        return [self._snapshots[sid] for sid in self._by_project.get(project_id, []) if sid in self._snapshots]

    def list_all_snapshots(self) -> List[FileSnapshot]:
        return list(self._snapshots.values())

    def get_snapshot(self, snapshot_id: str):
        return self._snapshots.get(snapshot_id)

    def clear_project(self, project_id: str):
        for sid in self._by_project.pop(project_id, []):
            self._snapshots.pop(sid, None)

    def clear_for_tests(self):
        self._snapshots.clear(); self._by_project.clear()

    def _sanitize(self, snapshot: FileSnapshot) -> FileSnapshot:
        data = snapshot.model_dump()
        data["metadata"] = self.redaction.redact_dict(data.get("metadata") or {})
        if data.get("isBinary"):
            if data.get("contentPreview") and self.audit_log:
                self.audit_log.add_entry("file_snapshot_blocked", summary=f"Binary preview ignored for {snapshot.path}")
            data["contentPreview"] = None
        elif data.get("contentPreview") is not None:
            preview = str(data["contentPreview"])
            truncated = len(preview) > MAX_PREVIEW_LENGTH
            preview = preview[:MAX_PREVIEW_LENGTH]
            redacted = self.redaction.redact_secret_like(preview)
            data["contentPreview"] = redacted
            if self.audit_log and (truncated or redacted != preview):
                self.audit_log.add_entry("file_snapshot_redacted", summary=f"File snapshot preview redacted/truncated for {snapshot.path}")
        return FileSnapshot(**data)
