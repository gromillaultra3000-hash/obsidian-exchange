import uuid
from lumi.app.schemas.dialog import DialogResponse
from lumi.app.schemas.task import TaskRequest
from lumi.app.schemas.project_scanner import ProjectScanRequest
from lumi.app.schemas.patch_planner import PatchRequest
from lumi.app.schemas.sandbox import SandboxWorkspaceRequest, SandboxTestRunRequest, ApplyPreparationRequest
from lumi.app.dialog.command_parser import CommandParser
from lumi.app.dialog.response_builder import DialogResponseBuilder


class DialogRuntime:
    def __init__(self, lumi_runtime, session_store, message_store, history_store, explanation_builder, audit_log=None):
        self.lumi_runtime = lumi_runtime
        self.session_store = session_store
        self.message_store = message_store
        self.history_store = history_store
        self.explanation_builder = explanation_builder
        self.audit_log = audit_log
        self.parser = CommandParser()
        self.responses = DialogResponseBuilder()

    def send_message(self, session_id: str, text: str, metadata: dict | None = None) -> DialogResponse:
        session = self.session_store.get_session(session_id)
        if not session:
            return DialogResponse(responseId=str(uuid.uuid4()), sessionId=session_id, messageId="unknown", commandType="unknown", text="Session not found. Create a new session first.", shortAnswer="Session not found")
        if session.status == "closed":
            return DialogResponse(responseId=str(uuid.uuid4()), sessionId=session_id, messageId="unknown", commandType="unknown", text="This session is closed. Create a new session to continue.", shortAnswer="Session closed")
        user_msg = self.message_store.add_message(session_id, "user", text, metadata=metadata or {})
        command = self.parser.parse_message(session_id, user_msg)
        if self.audit_log:
            self.audit_log.add_entry("dialog_command_parsed", summary=f"Dialog command parsed: {command.commandType}", details={"sessionId": session_id, "commandType": command.commandType})
        handlers = {
            "resolve_task": self._resolve_task,
            "explain_decision": self._explain_decision,
            "show_history": self._show_history,
            "show_status": self._show_status,
            "approval_response": self._approval_response,
            "register_provider_help": self._provider_help,
            "register_action_help": self._action_help,
            "project_scan": self._project_scan,
            "show_project_summary": self._show_project_summary,
            "show_improvement_plan": self._show_improvement_plan,
            "patch_preview": self._patch_preview,
            "show_diff_preview": self._show_diff_preview,
            "show_test_plan": self._show_test_plan,
            "show_rollback_plan": self._show_rollback_plan,
            "create_sandbox": self._create_sandbox,
            "sandbox_test": self._sandbox_test,
            "apply_preview_to_sandbox": self._apply_preview_to_sandbox,
            "prepare_apply_package": self._prepare_apply_package,
            "show_apply_package": self._show_apply_package,
        }
        response = handlers.get(command.commandType, self._unknown)(session_id, user_msg.messageId, command)
        self.message_store.add_message(session_id, "lumi", response.text, command_type=response.commandType, linked_task_id=response.taskId, linked_decision_id=response.decisionId, linked_approval_prompt_id=response.approvalPrompt.get("promptId") if response.approvalPrompt else None, metadata={"responseId": response.responseId})
        if self.audit_log:
            self.audit_log.add_entry("dialog_response_created", task_id=response.taskId, decision_id=response.decisionId, summary=f"Dialog response created: {response.commandType}")
        return response

    def _resolve_task(self, session_id, message_id, command):
        task = command.taskRequest or TaskRequest(input=command.inputText, context={"sessionId": session_id}, requirements={}, metadata={"dialogSessionId": session_id, "dialogMessageId": message_id, "source": "dialog"})
        if self.audit_log:
            self.audit_log.add_entry("dialog_task_created", task_id=task.taskId, summary="Task created from dialog message", details={"sessionId": session_id})
        decision = self.lumi_runtime.resolve(task)
        exp_result = self.explanation_builder.build_explanation_response(decision.decisionId, "dialog")
        exp = exp_result.explanation if exp_result else None
        return self.responses.build_from_decision(session_id, message_id, decision, exp)

    def _explain_decision(self, session_id, message_id, command):
        target = command.targetDecisionId or command.metadata.get("decisionId")
        if not target:
            session = self.session_store.get_session(session_id)
            if session and session.linkedDecisionIds:
                target = session.linkedDecisionIds[-1]
        if not target:
            return self.responses.build_text_response(session_id, message_id, "explain_decision", "No decision found to explain. Send a task first.", "No decision available")
        result = self.explanation_builder.build_explanation_response(target, "human")
        if not result:
            return self.responses.build_text_response(session_id, message_id, "explain_decision", f"Decision {target} not found.", "Decision not found")
        return self.responses.build_explanation_response(session_id, message_id, result)

    def _show_history(self, session_id, message_id, command):
        session = self.session_store.get_session(session_id)
        records = []
        if session:
            for did in reversed(session.linkedDecisionIds[-10:]):
                rec = self.history_store.get_decision(did)
                if rec:
                    records.append(rec)
        if not records:
            records = list(reversed(self.history_store.list_decisions()[-5:]))
        if self.audit_log:
            self.audit_log.add_entry("dialog_history_requested", summary=f"History requested for session {session_id}")
        return self.responses.build_history_response(session_id, message_id, records)

    def _show_status(self, session_id, message_id, command):
        if self.audit_log:
            self.audit_log.add_entry("dialog_status_requested", summary="Runtime status requested via dialog")
        return self.responses.build_status_response(session_id, message_id, self.lumi_runtime.get_status())

    def _approval_response(self, session_id, message_id, command):
        text = command.inputText.lower()
        decision_value = "approve" if any(k in text for k in ["approve", "одобряю", "согласен", "подтверждаю"]) else "reject" if any(k in text for k in ["reject", "отклоняю", "не согласен", "отказываю"]) else "cancel"
        prompt_id = command.targetApprovalPromptId or command.metadata.get("promptId")
        if not prompt_id:
            session = self.session_store.get_session(session_id)
            if session:
                for did in reversed(session.linkedDecisionIds):
                    rec = self.history_store.get_decision(did)
                    if rec and rec.approvalPromptId:
                        prompt_id = rec.approvalPromptId
                        break
        if not prompt_id:
            return self.responses.build_text_response(session_id, message_id, "approval_response", "No pending approval prompt found. Provide a prompt id or create an action proposal first.", "No approval found")
        result = self.lumi_runtime.record_approval_decision(prompt_id, decision_value)
        if self.audit_log:
            self.audit_log.add_entry("dialog_approval_response_recorded", summary=f"Approval response recorded via dialog: {decision_value}", details={"promptId": prompt_id})
        if not result:
            return self.responses.build_text_response(session_id, message_id, "approval_response", f"Approval prompt {prompt_id} not found.", "Approval prompt not found")
        return self.responses.build_text_response(session_id, message_id, "approval_response", f"Approval decision '{decision_value}' recorded for prompt {prompt_id}.", f"Approval {decision_value} recorded")


    def _project_scan(self, session_id, message_id, command):
        project_id = command.metadata.get("projectId")
        if not project_id:
            return self.responses.build_text_response(session_id, message_id, "project_scan", "Project ID required. Register a project first or send metadata.projectId with the dialog message.", "Project ID required")
        request = ProjectScanRequest(projectId=project_id, scanMode="static_inspection", includeImprovementPlan=True, metadata={"source": "dialog", "dialogSessionId": session_id})
        result = self.lumi_runtime.scan_project(request)
        if self.audit_log:
            self.audit_log.add_entry("dialog_project_scan_requested", summary=f"Project scan requested via dialog: {project_id}", details={"scanId": result.scanId, "status": result.status})
        critical = sum(1 for issue in result.issues if issue.severity == "critical")
        text = f"Project scan for {project_id}: {result.status}. Issues found: {len(result.issues)} total, {critical} critical."
        if result.improvementPlan:
            text += f"\nRecommended next step: {result.improvementPlan.recommendedNextStep}\n{result.improvementPlan.summary}"
            if result.improvementPlan.approvalPrompt:
                text += "\nApproval prompt is available for the proposed preview action."
        if result.errors:
            text += "\nErrors: " + "; ".join(result.errors)
        return self.responses.build_text_response(session_id, message_id, "project_scan", text, f"Scan {result.status}: {len(result.issues)} issues", metadata={"projectScanResult": result.model_dump()}, decision_id=result.decisionId)

    def _show_project_summary(self, session_id, message_id, command):
        project_id = command.metadata.get("projectId")
        if not project_id:
            projects = self.lumi_runtime.list_projects()
            if not projects:
                return self.responses.build_text_response(session_id, message_id, "show_project_summary", "No registered projects found.", "No projects")
            lines = [f"Registered projects: {len(projects)}"] + [f"- {p.projectId}: {p.displayName} ({p.status})" for p in projects[:10]]
            return self.responses.build_text_response(session_id, message_id, "show_project_summary", "\n".join(lines), f"{len(projects)} project(s) registered")
        project = self.lumi_runtime.get_project(project_id)
        if not project:
            return self.responses.build_text_response(session_id, message_id, "show_project_summary", f"Project {project_id} not found.", "Project not found")
        inventory = self.lumi_runtime.get_project_inventory(project_id)
        text = f"Project {project.projectId}: {project.displayName}\nType: {project.projectType}\nStatus: {project.status}"
        if inventory:
            text += f"\nFiles: {inventory.filesCount}; Directories: {inventory.directoriesCount}; Extensions: {inventory.extensions}"
        else:
            text += "\nNo inventory yet. Run a project scan first."
        return self.responses.build_text_response(session_id, message_id, "show_project_summary", text, "Project summary")

    def _show_improvement_plan(self, session_id, message_id, command):
        project_id = command.metadata.get("projectId")
        if not project_id:
            return self.responses.build_text_response(session_id, message_id, "show_improvement_plan", "Project ID required to show an improvement plan.", "Project ID required")
        plan = self.lumi_runtime.get_project_improvement_plan(project_id)
        if not plan:
            return self.responses.build_text_response(session_id, message_id, "show_improvement_plan", f"No improvement plan found for {project_id}. Run a scan first.", "No improvement plan")
        lines = [plan.summary, f"Candidates: {len(plan.candidates)}", f"Recommended next step: {plan.recommendedNextStep}"]
        for c in plan.candidates[:5]:
            lines.append(f"- [{c.priority}] {c.title}: {c.summary}")
        return self.responses.build_text_response(session_id, message_id, "show_improvement_plan", "\n".join(lines), "Improvement plan", metadata={"improvementPlan": plan.model_dump()})


    def _patch_preview(self, session_id, message_id, command):
        project_id = command.metadata.get("projectId")
        if not project_id:
            return self.responses.build_text_response(session_id, message_id, "patch_preview", "Project ID required. Send metadata.projectId or include project:<id> in the message.", "Project ID required", metadata={"requiredNextStep": "provide_project_id"})
        request = PatchRequest(
            projectId=project_id,
            source="dialog",
            title=command.metadata.get("title", "Dialog Patch Preview Request"),
            summary=(command.inputText or "")[:500],
            targetFiles=command.metadata.get("targetFiles", []),
            requestedChanges=command.metadata.get("requestedChanges", [{"changeType": "unknown", "description": (command.inputText or "")[:200]}]),
            riskLevel=command.metadata.get("riskLevel", "unknown"),
            metadata={"dialogSessionId": session_id, "dialogMessageId": message_id},
        )
        result = self.lumi_runtime.plan_patch(request)
        if self.audit_log:
            self.audit_log.add_entry("dialog_patch_preview_requested", summary=f"Patch preview requested via dialog for {project_id}", details={"status": result.status})
        if result.status == "blocked":
            text = "Patch plan blocked: " + "; ".join(result.errors)
            return self.responses.build_text_response(session_id, message_id, "patch_preview", text, "Patch plan blocked", metadata={"patchPlanResult": result.model_dump()})
        proposal = result.patchProposal
        diff_id = result.diffPreview.diffPreviewId if result.diffPreview else None
        test_id = result.testPlan.testPlanId if result.testPlan else None
        rollback_id = result.rollbackMetadata.rollbackMetadataId if result.rollbackMetadata else None
        # Keep last ids in session metadata for follow-up commands.
        session = self.session_store.get_session(session_id)
        if session:
            session.metadata["lastPatchResult"] = result.model_dump()
        text = (
            f"Patch plan ready for {project_id}: {result.status}.\n"
            f"PatchProposal: {proposal.patchProposalId if proposal else 'N/A'}\n"
            f"DiffPreview: {diff_id or 'N/A'}\n"
            f"TestPlan: {test_id or 'N/A'}\n"
            f"RollbackMetadata: {rollback_id or 'N/A'}\n"
            "No files were changed. No tests were executed. This is preview-only."
        )
        if proposal and proposal.approvalPrompt:
            text += "\nApproval prompt is available for the proposed preview action."
        return self.responses.build_text_response(
            session_id, message_id, "patch_preview", text, f"Patch plan ready: {result.status}",
            metadata={"patchPlanResult": result.model_dump(), "patchProposalId": proposal.patchProposalId if proposal else None, "diffPreviewId": diff_id, "testPlanId": test_id, "rollbackMetadataId": rollback_id, "canApply": False, "canExecute": False},
            decision_id=result.decisionId,
        )

    def _show_diff_preview(self, session_id, message_id, command):
        diff_id = command.metadata.get("diffPreviewId")
        if not diff_id:
            session = self.session_store.get_session(session_id)
            last = (session.metadata or {}).get("lastPatchResult", {}) if session else {}
            diff_id = ((last.get("diffPreview") or {}).get("diffPreviewId") if isinstance(last, dict) else None)
        if not diff_id:
            return self.responses.build_text_response(session_id, message_id, "show_diff_preview", "No diff preview available. Prepare a patch preview first or provide diffPreviewId.", "No diff available")
        diff = self.lumi_runtime.get_diff_preview(diff_id)
        if self.audit_log:
            self.audit_log.add_entry("dialog_diff_preview_requested", summary=f"Diff preview requested via dialog: {diff_id}")
        if not diff:
            return self.responses.build_text_response(session_id, message_id, "show_diff_preview", f"Diff preview {diff_id} not found.", "Diff not found")
        lines = [f"Diff Preview: {diff.title}", f"Files changed: {diff.totalFilesChanged}; additions: {diff.totalAdditions}; removals: {diff.totalRemovals}; canApply: {diff.canApply}"]
        for file_diff in diff.fileDiffs[:3]:
            lines.append(f"- {file_diff.path} ({file_diff.changeType}): {file_diff.summary}; lines: {len(file_diff.lines)}")
        if len(diff.fileDiffs) > 3:
            lines.append(f"... and {len(diff.fileDiffs) - 3} more file(s).")
        return self.responses.build_text_response(session_id, message_id, "show_diff_preview", "\n".join(lines), f"Diff: {diff.totalFilesChanged} files", metadata={"diffPreview": diff.model_dump(), "canApply": False})

    def _show_test_plan(self, session_id, message_id, command):
        test_plan_id = command.metadata.get("testPlanId")
        if not test_plan_id:
            session = self.session_store.get_session(session_id)
            last = (session.metadata or {}).get("lastPatchResult", {}) if session else {}
            test_plan_id = ((last.get("testPlan") or {}).get("testPlanId") if isinstance(last, dict) else None)
        if not test_plan_id:
            return self.responses.build_text_response(session_id, message_id, "show_test_plan", "No test plan available. Prepare a patch preview first or provide testPlanId.", "No test plan")
        test_plan = self.lumi_runtime.get_test_plan(test_plan_id)
        if self.audit_log:
            self.audit_log.add_entry("dialog_test_plan_requested", summary=f"Test plan requested via dialog: {test_plan_id}")
        if not test_plan:
            return self.responses.build_text_response(session_id, message_id, "show_test_plan", f"Test plan {test_plan_id} not found.", "Test plan not found")
        lines = [f"Test Plan: {test_plan.title}", f"Steps: {len(test_plan.steps)}; canExecute: {test_plan.canExecute}"]
        for step in test_plan.steps:
            line = f"- {step.title}: {step.purpose}"
            if step.commandPreview:
                line += f" | command preview: {step.commandPreview}"
            lines.append(line)
        lines.append("No tests were executed. This is a dry-run preview only.")
        return self.responses.build_text_response(session_id, message_id, "show_test_plan", "\n".join(lines), f"Test plan: {len(test_plan.steps)} steps", metadata={"testPlan": test_plan.model_dump(), "canExecute": False})

    def _show_rollback_plan(self, session_id, message_id, command):
        rollback_id = command.metadata.get("rollbackMetadataId")
        if not rollback_id:
            session = self.session_store.get_session(session_id)
            last = (session.metadata or {}).get("lastPatchResult", {}) if session else {}
            rollback_id = ((last.get("rollbackMetadata") or {}).get("rollbackMetadataId") if isinstance(last, dict) else None)
        if not rollback_id:
            return self.responses.build_text_response(session_id, message_id, "show_rollback_plan", "No rollback metadata available. Prepare a patch preview first or provide rollbackMetadataId.", "No rollback metadata")
        rollback = self.lumi_runtime.get_rollback_metadata(rollback_id)
        if self.audit_log:
            self.audit_log.add_entry("dialog_rollback_plan_requested", summary=f"Rollback metadata requested via dialog: {rollback_id}")
        if not rollback:
            return self.responses.build_text_response(session_id, message_id, "show_rollback_plan", f"Rollback metadata {rollback_id} not found.", "Rollback not found")
        lines = [f"Rollback Metadata: {rollback.summary}", f"Affected files: {len(rollback.affectedFiles)}; canRollback: {rollback.canRollback}"]
        for step in rollback.rollbackSteps[:5]:
            lines.append(f"- {step.title}: {step.description}")
        lines.append("No rollback was executed. This is metadata preview only.")
        return self.responses.build_text_response(session_id, message_id, "show_rollback_plan", "\n".join(lines), f"Rollback: {len(rollback.rollbackSteps)} steps", metadata={"rollbackMetadata": rollback.model_dump(), "canRollback": False})


    def _create_sandbox(self, session_id, message_id, command):
        project_id = command.metadata.get("projectId")
        if not project_id:
            return self.responses.build_text_response(session_id, message_id, "create_sandbox", "Project ID required. Send metadata.projectId or include project:<id>.", "Project ID required", metadata={"requiredNextStep": "provide_project_id"})
        request = SandboxWorkspaceRequest(projectId=project_id, source="dialog", includeSnapshots=True, patchPlanResultId=command.metadata.get("patchPlanResultId"), diffPreviewId=command.metadata.get("diffPreviewId"), metadata={"dialogSessionId": session_id})
        try:
            workspace = self.lumi_runtime.create_sandbox_workspace(request)
            if self.audit_log:
                self.audit_log.add_entry("dialog_sandbox_workspace_requested", summary=f"Sandbox workspace requested via dialog: {project_id}", details={"workspaceId": workspace.workspaceId})
            session = self.session_store.get_session(session_id)
            if session:
                session.metadata["lastSandboxWorkspaceId"] = workspace.workspaceId
            text = f"Sandbox workspace created.\nWorkspace: {workspace.workspaceId}\nFiles: {len(workspace.files)}\nStatus: {workspace.status}\nNo host files were modified."
            return self.responses.build_text_response(session_id, message_id, "create_sandbox", text, f"Sandbox ready: {len(workspace.files)} files", metadata={"workspaceId": workspace.workspaceId, "workspace": workspace.model_dump(), "canAffectHost": False})
        except Exception as exc:
            return self.responses.build_text_response(session_id, message_id, "create_sandbox", f"Sandbox creation blocked: {exc}", "Sandbox creation blocked", metadata={"error": str(exc)})

    def _sandbox_test(self, session_id, message_id, command):
        session = self.session_store.get_session(session_id)
        workspace_id = command.metadata.get("workspaceId") or ((session.metadata or {}).get("lastSandboxWorkspaceId") if session else None)
        project_id = command.metadata.get("projectId")
        if not project_id and workspace_id:
            ws = self.lumi_runtime.get_sandbox_workspace(workspace_id)
            project_id = ws.projectId if ws else None
        if not project_id:
            return self.responses.build_text_response(session_id, message_id, "sandbox_test", "Project ID or workspaceId required for sandbox test.", "Project or workspace required", metadata={"requiredNextStep": "provide_project_id_or_workspace_id"})
        request = SandboxTestRunRequest(projectId=project_id, workspaceId=workspace_id, testPlanId=command.metadata.get("testPlanId"), commands=command.metadata.get("commands", ["pytest -q"]), mode=command.metadata.get("mode", "preview_only"), metadata={"dialogSessionId": session_id})
        try:
            result = self.lumi_runtime.run_sandbox_tests(request)
            if self.audit_log:
                self.audit_log.add_entry("dialog_sandbox_test_requested", summary="Sandbox test requested via dialog", details={"status": result.status})
            if session:
                session.metadata["lastSandboxTestRunResultId"] = result.testRunResultId
            allowed = sum(1 for c in result.commands if c.status == "allowed")
            blocked = sum(1 for c in result.commands if c.status == "blocked")
            text = f"Sandbox test result: {result.status}\nCommands allowed: {allowed}; blocked: {blocked}\n{result.summary}\nNo host files were modified."
            return self.responses.build_text_response(session_id, message_id, "sandbox_test", text, f"Sandbox test: {result.status}", metadata={"testRunResultId": result.testRunResultId, "testRunResult": result.model_dump(), "canAffectHost": False})
        except Exception as exc:
            return self.responses.build_text_response(session_id, message_id, "sandbox_test", f"Sandbox test blocked: {exc}", "Sandbox test blocked", metadata={"error": str(exc)})

    def _apply_preview_to_sandbox(self, session_id, message_id, command):
        session = self.session_store.get_session(session_id)
        workspace_id = command.metadata.get("workspaceId") or ((session.metadata or {}).get("lastSandboxWorkspaceId") if session else None)
        diff_id = command.metadata.get("diffPreviewId")
        if not diff_id and session:
            last = (session.metadata or {}).get("lastPatchResult", {})
            diff_id = ((last.get("diffPreview") or {}).get("diffPreviewId") if isinstance(last, dict) else None)
        if not workspace_id or not diff_id:
            return self.responses.build_text_response(session_id, message_id, "apply_preview_to_sandbox", "workspaceId and diffPreviewId are required.", "Missing IDs", metadata={"requiredNextStep": "provide_workspace_id_and_diff_preview_id"})
        try:
            result = self.lumi_runtime.apply_patch_preview_to_sandbox(workspace_id, diff_id)
            text = f"Diff preview applied to sandbox only.\nStatus: {result.status}\nFiles affected: {len(result.filesAffected)}\nCan affect host: {result.canAffectHost}\nNo host files were modified."
            return self.responses.build_text_response(session_id, message_id, "apply_preview_to_sandbox", text, f"Sandbox apply preview: {result.status}", metadata={"patchApplyPreview": result.model_dump(), "canAffectHost": False})
        except Exception as exc:
            return self.responses.build_text_response(session_id, message_id, "apply_preview_to_sandbox", f"Sandbox apply preview blocked: {exc}", "Apply preview blocked", metadata={"error": str(exc)})

    def _prepare_apply_package(self, session_id, message_id, command):
        session = self.session_store.get_session(session_id)
        project_id = command.metadata.get("projectId")
        last_patch = (session.metadata or {}).get("lastPatchResult", {}) if session else {}
        request = ApplyPreparationRequest(projectId=project_id or ((last_patch or {}).get("projectId") if isinstance(last_patch, dict) else ""), patchPlanResultId=command.metadata.get("patchPlanResultId") or ((last_patch or {}).get("resultId") if isinstance(last_patch, dict) else None), diffPreviewId=command.metadata.get("diffPreviewId") or (((last_patch or {}).get("diffPreview") or {}).get("diffPreviewId") if isinstance(last_patch, dict) else None), testRunResultId=command.metadata.get("testRunResultId") or ((session.metadata or {}).get("lastSandboxTestRunResultId") if session else None), rollbackMetadataId=command.metadata.get("rollbackMetadataId") or (((last_patch or {}).get("rollbackMetadata") or {}).get("rollbackMetadataId") if isinstance(last_patch, dict) else None), metadata={"dialogSessionId": session_id})
        if not request.projectId:
            return self.responses.build_text_response(session_id, message_id, "prepare_apply_package", "Project ID required to prepare apply package.", "Project ID required", metadata={"requiredNextStep": "provide_project_id"})
        try:
            package = self.lumi_runtime.prepare_apply_package(request)
            if self.audit_log:
                self.audit_log.add_entry("dialog_apply_preparation_requested", summary=f"Apply preparation requested via dialog: {request.projectId}", details={"applyPackageId": package.applyPackageId})
            if session:
                session.metadata["lastApplyPackageId"] = package.applyPackageId
            text = f"Apply preparation package created.\nPackage: {package.applyPackageId}\nStatus: {package.status}\nFiles affected: {len(package.filesAffected)}\nApproval required: {package.approvalRequired}\nCan apply to host: {package.canApplyToHost}\nNo host changes were made."
            if package.approvalPrompt:
                text += "\nApproval prompt is attached for review."
            return self.responses.build_text_response(session_id, message_id, "prepare_apply_package", text, f"Apply package: {package.status}", metadata={"applyPackageId": package.applyPackageId, "applyPackage": package.model_dump(), "canApplyToHost": False})
        except Exception as exc:
            return self.responses.build_text_response(session_id, message_id, "prepare_apply_package", f"Apply preparation blocked: {exc}", "Apply preparation blocked", metadata={"error": str(exc)})

    def _show_apply_package(self, session_id, message_id, command):
        session = self.session_store.get_session(session_id)
        package_id = command.metadata.get("applyPackageId") or ((session.metadata or {}).get("lastApplyPackageId") if session else None)
        if not package_id:
            return self.responses.build_text_response(session_id, message_id, "show_apply_package", "applyPackageId required or prepare an apply package first.", "Package ID required")
        package = self.lumi_runtime.get_apply_package(package_id)
        if not package:
            return self.responses.build_text_response(session_id, message_id, "show_apply_package", f"Apply package {package_id} not found.", "Package not found")
        review = self.lumi_runtime.apply_package_service.build_review_payload(package)
        text = f"Apply package review:\nPackage: {package.applyPackageId}\nProject: {package.projectId}\nStatus: {package.status}\nRisk: {package.riskLevel}\nFiles affected: {len(package.filesAffected)}\nApproval required: {package.approvalRequired}\nCan apply to host: {package.canApplyToHost}\nRollback available: {package.rollbackAvailable}\nNo host changes were made."
        return self.responses.build_text_response(session_id, message_id, "show_apply_package", text, f"Apply package: {package.status}", metadata={"applyPackage": review, "canApplyToHost": False})

    def _provider_help(self, session_id, message_id, command):
        text = "Register a provider with POST /providers. Required fields: providerId, displayName, providerType, apiFormat, capabilities, roles. Secret values should be passed only through protected references."
        return self.responses.build_text_response(session_id, message_id, "register_provider_help", text, "Provider registration help")

    def _action_help(self, session_id, message_id, command):
        text = "Register a host action with POST /actions/register. Include actionId, title, riskLevel, allowedModes, inputSchema, and whether approval or dry-run is supported."
        return self.responses.build_text_response(session_id, message_id, "register_action_help", text, "Action registration help")

    def _unknown(self, session_id, message_id, command):
        return self.responses.build_text_response(session_id, message_id, "unknown", "I could not classify this command. Ask for status, history, explanation, or send a task to resolve.", "Unknown command")
