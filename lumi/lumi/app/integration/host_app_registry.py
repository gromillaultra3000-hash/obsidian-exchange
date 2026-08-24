from datetime import datetime, timezone
from typing import List, Optional
from lumi.app.schemas.integration import HostAppManifest, HostAppProfile
from lumi.app.providers.redaction import RedactionUtil


class HostAppRegistry:
    def __init__(self, audit_log=None, redaction: RedactionUtil | None = None):
        self._hosts: dict[str, HostAppProfile] = {}
        self.audit_log = audit_log
        self.redaction = redaction or RedactionUtil()

    def register_host(self, manifest: HostAppManifest) -> HostAppProfile:
        now = datetime.now(timezone.utc).isoformat()
        safe_manifest = self._redact_manifest(manifest)
        if manifest.hostAppId in self._hosts:
            profile = self._hosts[manifest.hostAppId]
            profile.manifest = safe_manifest
            profile.displayName = manifest.displayName
            profile.appType = manifest.appType
            profile.status = "active" if profile.status != "disabled" else "active"
            profile.lastSeenAt = now
            profile.metadata = self.redaction.redact_dict(manifest.metadata)
            if self.audit_log:
                self.audit_log.add_entry("host_app_seen", summary=f"Host app {manifest.hostAppId} seen")
            return profile
        profile = HostAppProfile(
            hostAppId=manifest.hostAppId,
            displayName=manifest.displayName,
            appType=manifest.appType,
            status="active",
            manifest=safe_manifest,
            registeredAt=now,
            lastSeenAt=now,
            metadata=self.redaction.redact_dict(manifest.metadata),
        )
        self._hosts[manifest.hostAppId] = profile
        if self.audit_log:
            self.audit_log.add_entry("host_app_registered", summary=f"Host app {manifest.hostAppId} registered", details={"manifest": self.redaction.redact_model(safe_manifest)})
        return profile

    def get_host(self, host_app_id: str) -> Optional[HostAppProfile]:
        return self._hosts.get(host_app_id)

    def list_hosts(self) -> List[HostAppProfile]:
        return list(self._hosts.values())

    def enable_host(self, host_app_id: str) -> Optional[HostAppProfile]:
        host = self._hosts.get(host_app_id)
        if host:
            host.status = "active"
            host.lastSeenAt = datetime.now(timezone.utc).isoformat()
            if self.audit_log:
                self.audit_log.add_entry("host_app_enabled", summary=f"Host app {host_app_id} enabled")
        return host

    def disable_host(self, host_app_id: str) -> Optional[HostAppProfile]:
        host = self._hosts.get(host_app_id)
        if host:
            host.status = "disabled"
            host.lastSeenAt = datetime.now(timezone.utc).isoformat()
            if self.audit_log:
                self.audit_log.add_entry("host_app_disabled", summary=f"Host app {host_app_id} disabled")
        return host

    def update_last_seen(self, host_app_id: str) -> Optional[HostAppProfile]:
        host = self._hosts.get(host_app_id)
        if host:
            host.lastSeenAt = datetime.now(timezone.utc).isoformat()
            if self.audit_log:
                self.audit_log.add_entry("host_app_seen", summary=f"Host app {host_app_id} seen")
        return host

    def host_exists(self, host_app_id: str) -> bool:
        return host_app_id in self._hosts

    def _redact_manifest(self, manifest: HostAppManifest) -> HostAppManifest:
        data = manifest.model_dump()
        data["callbacks"] = self.redaction.redact_dict(data.get("callbacks", {}))
        data["metadata"] = self.redaction.redact_dict(data.get("metadata", {}))
        return HostAppManifest(**data)

    def clear_for_tests(self):
        self._hosts.clear()
