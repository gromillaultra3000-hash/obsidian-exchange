from __future__ import annotations
import os
from pathlib import PurePosixPath
from lumi.app.schemas.real_apply import PathGuardResult

class PathGuard:
    def __init__(self, config_service, audit_log=None):
        self.config_service = config_service
        self.audit_log = audit_log

    def _norm_rel(self, path: str) -> str:
        return str(PurePosixPath(path.replace('\\', '/')))

    def check_path(self, workspace, target_path: str) -> PathGuardResult:
        config = self.config_service.get_config()
        blockers, warnings = [], []
        raw = str(target_path or "")
        rel_in = self._norm_rel(raw)
        if not raw or raw.strip() == "":
            blockers.append("Path is required")
        if os.path.isabs(raw):
            candidate = os.path.realpath(os.path.abspath(raw))
        else:
            candidate = os.path.realpath(os.path.abspath(os.path.join(workspace.normalizedRootPath, rel_in)))
        root = os.path.realpath(os.path.abspath(workspace.normalizedRootPath))
        try:
            common = os.path.commonpath([root, candidate])
        except ValueError:
            common = ""
        if common != root:
            blockers.append("Path outside workspace")
        relative = os.path.relpath(candidate, root) if common == root else rel_in
        relative_posix = relative.replace('\\', '/')
        parts = relative_posix.split('/')
        if '..' in parts or relative_posix.startswith('../') or '/..' in relative_posix:
            blockers.append("Path traversal detected")
        low = relative_posix.lower()
        for frag in config.blockedPathFragments:
            if frag.lower() in low:
                blockers.append(f"Blocked path fragment: {frag}")
        ext = os.path.splitext(low)[1]
        if ext in {e.lower() for e in config.blockedExtensions}:
            blockers.append(f"Blocked extension: {ext}")
        if config.allowedExtensions and ext and ext not in {e.lower() for e in config.allowedExtensions}:
            blockers.append(f"Extension not allowed: {ext}")
        if workspace.allowedPathPrefixes and not any(low.startswith(p.lower().replace('\\','/')) for p in workspace.allowedPathPrefixes):
            blockers.append("Path not in allowed prefixes")
        if workspace.blockedPathPrefixes and any(low.startswith(p.lower().replace('\\','/')) for p in workspace.blockedPathPrefixes):
            blockers.append("Path blocked by workspace blocked prefixes")
        allowed = not blockers
        if self.audit_log:
            self.audit_log.add_entry("path_guard_checked" if allowed else "path_guard_blocked", summary=f"Path guard {'allowed' if allowed else 'blocked'}: {relative_posix}", details={"blockers": blockers})
        return PathGuardResult(path=raw, normalizedPath=candidate, relativePath=relative_posix, allowed=allowed, blockers=blockers, warnings=warnings)
