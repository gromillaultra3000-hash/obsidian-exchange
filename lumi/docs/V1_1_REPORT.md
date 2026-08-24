# Lumi v1.1 — UI Dashboard, Dialog Window & Integration Wizard Foundation

## Implemented

- Local web dashboard served by FastAPI at `/ui` and `/dashboard`.
- Static HTML/CSS/JS assets with no external CDN and no frontend build step.
- UI state endpoints: `/ui/state`, `/ui/panels`, `/ui/safety-labels`, `/ui/wizards/integration`, `/ui/wizards/project`.
- Overview, Dialog, Approvals, History, Integration, Project Scanner, Patch Planner, Sandbox, and API Status panels.
- Safety labels throughout the UI: no host writes, no real patch apply, approval required, sandbox only, no external network calls, secrets redacted.
- UI audit events for dashboard/state/panel/wizard access.

## Safety

The UI only calls existing backend REST endpoints. It does not execute commands, write files, apply patches, call external URLs, or bypass Action Gateway / policy checks. Approval buttons only record approval decisions.

## Limits

- No auth.
- No persistent UI state.
- No desktop native wrapper.
- No external provider runtime.
- No real host apply.
