from typing import List, Any
from lumi.app.schemas.ui import UiDashboardSummary, UiPanelConfig, UiSafetyLabel, UiWizardState, UiWizardStep
from lumi.app.version.metadata import VERSION, CAPABILITIES
from lumi.app.providers.redaction import RedactionUtil


def _dump_model(obj: Any) -> dict:
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if hasattr(obj, "dict"):
        return obj.dict()
    return dict(obj) if isinstance(obj, dict) else {}

def _get(obj: Any, name: str, default=0):
    snake = []
    for ch in name:
        if ch.isupper():
            snake.append('_')
            snake.append(ch.lower())
        else:
            snake.append(ch)
    snake_name = ''.join(snake).lstrip('_')
    return getattr(obj, name, getattr(obj, snake_name, default))

class UiStateService:
    def __init__(self, audit_log=None, redaction: RedactionUtil | None = None):
        self.audit_log = audit_log
        self.redaction = redaction or RedactionUtil()

    def get_dashboard_summary(self, runtime) -> UiDashboardSummary:
        status = runtime.get_status()
        health_data = {"status": "ok", "module": "Lumi", "version": VERSION}
        counts = {
            "providers": _get(status, "providersCount"),
            "enabledProviders": _get(status, "enabledProvidersCount"),
            "actions": _get(status, "actionsCount"),
            "enabledActions": _get(status, "enabledActionsCount"),
            "decisions": _get(status, "decisionsCount"),
            "dialogSessions": _get(status, "dialogSessionsCount"),
            "activeDialogSessions": _get(status, "activeDialogSessionsCount"),
            "hostApps": _get(status, "hostAppsCount"),
            "activeHostApps": _get(status, "activeHostAppsCount"),
            "projects": _get(status, "projectsCount"),
            "activeProjects": _get(status, "activeProjectsCount"),
            "patchPlans": _get(status, "patchPlansCount"),
            "sandboxWorkspaces": _get(status, "sandboxWorkspacesCount"),
            "applyPackages": _get(status, "applyPackagesCount"),
            "pendingApprovals": _get(status, "pendingApprovalPromptsCount"),
            "fileSnapshots": _get(status, "fileSnapshotsCount"),
            "testResults": _get(status, "sandboxTestResultsCount"),
        }
        safety_labels = [
            "No host writes",
            "No real patch apply",
            "Approval required",
            "Sandbox only",
            "No external network calls",
            "Secrets redacted",
        ]
        warnings = []
        if counts["pendingApprovals"] > 0:
            warnings.append(f"{counts['pendingApprovals']} approval(s) pending")
        if counts["enabledProviders"] == 0:
            warnings.append("No providers enabled")
        if counts["activeProjects"] == 0:
            warnings.append("No active projects registered")
        if self.audit_log:
            self.audit_log.add_entry("ui_state_requested", summary="UI dashboard summary requested")
        return UiDashboardSummary(
            version=VERSION,
            runtimeStatus=self.redaction.redact_dict(_dump_model(status)),
            health=health_data,
            counts=counts,
            safetyLabels=safety_labels,
            warnings=warnings,
            metadata={"capabilitiesPreview": CAPABILITIES[-20:]},
        )

    def get_panel_configs(self) -> List[UiPanelConfig]:
        return [
            UiPanelConfig(panelId="overview", title="Overview", description="Runtime status and counts", requiredEndpoints=["/health", "/version", "/runtime/status"]),
            UiPanelConfig(panelId="dialog", title="Dialog Window", description="Conversational control panel", requiredEndpoints=["/dialog/sessions", "/dialog/sessions/{id}/message"]),
            UiPanelConfig(panelId="approvals", title="Approvals", description="Approval prompts", requiredEndpoints=["/actions/approvals"]),
            UiPanelConfig(panelId="history", title="Decision History", description="History and explanations", requiredEndpoints=["/history/decisions", "/explain/{decisionId}"]),
            UiPanelConfig(panelId="integration", title="Integration Wizard", description="Host app integration", requiredEndpoints=["/integration/handshake", "/integration/hosts/register"]),
            UiPanelConfig(panelId="projects", title="Project Scanner", description="Register and scan projects", requiredEndpoints=["/projects/register", "/projects/scan"]),
            UiPanelConfig(panelId="patches", title="Patch Planner", description="Patch and diff preview", requiredEndpoints=["/patches/plan"]),
            UiPanelConfig(panelId="sandbox", title="Sandbox & Apply Prep", description="Sandbox tests and apply package", requiredEndpoints=["/sandbox/workspaces", "/sandbox/tests/run", "/sandbox/apply/prepare"]),
            UiPanelConfig(panelId="apiStatus", title="API Status", description="Endpoint status overview", requiredEndpoints=["/health"]),
        ]

    def get_safety_labels(self) -> List[UiSafetyLabel]:
        return [
            UiSafetyLabel(labelId="no_host_writes", title="No host writes", level="critical", description="Lumi does not write to host project files."),
            UiSafetyLabel(labelId="no_real_patch_apply", title="No real patch apply", level="critical", description="Patch apply remains disabled; previews only."),
            UiSafetyLabel(labelId="approval_required", title="Approval required", level="warning", description="High-risk proposals require explicit approval."),
            UiSafetyLabel(labelId="sandbox_only", title="Sandbox only", level="warning", description="Verification happens in sandbox/preview layers."),
            UiSafetyLabel(labelId="no_external_network_calls", title="No external network calls", level="info", description="UI uses same-origin backend endpoints only."),
            UiSafetyLabel(labelId="secrets_redacted", title="Secrets redacted", level="critical", description="Secret-like values are masked in UI responses and logs."),
        ]

    def get_integration_wizard_state(self) -> UiWizardState:
        return UiWizardState(
            wizardId="integration_wizard",
            title="Host Application Integration Wizard",
            currentStepId="prepare_manifest",
            steps=[
                UiWizardStep(stepId="prepare_manifest", title="Prepare Host Manifest", status="active"),
                UiWizardStep(stepId="handshake", title="Integration Handshake"),
                UiWizardStep(stepId="register_providers", title="Register Providers"),
                UiWizardStep(stepId="register_actions", title="Register Actions"),
                UiWizardStep(stepId="verify", title="Verify Integration"),
            ],
        )

    def get_project_wizard_state(self) -> UiWizardState:
        return UiWizardState(
            wizardId="project_wizard",
            title="Project Scanner Wizard",
            currentStepId="register_project",
            steps=[
                UiWizardStep(stepId="register_project", title="Register Project", status="active"),
                UiWizardStep(stepId="upload_snapshots", title="Upload File Snapshots"),
                UiWizardStep(stepId="run_scan", title="Run Project Scan"),
                UiWizardStep(stepId="review_issues", title="Review Issues"),
            ],
        )
