import uuid
from typing import List, Optional
from lumi.app.schemas.patch_planner import DiffPreview, FileDiffPreview, DiffPreviewLine, PatchProposal
from lumi.app.schemas.project_scanner import FileSnapshot
from lumi.app.providers.redaction import RedactionUtil

class DiffPreviewBuilder:
    def __init__(self, snapshot_store=None, redaction: RedactionUtil | None = None):
        self.snapshot_store = snapshot_store
        self.redaction = redaction or RedactionUtil()

    def build_diff_preview(self, project_id: str, patch_proposal: PatchProposal, snapshots: Optional[List[FileSnapshot]] = None) -> DiffPreview:
        diff_id = str(uuid.uuid4())
        snapshots = snapshots or []
        snapshot_map = {s.path: s for s in snapshots}
        file_diffs, warnings = [], []
        total_additions = total_removals = 0
        target_files = patch_proposal.targetFiles or ["synthetic_preview.md"]
        for file_path in target_files:
            snapshot = snapshot_map.get(file_path)
            change_type = self._determine_change_type(file_path, patch_proposal)
            lines = []
            file_warnings = []
            if snapshot and snapshot.contentPreview and not snapshot.isBinary:
                preview = self.redaction.redact_value("content", snapshot.contentPreview)
                for i, line in enumerate(str(preview).split("\n")[:5]):
                    lines.append(DiffPreviewLine(lineType="context", oldLineNumber=i+1, newLineNumber=i+1, content=str(line)[:240]))
                lines.extend(self._generate_synthetic_changes(change_type, patch_proposal))
            else:
                msg = f"No snapshot available for {file_path}; generated synthetic preview only."
                warnings.append(msg); file_warnings.append(msg)
                lines = self._generate_synthetic_new_file(change_type, patch_proposal, file_path)
            for line in lines:
                line.content = self.redaction.redact_value("content", line.content)
            total_additions += sum(1 for l in lines if l.lineType in ["add", "info"])
            total_removals += sum(1 for l in lines if l.lineType == "remove")
            file_diffs.append(FileDiffPreview(fileDiffId=str(uuid.uuid4()), path=file_path, changeType=change_type, summary=f"Synthetic preview for {file_path}", lines=lines, isSynthetic=True, canApply=False, warnings=file_warnings))
        return DiffPreview(diffPreviewId=diff_id, projectId=project_id, patchProposalId=patch_proposal.patchProposalId, title=f"Diff Preview: {patch_proposal.title}", summary=patch_proposal.summary, fileDiffs=file_diffs, totalFilesChanged=len(file_diffs), totalAdditions=total_additions, totalRemovals=total_removals, canApply=False, applyBlockedReason="real_file_write_disabled_in_v0_9", warnings=warnings)

    def _determine_change_type(self, file_path: str, proposal: PatchProposal):
        for change in proposal.proposedChanges:
            ct = change.get("changeType", "unknown")
            if ct in ["docs_change", "test_change", "config_change", "security_fix", "refactor", "create_file", "update_file"]:
                return ct
        lower = file_path.lower()
        if "readme" in lower or lower.startswith("docs/"):
            return "docs_change"
        if "test" in lower or "spec" in lower:
            return "test_change"
        return "unknown"

    def _generate_synthetic_changes(self, change_type: str, proposal: PatchProposal):
        if change_type == "docs_change":
            return [DiffPreviewLine(lineType="info", content="# Synthetic preview: add documentation section"), DiffPreviewLine(lineType="add", content="## Purpose"), DiffPreviewLine(lineType="add", content="Describe purpose, setup, usage, and limitations.")]
        if change_type == "test_change":
            return [DiffPreviewLine(lineType="info", content="# Synthetic preview: add basic tests"), DiffPreviewLine(lineType="add", content="def test_basic_behavior():"), DiffPreviewLine(lineType="add", content="    assert True")]
        if change_type == "security_fix":
            return [DiffPreviewLine(lineType="info", content="# Synthetic preview: security improvement"), DiffPreviewLine(lineType="remove", content="# [REDACTED sensitive-looking content]"), DiffPreviewLine(lineType="add", content="# Use protected configuration reference instead")]
        if change_type == "config_change":
            return [DiffPreviewLine(lineType="info", content="# Synthetic preview: add or update configuration"), DiffPreviewLine(lineType="add", content="# Configuration placeholder")]
        return [DiffPreviewLine(lineType="info", content="# Synthetic preview: review and update structure")]

    def _generate_synthetic_new_file(self, change_type: str, proposal: PatchProposal, file_path: str):
        lines = [DiffPreviewLine(lineType="info", content=f"# Synthetic preview only for {file_path}")]
        lines.extend(self._generate_synthetic_changes(change_type, proposal))
        return lines
