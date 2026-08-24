from __future__ import annotations
import os
import uuid
import tempfile
from datetime import datetime, timezone
from lumi.app.schemas.real_apply import ApplyExecutionResult

class ApplyExecutor:
    def __init__(self, audit_log=None):
        self.audit_log = audit_log
        self._results: dict[str, ApplyExecutionResult] = {}

    def execute(self, request, workspace, gate_result, backup_record) -> ApplyExecutionResult:
        apply_id = str(uuid.uuid4())
        applied, skipped, failed = [], [], []
        if not gate_result.allowed:
            return ApplyExecutionResult(applyId=apply_id, workspaceId=request.workspaceId, status="blocked", skippedFiles=[c.path for c in request.fileChanges], errors=gate_result.blockers)
        root = os.path.realpath(workspace.normalizedRootPath)
        if self.audit_log:
            self.audit_log.add_entry("controlled_apply_started", summary=f"Controlled apply started: {apply_id}", details={"workspaceId": workspace.workspaceId, "filesCount": len(request.fileChanges)})
        for change in request.fileChanges:
            try:
                if change.operation not in ("create", "update"):
                    skipped.append(change.path)
                    continue
                target = os.path.realpath(os.path.join(root, change.path))
                if os.path.commonpath([root, target]) != root:
                    failed.append({"path": change.path, "error": "Path outside workspace"})
                    continue
                os.makedirs(os.path.dirname(target), exist_ok=True)
                content = change.afterContent or ""
                fd, tmp_path = tempfile.mkstemp(prefix=".lumi-apply-", dir=os.path.dirname(target), text=True)
                try:
                    with os.fdopen(fd, 'w', encoding='utf-8') as f:
                        f.write(content)
                        f.flush()
                        os.fsync(f.fileno())
                    os.replace(tmp_path, target)
                    with open(target, 'r', encoding='utf-8') as verify:
                        if verify.read() != content:
                            raise RuntimeError("Written content verification failed")
                    applied.append(change.path)
                finally:
                    if os.path.exists(tmp_path):
                        try: os.remove(tmp_path)
                        except OSError: pass
            except Exception as e:
                failed.append({"path": change.path, "error": str(e)[:500]})
        status = "applied" if applied and not failed else "partial" if applied else "failed"
        result = ApplyExecutionResult(applyId=apply_id, workspaceId=workspace.workspaceId, status=status, appliedFiles=applied, skippedFiles=skipped, failedFiles=failed, backupId=backup_record.backupId if backup_record else None, warnings=[], errors=[f["error"] for f in failed], metadata={"createdAt": datetime.now(timezone.utc).isoformat(), "contentExcluded": True})
        self._results[apply_id] = result
        if self.audit_log:
            self.audit_log.add_entry("controlled_apply_completed" if status in ("applied", "partial") else "controlled_apply_failed", summary=f"Controlled apply {apply_id}: {status}", details={"appliedCount": len(applied), "failedCount": len(failed)})
        return result

    def get_result(self, apply_id: str):
        return self._results.get(apply_id)

    def list_results(self):
        return list(self._results.values())

    def clear_for_tests(self):
        self._results.clear()
