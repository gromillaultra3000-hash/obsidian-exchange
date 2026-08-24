from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SCOPES = ("bot", "relay", "relay-fastapi", "payment", "monitoring", "support_bot")

# Explicitly non-active compatibility/tooling files. Adding to this list needs
# an architectural decision; active runtime files are never allowed here.
ALLOW = {
    "bot/winback_fix_campaign.py",   # one-shot campaign utility
    "relay/utils/security.py",        # used only by legacy entrypoints
    "relay/core/db_runtime.py",       # the boundary implementation itself
}

tracked = subprocess.check_output(
    ["git", "ls-files", "*.py"], cwd=ROOT, text=True).splitlines()
found = set()
for rel in tracked:
    if rel.split("/", 1)[0] not in SCOPES:
        continue
    path = ROOT / rel
    if "sqlite3.connect" in path.read_text("utf-8"):
        found.add(rel)

unexpected = sorted(found - ALLOW)
missing = sorted(ALLOW - found)
assert not unexpected, f"active direct SQLite connections returned: {unexpected}"
assert not missing, f"stale DB boundary allowlist entries: {missing}"
print(f"DB boundary inventory: active direct SQLite=0, explicit legacy/tooling={len(found)-1}")
