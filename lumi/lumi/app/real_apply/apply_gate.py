from __future__ import annotations
import uuid
from lumi.app.schemas.real_apply import ApplyGateResult

class ApplyGate:
    def __init__(self, config_service, workspace_registry, path_guard, file_classifier, diff_validator, audit_log=None):
        self.config_service = config_service
        self.workspace_registry = workspace_registry
        self.path_guard = path_guard
        self.file_classifier = file_classifier
        self.diff_validator = diff_validator
        self.audit_log = audit_log

    def check_gate(self, request) -> ApplyGateResult:
        gate_id = str(uuid.uuid4())
        config = self.config_service.get_config()
        blockers, warnings, path_results, classifications = [], [], [], []
        if config.mode != "controlled":
            blockers.append("Global apply mode is not controlled")
        workspace = self.workspace_registry.get_workspace(request.workspaceId)
        if not workspace:
            blockers.append("Workspace not found")
        else:
            if workspace.status != "registered":
                blockers.append(f"Workspace status is {workspace.status}")
            if not workspace.allowApply:
                blockers.append("Workspace apply not allowed")
        diff = self.diff_validator.validate(request.fileChanges, config)
        if not diff["valid"]:
            blockers.extend(diff["errors"])
        if workspace:
            for ch in request.fileChanges:
                pr = self.path_guard.check_path(workspace, ch.path)
                path_results.append(pr)
                if not pr.allowed:
                    blockers.extend([f"{ch.path}: {b}" for b in pr.blockers])
                    continue
                fc = self.file_classifier.classify_change(ch, config)
                classifications.append(fc)
                if not fc.allowed:
                    blockers.extend([f"{ch.path}: {b}" for b in fc.blockers])
        if config.requireSandboxPass and not request.testRunResultId:
            blockers.append("Sandbox test pass required but not provided")
        if config.requireApproval and not request.approvalPromptId:
            blockers.append("Approval required but not provided")
        allowed = not blockers
        event = "apply_gate_allowed" if allowed else "apply_gate_blocked"
        if self.audit_log:
            self.audit_log.add_entry("apply_gate_checked", summary=f"Apply gate checked: {gate_id}", details={"allowed": allowed, "blockersCount": len(blockers)})
            self.audit_log.add_entry(event, summary=f"Apply gate {'allowed' if allowed else 'blocked'}: {gate_id}", details={"blockers": blockers[:20]})
        return ApplyGateResult(gateId=gate_id, status="allowed" if allowed else "blocked", allowed=allowed, workspaceId=request.workspaceId, blockers=blockers, warnings=warnings, pathResults=path_results, fileClassifications=classifications, requiresApproval=config.requireApproval, requiresSandboxPass=config.requireSandboxPass, requiresBackup=config.requireBackup, metadata={"configMode": config.mode, "totalBytes": diff.get("totalBytes", 0)})
