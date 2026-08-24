import uuid
from lumi.app.schemas.patch_planner import TestRunPreview, TestPlan

class TestRunnerPreview:
    def preview_test_run(self, project_id: str, patch_proposal, test_plan: TestPlan) -> TestRunPreview:
        return TestRunPreview(testRunPreviewId=str(uuid.uuid4()), projectId=project_id, patchProposalId=getattr(patch_proposal, "patchProposalId", None), testPlanId=test_plan.testPlanId, status="preview_ready", plannedSteps=test_plan.steps, simulatedResult="No tests executed. This is a dry-run preview only. No subprocess, shell, npm, pytest, or command execution was performed.", canExecute=False, executeBlockedReason="real_test_execution_disabled_in_v0_9")
