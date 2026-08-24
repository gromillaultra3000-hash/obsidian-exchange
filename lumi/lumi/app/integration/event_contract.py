import uuid
from lumi.app.schemas.integration import HostEvent, HostEventResult
from lumi.app.schemas.task import TaskRequest
from lumi.app.providers.redaction import RedactionUtil


class HostEventProcessor:
    def __init__(self, runtime, host_registry, audit_log=None, redaction: RedactionUtil | None = None):
        self.runtime = runtime
        self.host_registry = host_registry
        self.audit_log = audit_log
        self.redaction = redaction or RedactionUtil()

    def process_event(self, event: HostEvent) -> HostEventResult:
        result_id = str(uuid.uuid4())
        if self.audit_log:
            self.audit_log.add_entry("host_event_received", summary=f"Host event {event.eventId} received", details={"eventType": event.eventType, "payload": self.redaction.redact_dict(event.payload)})
        host = self.host_registry.get_host(event.hostAppId)
        if not host:
            if self.audit_log:
                self.audit_log.add_entry("host_event_rejected", summary=f"Unknown host app: {event.hostAppId}")
            return HostEventResult(eventResultId=result_id, eventId=event.eventId, accepted=False, status="rejected", errors=[f"Unknown host app: {event.hostAppId}"])
        if host.status == "disabled":
            if self.audit_log:
                self.audit_log.add_entry("host_event_rejected", summary=f"Host app disabled: {event.hostAppId}")
            return HostEventResult(eventResultId=result_id, eventId=event.eventId, accepted=False, status="rejected", errors=[f"Host app {event.hostAppId} is disabled"])
        self.host_registry.update_last_seen(event.hostAppId)
        try:
            if event.eventType == "user_message":
                result = self._user_message(event, result_id)
            elif event.eventType == "error_log":
                result = self._error_log(event, result_id)
            elif event.eventType == "action_requested":
                result = self._action_requested(event, result_id)
            elif event.eventType == "approval_response":
                result = self._approval_response(event, result_id)
            else:
                result = self._custom(event, result_id)
            if self.audit_log:
                self.audit_log.add_entry("host_event_processed", summary=f"Host event {event.eventId} processed", details={"status": result.status})
            return result
        except Exception as exc:
            if self.audit_log:
                self.audit_log.add_entry("host_event_rejected", summary=f"Host event failed: {exc}")
            return HostEventResult(eventResultId=result_id, eventId=event.eventId, accepted=False, status="error", errors=[str(exc)])

    def _user_message(self, event: HostEvent, result_id: str) -> HostEventResult:
        text = event.payload.get("text") or event.payload.get("message") or ""
        session_id = event.sessionId
        if not session_id:
            session = self.runtime.create_dialog_session(host_app_id=event.hostAppId, title=f"Host session {event.hostAppId}")
            session_id = session.sessionId
        response = self.runtime.send_dialog_message(session_id, text, {"hostEventId": event.eventId})
        return HostEventResult(eventResultId=result_id, eventId=event.eventId, accepted=True, taskId=response.taskId, decisionId=response.decisionId, dialogResponse=response.model_dump(), status="processed", metadata={"sessionId": session_id})

    def _error_log(self, event: HostEvent, result_id: str) -> HostEventResult:
        payload = self.redaction.redact_dict(event.payload)
        error_text = payload.get("errorText") or payload.get("message") or str(payload)
        task = TaskRequest(input=f"Analyze this error log and suggest a safe next step: {error_text}", context={"hostAppId": event.hostAppId, "eventId": event.eventId, "payload": payload}, metadata={"source": "host_event", "eventType": "error_log"})
        decision = self.runtime.resolve(task)
        return HostEventResult(eventResultId=result_id, eventId=event.eventId, accepted=True, taskId=decision.taskId, decisionId=decision.decisionId, status="processed")

    def _action_requested(self, event: HostEvent, result_id: str) -> HostEventResult:
        action_id = event.payload.get("actionId")
        if not action_id:
            return HostEventResult(eventResultId=result_id, eventId=event.eventId, accepted=False, status="rejected", errors=["Missing actionId"])
        result = self.runtime.propose_action(action_id, proposed_input=event.payload.get("input", {}), requested_mode=event.payload.get("mode", "proposal"))
        return HostEventResult(eventResultId=result_id, eventId=event.eventId, accepted=result.status not in ["blocked", "failed"], status=result.status, errors=result.errors, metadata={"actionGatewayResult": result.model_dump()})

    def _approval_response(self, event: HostEvent, result_id: str) -> HostEventResult:
        prompt_id = event.payload.get("promptId")
        decision = event.payload.get("decision", "reject")
        if not prompt_id:
            return HostEventResult(eventResultId=result_id, eventId=event.eventId, accepted=False, status="rejected", errors=["Missing promptId"])
        record = self.runtime.record_approval_decision(prompt_id, decision, event.payload.get("userId"), event.payload.get("reason"))
        return HostEventResult(eventResultId=result_id, eventId=event.eventId, accepted=record is not None, status="processed" if record else "failed")

    def _custom(self, event: HostEvent, result_id: str) -> HostEventResult:
        payload = self.redaction.redact_dict(event.payload)
        subtype = payload.get("subtype")
        if subtype == "project_manifest":
            from lumi.app.schemas.project_scanner import ProjectManifest
            manifest_data = payload.get("projectManifest") or {}
            try:
                manifest = ProjectManifest(**manifest_data)
                validation = self.runtime.project_manifest_validator.validate_manifest(manifest)
                if not validation["valid"]:
                    return HostEventResult(eventResultId=result_id, eventId=event.eventId, accepted=False, status="rejected", errors=validation["errors"])
                self.runtime.register_project(manifest)
                if self.audit_log:
                    self.audit_log.add_entry("integration_project_manifest_received", summary=f"Project manifest received: {manifest.projectId}")
                return HostEventResult(eventResultId=result_id, eventId=event.eventId, accepted=True, status="processed", metadata={"projectId": manifest.projectId, "warnings": validation.get("warnings", [])})
            except Exception as exc:
                return HostEventResult(eventResultId=result_id, eventId=event.eventId, accepted=False, status="rejected", errors=[str(exc)])
        if subtype == "project_snapshot":
            from lumi.app.schemas.project_scanner import FileSnapshot
            project_id = payload.get("projectId")
            if not project_id or not self.runtime.get_project(project_id):
                return HostEventResult(eventResultId=result_id, eventId=event.eventId, accepted=False, status="rejected", errors=["Unknown or missing projectId"])
            snapshots = [FileSnapshot(**s) for s in payload.get("snapshots", [])]
            self.runtime.add_file_snapshots(project_id, snapshots)
            if self.audit_log:
                self.audit_log.add_entry("integration_project_snapshot_received", summary=f"Project snapshots received: {project_id}", details={"count": len(snapshots)})
            return HostEventResult(eventResultId=result_id, eventId=event.eventId, accepted=True, status="processed", metadata={"projectId": project_id, "snapshotsCount": len(snapshots)})
        if subtype == "project_scan_request":
            from lumi.app.schemas.project_scanner import ProjectScanRequest
            try:
                request = ProjectScanRequest(projectId=payload.get("projectId", ""), scanMode=payload.get("scanMode", "static_inspection"), includeImprovementPlan=payload.get("includeImprovementPlan", True), metadata={"source": "integration_event", "hostEventId": event.eventId})
                result = self.runtime.scan_project(request)
                if self.audit_log:
                    self.audit_log.add_entry("integration_project_scan_requested", summary=f"Project scan requested: {request.projectId}")
                return HostEventResult(eventResultId=result_id, eventId=event.eventId, accepted=result.status == "completed", status=result.status, decisionId=result.decisionId, metadata={"scanResult": result.model_dump()})
            except Exception as exc:
                return HostEventResult(eventResultId=result_id, eventId=event.eventId, accepted=False, status="rejected", errors=[str(exc)])
        if subtype == "patch_preview_request":
            from lumi.app.schemas.patch_planner import PatchRequest
            project_id = payload.get("projectId")
            if not project_id or not self.runtime.get_project(project_id):
                return HostEventResult(eventResultId=result_id, eventId=event.eventId, accepted=False, status="rejected", errors=["Unknown or missing projectId"])
            request = PatchRequest(
                projectId=project_id,
                source="integration_event",
                title=payload.get("title", "Integration Patch Preview Request"),
                summary=payload.get("summary", ""),
                targetFiles=payload.get("targetFiles", []),
                requestedChanges=payload.get("requestedChanges", []),
                riskLevel=payload.get("riskLevel", "unknown"),
                metadata={"hostEventId": event.eventId},
            )
            result = self.runtime.plan_patch(request)
            if self.audit_log:
                self.audit_log.add_entry("integration_patch_preview_requested", summary=f"Patch preview requested: {project_id}")
            return HostEventResult(eventResultId=result_id, eventId=event.eventId, accepted=result.status not in ["blocked", "failed"], status=result.status, decisionId=result.decisionId, metadata={"patchPlanResult": result.model_dump()})
        if subtype == "diff_preview_request":
            diff_id = payload.get("diffPreviewId")
            if not diff_id:
                return HostEventResult(eventResultId=result_id, eventId=event.eventId, accepted=False, status="rejected", errors=["Missing diffPreviewId"])
            diff = self.runtime.get_diff_preview(diff_id)
            if self.audit_log:
                self.audit_log.add_entry("integration_diff_preview_requested", summary=f"Diff preview requested: {diff_id}")
            return HostEventResult(eventResultId=result_id, eventId=event.eventId, accepted=diff is not None, status="processed" if diff else "not_found", metadata={"diffPreview": diff.model_dump() if diff else None})
        if subtype == "test_plan_request":
            test_plan_id = payload.get("testPlanId")
            if not test_plan_id:
                return HostEventResult(eventResultId=result_id, eventId=event.eventId, accepted=False, status="rejected", errors=["Missing testPlanId"])
            plan = self.runtime.get_test_plan(test_plan_id)
            if self.audit_log:
                self.audit_log.add_entry("integration_test_plan_requested", summary=f"Test plan requested: {test_plan_id}")
            return HostEventResult(eventResultId=result_id, eventId=event.eventId, accepted=plan is not None, status="processed" if plan else "not_found", metadata={"testPlan": plan.model_dump() if plan else None})

        if subtype == "sandbox_workspace_request":
            from lumi.app.schemas.sandbox import SandboxWorkspaceRequest
            project_id = payload.get("projectId")
            if not project_id or not self.runtime.get_project(project_id):
                return HostEventResult(eventResultId=result_id, eventId=event.eventId, accepted=False, status="rejected", errors=["Unknown or missing projectId"])
            request = SandboxWorkspaceRequest(projectId=project_id, source="integration_event", patchPlanResultId=payload.get("patchPlanResultId"), diffPreviewId=payload.get("diffPreviewId"), includeSnapshots=payload.get("includeSnapshots", True), metadata={"hostEventId": event.eventId})
            workspace = self.runtime.create_sandbox_workspace(request)
            if self.audit_log:
                self.audit_log.add_entry("integration_sandbox_workspace_requested", summary=f"Sandbox workspace requested via integration: {project_id}")
            return HostEventResult(eventResultId=result_id, eventId=event.eventId, accepted=True, status="processed", metadata={"workspace": workspace.model_dump()})
        if subtype == "sandbox_test_request":
            from lumi.app.schemas.sandbox import SandboxTestRunRequest
            request = SandboxTestRunRequest(projectId=payload.get("projectId", ""), workspaceId=payload.get("workspaceId"), testPlanId=payload.get("testPlanId"), commands=payload.get("commands", []), mode=payload.get("mode", "preview_only"), metadata={"hostEventId": event.eventId})
            result = self.runtime.run_sandbox_tests(request)
            if self.audit_log:
                self.audit_log.add_entry("integration_sandbox_test_requested", summary="Sandbox test requested via integration")
            return HostEventResult(eventResultId=result_id, eventId=event.eventId, accepted=result.status != "blocked", status=result.status, metadata={"testRunResult": result.model_dump()})
        if subtype == "apply_preparation_request":
            from lumi.app.schemas.sandbox import ApplyPreparationRequest
            request = ApplyPreparationRequest(projectId=payload.get("projectId", ""), patchPlanResultId=payload.get("patchPlanResultId"), diffPreviewId=payload.get("diffPreviewId"), testRunResultId=payload.get("testRunResultId"), rollbackMetadataId=payload.get("rollbackMetadataId"), metadata={"hostEventId": event.eventId})
            package = self.runtime.prepare_apply_package(request)
            if self.audit_log:
                self.audit_log.add_entry("integration_apply_preparation_requested", summary="Apply preparation requested via integration")
            return HostEventResult(eventResultId=result_id, eventId=event.eventId, accepted=package.status not in ["blocked", "failed"], status=package.status, metadata={"applyPackage": package.model_dump()})
        if subtype == "persistence_save_request":
            from lumi.app.schemas.persistence import PersistenceSaveRequest
            req = PersistenceSaveRequest(profileId=payload.get("profileId", "default"), includeAudit=payload.get("includeAudit", True), includeSnapshots=payload.get("includeSnapshots", True), metadata={"hostEventId": event.eventId})
            result = self.runtime.save_state(req)
            if self.audit_log:
                self.audit_log.add_entry("integration_persistence_save_requested", summary="Persistence save requested via integration")
            return HostEventResult(eventResultId=result_id, eventId=event.eventId, accepted=True, status="processed", metadata={"saveResult": result.model_dump()})
        if subtype == "persistence_export_request":
            from lumi.app.schemas.persistence import ExportSnapshotRequest
            req = ExportSnapshotRequest(profileId=payload.get("profileId", "default"), includeAudit=payload.get("includeAudit", True), includeSnapshots=payload.get("includeSnapshots", True), metadata={"hostEventId": event.eventId})
            result = self.runtime.export_state_snapshot(req)
            if self.audit_log:
                self.audit_log.add_entry("integration_persistence_export_requested", summary="Persistence export requested via integration")
            return HostEventResult(eventResultId=result_id, eventId=event.eventId, accepted=True, status="processed", metadata={"exportResult": result.model_dump()})

        task = TaskRequest(input=f"Process custom host event: {event.eventType}", context={"hostAppId": event.hostAppId, "eventId": event.eventId, "payload": payload}, metadata={"source": "host_event", "eventType": event.eventType})
        decision = self.runtime.resolve(task)
        return HostEventResult(eventResultId=result_id, eventId=event.eventId, accepted=True, taskId=decision.taskId, decisionId=decision.decisionId, status="processed")
