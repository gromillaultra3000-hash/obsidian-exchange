import uuid
from datetime import datetime, timezone
from typing import List
from lumi.app.schemas.project_scanner import ProjectInventory, FileSnapshot, HostProjectProfile

class ProjectInventoryBuilder:
    def build_inventory(self, profile: HostProjectProfile, snapshots: List[FileSnapshot]) -> ProjectInventory:
        directories: set[str] = set()
        extensions: dict[str, int] = {}
        entry_points: list[str] = []
        tests: list[str] = []
        configs: list[str] = []
        docs: list[str] = []
        risky_generated = []
        for snap in snapshots:
            parts = snap.path.split("/")
            if len(parts) > 1:
                for i in range(1, len(parts)):
                    directories.add("/".join(parts[:i]))
            else:
                directories.add("/")
            ext = snap.extension or "(none)"
            extensions[ext] = extensions.get(ext, 0) + 1
            lower_path = snap.path.lower()
            lower_file = snap.fileName.lower()
            if lower_file in {"main.py", "app.py", "run.py", "server.py", "index.js", "main.js"} or lower_path == "src/index.js":
                entry_points.append(snap.path)
            if lower_file.startswith("test_") or lower_file.endswith("_test.py") or ".test." in lower_file or ".spec." in lower_file or lower_path.startswith("tests/") or "/tests/" in lower_path:
                tests.append(snap.path)
            if lower_file in {"pyproject.toml", "requirements.txt", "package.json", "tsconfig.json", "vite.config.js", "dockerfile", ".env.example"}:
                configs.append(snap.path)
            if lower_file == "readme.md" or lower_path.startswith("docs/") or "/docs/" in lower_path:
                docs.append(snap.path)
            if any(marker in lower_path for marker in ["node_modules", "__pycache__", ".pytest_cache", "/dist/", "/build/", ".venv"]):
                risky_generated.append(snap.path)
        warnings = []
        if not docs:
            warnings.append("No README or documentation files detected")
        if not tests:
            warnings.append("No test files detected")
        if not configs:
            warnings.append("No configuration files detected")
        if not entry_points:
            warnings.append("No clear entry point detected")
        if risky_generated:
            warnings.append("Risky generated/cache folders are included in snapshots")
        largest = sorted([{"path": s.path, "fileName": s.fileName, "sizeBytes": s.sizeBytes} for s in snapshots], key=lambda x: x["sizeBytes"], reverse=True)[:10]
        return ProjectInventory(
            inventoryId=str(uuid.uuid4()), projectId=profile.projectId,
            createdAt=datetime.now(timezone.utc).isoformat(), filesCount=len(snapshots),
            directoriesCount=len(directories), extensions=extensions, largestFiles=largest,
            suspectedEntryPoints=entry_points, suspectedTestFiles=tests,
            suspectedConfigFiles=configs, suspectedDocs=docs, warnings=warnings,
        )
