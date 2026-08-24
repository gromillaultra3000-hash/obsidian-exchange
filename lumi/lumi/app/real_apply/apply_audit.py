class ApplyAuditBuilder:
    def __init__(self, redaction=None):
        self.redaction = redaction

    def build_apply_summary(self, result):
        return {"applyId": result.applyId, "workspaceId": result.workspaceId, "status": result.status, "appliedFilesCount": len(result.appliedFiles), "failedFilesCount": len(result.failedFiles), "backupId": result.backupId, "rollbackPackageId": result.rollbackPackageId}

    def build_rollback_summary(self, result):
        return {"rollbackId": result.rollbackId, "rollbackPackageId": result.rollbackPackageId, "workspaceId": result.workspaceId, "status": result.status, "restoredFilesCount": len(result.restoredFiles), "deletedFilesCount": len(result.deletedFiles), "failedFilesCount": len(result.failedFiles)}

    def redact_apply_metadata(self, metadata):
        return self.redaction.redact_dict(metadata or {}) if self.redaction else (metadata or {})
