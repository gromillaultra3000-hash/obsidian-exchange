import os, re
from pathlib import Path
from lumi.app.schemas.persistence import StorageConfig

class StorageConfigService:
    def __init__(self, config: StorageConfig | None = None):
        self._config = config or StorageConfig()
        self._valid = re.compile(r"^[A-Za-z0-9_-]+$")
    def get_default_config(self) -> StorageConfig:
        return self._config
    def sanitize_profile_id(self, profile_id: str) -> str:
        if not profile_id: return ""
        profile_id = profile_id.strip()
        if not self._valid.match(profile_id): return ""
        if ".." in profile_id or "/" in profile_id or "\\" in profile_id: return ""
        return profile_id
    def resolve_data_dir(self, config: StorageConfig | None = None) -> str:
        config = config or self._config
        return str(Path(config.dataDir).resolve())
    def resolve_profile_dir(self, profile_id: str, config: StorageConfig | None = None) -> str:
        safe = self.sanitize_profile_id(profile_id)
        if not safe: raise ValueError(f"Invalid profile ID: {profile_id}")
        base = Path(self.resolve_data_dir(config)).resolve()
        path = (base / safe).resolve()
        if not str(path).startswith(str(base)): raise ValueError("profile path escapes data dir")
        return str(path)
    def resolve_sqlite_path(self, profile_id: str, config: StorageConfig | None = None) -> str:
        return str(Path(self.resolve_profile_dir(profile_id, config)) / "lumi_state.sqlite")
    def ensure_profile_dirs(self, profile_id: str, config: StorageConfig | None = None):
        profile_dir = Path(self.resolve_profile_dir(profile_id, config))
        (profile_dir / "exports").mkdir(parents=True, exist_ok=True)
        return profile_dir
