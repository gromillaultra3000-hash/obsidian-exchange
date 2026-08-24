import uuid
import re
from lumi.app.schemas.sandbox import CommandPreview

class CommandExecutionGuard:
    def __init__(self):
        self.allowlist_python = ["python -m compileall -q .", "pytest -q", "pytest", "python -m pytest -q", "python -m pytest"]
        self.allowlist_javascript = ["npm test", "npm run test", "npm run build", "npm run lint"]
        self.allowlist_generic = ["echo sandbox-check", "true"]
        self.blocklist_tokens = ["rm", "rmdir", "del", "mv", "cp", "chmod", "chown", "curl", "wget", "ssh", "scp", "git", "pip install", "npm install", "poetry add", "yarn add", "apt-get", "sudo", "kill", "shutdown", "reboot", "bash", "powershell", "cmd", "python -c", "python3 -c", "node -e"]
        self.shell_operators = [";", "&&", "||", "|", ">", "<", "`", "$(", "${"]

    def sanitize_command(self, command: str) -> str:
        sanitized = (command or "").strip()[:240]
        sanitized = re.sub(r'(api[_\s-]?key|secret|token|password|bearer)\s*[:=]\s*\S+', r'\1=***REDACTED***', sanitized, flags=re.IGNORECASE)
        return sanitized

    def is_allowlisted(self, command: str, project_type: str | None = None) -> bool:
        cmd = (command or "").strip().lower()
        if project_type == "python":
            allowed = self.allowlist_python + self.allowlist_generic
        elif project_type in ["javascript", "typescript"]:
            allowed = self.allowlist_javascript + self.allowlist_generic
        else:
            allowed = self.allowlist_python + self.allowlist_javascript + self.allowlist_generic
        return cmd in [a.lower() for a in allowed]

    def validate_command(self, command: str, project_type: str | None = None) -> CommandPreview:
        cid = str(uuid.uuid4())
        sanitized = self.sanitize_command(command)
        raw = command or ""
        lower = raw.lower().strip()
        for op in self.shell_operators:
            if op in raw:
                return CommandPreview(commandId=cid, commandPreview=sanitized, purpose="Command validation", allowlisted=False, blockedReason=f"Shell operator '{op}' is not allowed")
        if lower.startswith("/") or lower.startswith("\\"):
            return CommandPreview(commandId=cid, commandPreview=sanitized, purpose="Command validation", allowlisted=False, blockedReason="Absolute path execution is not allowed")
        if ".." in lower:
            return CommandPreview(commandId=cid, commandPreview=sanitized, purpose="Command validation", allowlisted=False, blockedReason="Path traversal is not allowed")
        for token in self.blocklist_tokens:
            if lower == token or lower.startswith(token + " ") or (" " + token + " ") in lower:
                return CommandPreview(commandId=cid, commandPreview=sanitized, purpose="Command validation", allowlisted=False, blockedReason=f"Blocked command pattern: {token}")
        if self.is_allowlisted(raw, project_type):
            return CommandPreview(commandId=cid, commandPreview=sanitized, purpose="Command validation", allowlisted=True)
        return CommandPreview(commandId=cid, commandPreview=sanitized, purpose="Command validation", allowlisted=False, blockedReason="Command is not in the sandbox allowlist")

    def blocked_reason(self, command: str) -> str | None:
        p = self.validate_command(command)
        return None if p.allowlisted else p.blockedReason
