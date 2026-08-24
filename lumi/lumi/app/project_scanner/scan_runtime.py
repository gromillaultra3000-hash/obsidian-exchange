import uuid
from lumi.app.schemas.project_scanner import ProjectScanRequest, ProjectScanResult, ProjectInventory, ProjectIssue, ImprovementPlan
from lumi.app.schemas.task import TaskRequest

class ProjectScanRuntime:
    def __init__(self, runtime, registry, snapshot_store, inventory_builder, static_inspector, issue_detector, candidate_builder, improvement_planner, patch_preview_builder, audit_log, redaction):
        self.runtime = runtime
        self.registry = registry
        self.snapshot_store = snapshot_store
        self.inventory_builder = inventory_builder
        self.static_inspector = static_inspector
        self.issue_detector = issue_detector
        self.candidate_builder = candidate_builder
        self.improvement_planner = improvement_planner
        self.patch_preview_builder = patch_preview_builder
        self.audit_log = audit_log
        self.redaction = redaction
        self._latest_inventory: dict[str, ProjectInventory] = {}
        self._latest_issues: dict[str, list[ProjectIssue]] = {}
        self._latest_plans: dict[str, ImprovementPlan] = {}
        self._scan_count = 0

    @property
    def scan_count(self):
        return self._scan_count

    def scan_project(self, request: ProjectScanRequest) -> ProjectScanResult:
        scan_id = str(uuid.uuid4())
        if self.audit_log:
            self.audit_log.add_entry("project_scan_started", summary=f"Project scan started: {request.projectId}", details={"scanId": scan_id, "scanMode": request.scanMode})
        profile = self.registry.get_project(request.projectId)
        if not profile:
            return self._blocked(scan_id, request, [f"Project {request.projectId} not found"])
        if profile.status != "active":
            return self._blocked(scan_id, request, [f"Project {request.projectId} is not active"])
        if request.scanMode not in profile.manifest.allowedScanModes:
            return self._blocked(scan_id, request, [f"Scan mode {request.scanMode} not allowed for project"])
        snapshots = self.snapshot_store.list_snapshots(request.projectId)
        if request.scanMode in {"snapshot", "static_inspection", "improvement_plan"} and not snapshots:
            return self._blocked(scan_id, request, ["No file snapshots available for this scan mode"])
        try:
            inventory = self.inventory_builder.build_inventory(profile, snapshots)
            self._latest_inventory[request.projectId] = inventory
            if self.audit_log:
                self.audit_log.add_entry("project_inventory_built", summary=f"Project inventory built: {request.projectId}", details={"filesCount": inventory.filesCount})
            issues: list[ProjectIssue] = []
            plan = None
            previews = []
            if request.scanMode != "manifest_only":
                raw_issues = self.static_inspector.inspect(profile, inventory, snapshots)
                issues = self.issue_detector.deduplicate_issues(self.issue_detector.normalize_issues(raw_issues))
                self._latest_issues[request.projectId] = issues
                if self.audit_log:
                    self.audit_log.add_entry("project_static_inspection_completed", summary=f"Static inspection completed: {request.projectId}")
                    self.audit_log.add_entry("project_issues_detected", summary=f"Project issues detected: {len(issues)}", details={"counts": self.issue_detector.severity_counts(issues)})
                if request.includeImprovementPlan:
                    candidates = self.candidate_builder.build_candidates(request.projectId, issues)
                    if self.audit_log:
                        self.audit_log.add_entry("improvement_candidates_created", summary=f"Improvement candidates created: {len(candidates)}")
                    plan = self.improvement_planner.build_plan(profile, scan_id, issues, candidates)
                    self._latest_plans[request.projectId] = plan
                    if self.audit_log:
                        self.audit_log.add_entry("improvement_plan_created", summary=f"Improvement plan created: {plan.planId}")
                    previews = self.patch_preview_builder.build_previews(request.projectId, candidates, issues)
                    if self.audit_log:
                        self.audit_log.add_entry("patch_plan_preview_created", summary=f"Patch previews created: {len(previews)}")
            decision_id = self._create_review_decision(request, scan_id, issues, plan)
            self.registry.update_last_scan(request.projectId)
            self._scan_count += 1
            if self.audit_log:
                self.audit_log.add_entry("project_scan_completed", summary=f"Project scan completed: {scan_id}")
            return ProjectScanResult(scanId=scan_id, projectId=request.projectId, status="completed", scanMode=request.scanMode, inventory=inventory, issues=issues, improvementPlan=plan, patchPlanPreviews=previews, decisionId=decision_id, metadata={"source": "project_scanner", "projectId": request.projectId, "scanId": scan_id, "totalIssues": len(issues), "criticalIssues": sum(1 for i in issues if i.severity == "critical"), "candidateCount": len(plan.candidates) if plan else 0})
        except Exception as exc:
            if self.audit_log:
                self.audit_log.add_entry("project_scan_failed", summary=f"Project scan failed: {exc}")
            return ProjectScanResult(scanId=scan_id, projectId=request.projectId, status="failed", scanMode=request.scanMode, errors=[str(exc)])

    def _blocked(self, scan_id, request, errors):
        if self.audit_log:
            self.audit_log.add_entry("project_scan_blocked", summary=f"Project scan blocked: {request.projectId}", details={"errors": errors})
        return ProjectScanResult(scanId=scan_id, projectId=request.projectId, status="blocked", scanMode=request.scanMode, errors=errors)

    def _create_review_decision(self, request, scan_id, issues, plan):
        # Optional: use existing pipeline only when provider route exists. Fail safely if not.
        try:
            task = TaskRequest(
                input=f"Review improvement plan for host project {request.projectId}",
                context={"projectId": request.projectId, "scanId": scan_id, "totalIssues": len(issues), "criticalIssues": sum(1 for i in issues if i.severity == "critical"), "candidateSummaries": [c.summary for c in (plan.candidates if plan else [])[:5]]},
                requirements={},
                metadata={"source": "project_scanner", "projectId": request.projectId, "scanId": scan_id, "totalIssues": len(issues), "criticalIssues": sum(1 for i in issues if i.severity == "critical"), "candidateCount": len(plan.candidates) if plan else 0},
            )
            decision = self.runtime.resolve(task)
            return decision.decisionId
        except Exception:
            return None

    def get_latest_inventory(self, project_id: str): return self._latest_inventory.get(project_id)
    def get_latest_issues(self, project_id: str): return self._latest_issues.get(project_id, [])
    def get_latest_improvement_plan(self, project_id: str): return self._latest_plans.get(project_id)
    def clear_for_tests(self):
        self._latest_inventory.clear(); self._latest_issues.clear(); self._latest_plans.clear(); self._scan_count = 0
