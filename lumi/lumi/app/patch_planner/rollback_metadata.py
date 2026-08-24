import uuid
from typing import List
from lumi.app.schemas.patch_planner import RollbackMetadata, RollbackStep
from lumi.app.schemas.project_scanner import FileSnapshot

class RollbackMetadataBuilder:
    def __init__(self, snapshot_store=None):
        self.snapshot_store = snapshot_store

    def build_rollback_metadata(self, project_id: str, patch_proposal, snapshots: List[FileSnapshot] | None = None) -> RollbackMetadata:
        snapshots = snapshots or []
        snapshot_map = {s.path: s for s in snapshots}
        affected_files = list(getattr(patch_proposal, "targetFiles", []) or [])
        snapshot_refs, steps = [], []
        steps.append(RollbackStep(stepId=str(uuid.uuid4()), title="Review before rollback", targetFiles=affected_files, description="Review planned changes and confirm rollback intent. This is metadata only.", canExecute=False, executeBlockedReason="real_rollback_execution_disabled_in_v0_9"))
        for file_path in affected_files:
            snapshot = snapshot_map.get(file_path)
            if snapshot:
                ref = snapshot.snapshotId
                if snapshot.contentHash:
                    ref += f":{snapshot.contentHash}"
                snapshot_refs.append(ref)
                desc = f"Restore {file_path} from snapshot reference {snapshot.snapshotId}."
            else:
                desc = f"No snapshot available for {file_path}; manual review required."
            steps.append(RollbackStep(stepId=str(uuid.uuid4()), title=f"Rollback preview for {file_path}", targetFiles=[file_path], description=desc, canExecute=False, executeBlockedReason="real_rollback_execution_disabled_in_v0_9"))
        return RollbackMetadata(rollbackMetadataId=str(uuid.uuid4()), projectId=project_id, patchProposalId=getattr(patch_proposal, "patchProposalId", None), status="preview_ready", summary=f"Rollback metadata for {len(affected_files)} affected file(s).", affectedFiles=affected_files, rollbackSteps=steps, snapshotReferences=snapshot_refs, canRollback=False, rollbackBlockedReason="real_rollback_execution_disabled_in_v0_9")
