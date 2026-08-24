import uuid
from lumi.app.schemas.sandbox import SandboxTestRunRequest, SandboxTestRunResult, SandboxCommandResult, SandboxWorkspace
from lumi.app.schemas.project_scanner import HostProjectProfile
from lumi.app.schemas.patch_planner import TestPlan
from lumi.app.sandbox.command_guard import CommandExecutionGuard
from lumi.app.providers.redaction import RedactionUtil

class SandboxTestRunner:
    def __init__(self, command_guard: CommandExecutionGuard, audit_log=None, redaction: RedactionUtil | None = None):
        self.command_guard = command_guard
        self.audit_log = audit_log
        self.redaction = redaction or RedactionUtil()

    def run_tests(self, request: SandboxTestRunRequest, workspace: SandboxWorkspace | None = None, project_profile: HostProjectProfile | None = None, test_plan: TestPlan | None = None) -> SandboxTestRunResult:
        tid = str(uuid.uuid4())
        project_type = project_profile.projectType if project_profile else None
        commands = list(request.commands or [])
        if not commands and test_plan:
            commands = [s.commandPreview for s in test_plan.steps if s.commandPreview]
        if not commands:
            commands = ["echo sandbox-check"]
        if self.audit_log:
            self.audit_log.add_entry("sandbox_test_run_requested", summary="Sandbox test run requested", details={"mode": request.mode, "commandsCount": len(commands)})
        results = []
        errors = []
        warnings = []
        if request.mode == "controlled_sandbox":
            warnings.append("controlled_sandbox_execution_not_available")
        for command in commands:
            preview = self.command_guard.validate_command(command, project_type)
            if not preview.allowlisted:
                results.append(SandboxCommandResult(commandId=str(uuid.uuid4()), commandPreview=preview.commandPreview, status="blocked", blockedReason=preview.blockedReason))
                continue
            if request.mode == "controlled_sandbox":
                results.append(SandboxCommandResult(commandId=str(uuid.uuid4()), commandPreview=preview.commandPreview, status="blocked", blockedReason="controlled_sandbox_execution_not_available"))
                continue
            results.append(SandboxCommandResult(commandId=str(uuid.uuid4()), commandPreview=preview.commandPreview, status="allowed", stdoutPreview=None, stderrPreview=None, blockedReason=None))
        if any(r.status == "blocked" for r in results):
            status = "blocked"
            passed = False
            summary = f"{sum(1 for r in results if r.status == 'blocked')} command(s) blocked by sandbox guard"
        else:
            status = "completed"
            passed = True
            summary = f"{len(results)} command(s) validated in preview-only mode. No tests executed."
        if self.audit_log:
            self.audit_log.add_entry("sandbox_test_run_completed" if status == "completed" else "sandbox_test_run_blocked", summary=f"Sandbox test run {tid}: {status}")
        return SandboxTestRunResult(testRunResultId=tid, projectId=request.projectId, workspaceId=request.workspaceId, testPlanId=request.testPlanId, status=status, mode=request.mode, commands=results, summary=summary, passed=passed, canAffectHost=False, warnings=warnings, errors=errors)
