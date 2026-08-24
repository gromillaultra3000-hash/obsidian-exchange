import uuid
from collections import defaultdict
from typing import List
from lumi.app.schemas.project_scanner import ProjectIssue, ProjectInventory, FileSnapshot, HostProjectProfile

SECRET_MARKERS = ["api_key", "apikey", "secret", "token", "password", "bearer", "authorization"]
RISKY_PATHS = ["node_modules", "__pycache__", ".pytest_cache", "/dist/", "/build/", ".venv"]
SUSPICIOUS_NAME_MARKERS = ["backup", "old", "copy", "final_final", "temp", "debug"]

class StaticInspector:
    def inspect(self, profile: HostProjectProfile, inventory: ProjectInventory, snapshots: List[FileSnapshot]) -> List[ProjectIssue]:
        issues: list[ProjectIssue] = []
        def add(category, severity, title, description, file_path=None, evidence=None, suggested=None):
            issues.append(ProjectIssue(issueId=str(uuid.uuid4()), projectId=profile.projectId, filePath=file_path, category=category, severity=severity, title=title, description=description, evidence=evidence or [], suggestedFix=suggested))
        if not inventory.suspectedDocs:
            add("documentation", "warning", "Missing README or documentation", "Potential issue detected: no README.md or docs path was detected.", suggested="Add or update README.md/documentation.")
        if not inventory.suspectedTestFiles:
            add("testing", "warning", "Missing test files", "Indicator suggests the project has no detected tests.", suggested="Add basic test coverage.")
        if not inventory.suspectedConfigFiles:
            add("configuration", "warning", "Missing configuration files", "No common configuration files were detected.", suggested="Add explicit project configuration.")
        if not inventory.suspectedEntryPoints:
            add("structure", "warning", "No clear entry point", "No common application entrypoint was detected.", suggested="Clarify or document the application entrypoint.")
        file_names = defaultdict(list)
        for snap in snapshots:
            file_names[snap.fileName.lower()].append(snap.path)
            lower_path = snap.path.lower()
            lower_file = snap.fileName.lower()
            preview = snap.contentPreview or ""
            lower_preview = preview.lower()
            if snap.sizeBytes == 0:
                add("quality", "info", "Empty file detected", f"Potential issue detected: {snap.path} is empty.", snap.path, suggested="Review whether this file is needed.")
            if snap.sizeBytes > 2_000_000:
                add("maintainability", "error", "Very large file", f"Indicator suggests {snap.path} is very large (>2 MB).", snap.path, evidence=[f"sizeBytes={snap.sizeBytes}"], suggested="Review and consider splitting the file.")
            elif snap.sizeBytes > 500_000:
                add("maintainability", "warning", "Large file", f"Indicator suggests {snap.path} is large (>500 KB).", snap.path, evidence=[f"sizeBytes={snap.sizeBytes}"], suggested="Review file size and modularity.")
            if "todo" in lower_preview or "fixme" in lower_preview:
                add("maintainability", "info", "TODO/FIXME markers found", f"Review recommended: {snap.path} contains TODO/FIXME markers.", snap.path, evidence=["TODO/FIXME marker detected"], suggested="Review TODO/FIXME items.")
            if any(marker in lower_preview for marker in SECRET_MARKERS) or "***redacted***" in lower_preview:
                add("security", "critical", "Potential secret-like content detected", f"Potential issue detected: {snap.path} contains secret-like markers.", snap.path, evidence=["Secret-like pattern detected in redacted preview"], suggested="Remove or secure sensitive-looking content.")
            if lower_file == ".env" or lower_file.endswith(".env"):
                add("security", "error", "Environment file snapshot detected", f"Review recommended: environment file {snap.path} is included in snapshot.", snap.path, suggested="Exclude .env files and use .env.example.")
            if any(marker in lower_path for marker in RISKY_PATHS) or snap.isGenerated:
                add("quality", "warning", "Generated/cache path included", f"Potential issue detected: generated/cache path included: {snap.path}", snap.path, suggested="Exclude generated/cache folders from snapshots.")
            if any(marker in lower_file for marker in SUSPICIOUS_NAME_MARKERS):
                add("maintainability", "info", "Suspicious filename marker", f"Review recommended: filename suggests temporary/backup/debug file: {snap.path}", snap.path, suggested="Confirm whether this file belongs in the project.")
        for filename, paths in file_names.items():
            if filename and len(paths) > 1:
                add("maintainability", "info", "Duplicate filename detected", f"Indicator suggests duplicate file names for {filename} across directories.", evidence=paths[:5], suggested="Review duplicate files for confusion or accidental copies.")
        return issues
