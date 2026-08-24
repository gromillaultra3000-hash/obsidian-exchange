import uuid
from lumi.app.schemas.patch_planner import TestPlan, TestPlanStep

class TestPlanBuilder:
    def build_test_plan(self, project_profile, patch_proposal, inventory=None) -> TestPlan:
        steps = []
        project_type = getattr(project_profile, "projectType", "unknown")
        if project_type == "python":
            steps += [
                TestPlanStep(stepId=str(uuid.uuid4()), title="Python syntax check", commandPreview="python -m compileall -q .", purpose="Verify Python files compile", expectedResult="No syntax errors"),
                TestPlanStep(stepId=str(uuid.uuid4()), title="Python test suite", commandPreview="pytest -q", purpose="Run existing tests", expectedResult="All tests pass"),
            ]
        elif project_type in ["javascript", "typescript"]:
            steps += [
                TestPlanStep(stepId=str(uuid.uuid4()), title="JavaScript tests", commandPreview="npm test", purpose="Run existing test suite", expectedResult="All tests pass"),
                TestPlanStep(stepId=str(uuid.uuid4()), title="Build check", commandPreview="npm run build", purpose="Verify build", expectedResult="Build succeeds"),
                TestPlanStep(stepId=str(uuid.uuid4()), title="Lint check", commandPreview="npm run lint", purpose="Check code style", expectedResult="No lint errors"),
            ]
        else:
            steps.append(TestPlanStep(stepId=str(uuid.uuid4()), title="Manual smoke test", commandPreview="run existing test suite", purpose="Review basic behavior", expectedResult="Smoke test passes"))
        steps.append(TestPlanStep(stepId=str(uuid.uuid4()), title="Manual review", purpose="Review synthetic diff preview", expectedResult="Reviewer accepts planned changes"))
        return TestPlan(testPlanId=str(uuid.uuid4()), projectId=project_profile.projectId, patchProposalId=getattr(patch_proposal, "patchProposalId", None), title=f"Test Plan for {project_profile.displayName}", summary=f"Dry-run-only test plan with {len(steps)} step(s)", status="preview_ready", steps=steps, canExecute=False, executeBlockedReason="real_test_execution_disabled_in_v0_9")
