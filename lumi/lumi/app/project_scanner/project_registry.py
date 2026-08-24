from datetime import datetime, timezone
from typing import List, Optional
from lumi.app.schemas.project_scanner import ProjectManifest, HostProjectProfile
from lumi.app.providers.redaction import RedactionUtil

class HostProjectRegistry:
    def __init__(self, audit_log=None, redaction: RedactionUtil | None = None):
        self._projects: dict[str, HostProjectProfile] = {}
        self.audit_log = audit_log
        self.redaction = redaction or RedactionUtil()

    def register_project(self, manifest: ProjectManifest) -> HostProjectProfile:
        now = datetime.now(timezone.utc).isoformat()
        safe_manifest = self._redact_manifest(manifest)
        if manifest.projectId in self._projects:
            profile = self._projects[manifest.projectId]
            profile.manifest = safe_manifest
            profile.displayName = manifest.displayName
            profile.projectType = manifest.projectType
            profile.metadata = self.redaction.redact_dict(manifest.metadata)
            if self.audit_log:
                self.audit_log.add_entry("project_seen", summary=f"Project {manifest.projectId} seen", details={"projectId": manifest.projectId})
            return profile
        profile = HostProjectProfile(
            projectId=manifest.projectId, hostAppId=manifest.hostAppId,
            displayName=manifest.displayName, projectType=manifest.projectType,
            status="active", manifest=safe_manifest, registeredAt=now,
            metadata=self.redaction.redact_dict(manifest.metadata),
        )
        self._projects[manifest.projectId] = profile
        if self.audit_log:
            self.audit_log.add_entry("project_registered", summary=f"Project {manifest.projectId} registered", details={"projectId": manifest.projectId})
        return profile

    def get_project(self, project_id: str) -> Optional[HostProjectProfile]:
        return self._projects.get(project_id)

    def list_projects(self) -> List[HostProjectProfile]:
        return list(self._projects.values())

    def enable_project(self, project_id: str) -> Optional[HostProjectProfile]:
        profile = self._projects.get(project_id)
        if profile:
            profile.status = "active"
            if self.audit_log:
                self.audit_log.add_entry("project_enabled", summary=f"Project {project_id} enabled")
        return profile

    def disable_project(self, project_id: str) -> Optional[HostProjectProfile]:
        profile = self._projects.get(project_id)
        if profile:
            profile.status = "disabled"
            if self.audit_log:
                self.audit_log.add_entry("project_disabled", summary=f"Project {project_id} disabled")
        return profile

    def update_last_scan(self, project_id: str):
        profile = self._projects.get(project_id)
        if profile:
            profile.lastScanAt = datetime.now(timezone.utc).isoformat()
            if self.audit_log:
                self.audit_log.add_entry("project_scan_timestamp_updated", summary=f"Project scan timestamp updated: {project_id}")
        return profile

    def project_exists(self, project_id: str) -> bool:
        return project_id in self._projects

    def _redact_manifest(self, manifest: ProjectManifest) -> ProjectManifest:
        data = manifest.model_dump()
        data["metadata"] = self.redaction.redact_dict(data.get("metadata") or {})
        return ProjectManifest(**data)

    def clear_for_tests(self):
        self._projects.clear()
