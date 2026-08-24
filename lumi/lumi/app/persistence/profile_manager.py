from datetime import datetime, timezone
from lumi.app.schemas.persistence import RuntimeProfile
from lumi.app.providers.redaction import RedactionUtil

class ProfileManager:
    def __init__(self, storage_config, audit_log=None, redaction: RedactionUtil | None = None):
        self.storage_config=storage_config; self.audit_log=audit_log; self.redaction=redaction or RedactionUtil()
        self._profiles={}; self._active_profile_id="default"
    def ensure_default_profile(self):
        if "default" not in self._profiles:
            now=datetime.now(timezone.utc).isoformat()
            self._profiles["default"]=RuntimeProfile(profileId="default",displayName="Default Profile",status="active",createdAt=now,updatedAt=now,storageBackend="sqlite",storagePath=self.storage_config.resolve_sqlite_path("default"))
            if self.audit_log: self.audit_log.add_entry("profile_created", summary="Default profile created")
        return self._profiles["default"]
    def create_profile(self, profile_id: str, display_name: str | None = None):
        safe=self.storage_config.sanitize_profile_id(profile_id)
        if not safe: raise ValueError(f"Invalid profile ID: {profile_id}")
        if safe in self._profiles: raise ValueError(f"Profile {safe} already exists")
        self.storage_config.ensure_profile_dirs(safe)
        now=datetime.now(timezone.utc).isoformat()
        profile=RuntimeProfile(profileId=safe,displayName=display_name or safe,status="active",createdAt=now,updatedAt=now,storageBackend="sqlite",storagePath=self.storage_config.resolve_sqlite_path(safe),metadata={})
        self._profiles[safe]=profile
        if self.audit_log: self.audit_log.add_entry("profile_created", summary=f"Profile {safe} created")
        return profile
    def get_profile(self, profile_id: str): return self._profiles.get(profile_id)
    def list_profiles(self): return list(self._profiles.values())
    def set_active_profile(self, profile_id: str):
        if profile_id not in self._profiles: raise ValueError(f"Profile {profile_id} not found")
        self._active_profile_id=profile_id
        self._profiles[profile_id].updatedAt=datetime.now(timezone.utc).isoformat()
        if self.audit_log: self.audit_log.add_entry("profile_activated", summary=f"Profile {profile_id} activated")
        return self._profiles[profile_id]
    def get_active_profile(self): return self._profiles.get(self._active_profile_id) or self.ensure_default_profile()
    def archive_profile(self, profile_id: str):
        p=self.get_profile(profile_id)
        if not p: raise ValueError(f"Profile {profile_id} not found")
        if profile_id == "default": raise ValueError("Cannot archive default profile")
        p.status="archived"; p.updatedAt=datetime.now(timezone.utc).isoformat()
        if self.audit_log: self.audit_log.add_entry("profile_archived", summary=f"Profile {profile_id} archived")
        return p
    def reset_profile(self, profile_id: str):
        p=self.get_profile(profile_id)
        if not p: raise ValueError(f"Profile {profile_id} not found")
        p.updatedAt=datetime.now(timezone.utc).isoformat()
        if self.audit_log: self.audit_log.add_entry("profile_reset", summary=f"Profile {profile_id} reset")
        return p
    def clear_for_tests(self): self._profiles.clear(); self._active_profile_id="default"
