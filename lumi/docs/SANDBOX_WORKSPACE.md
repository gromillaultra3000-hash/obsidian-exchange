# Sandbox Workspace

A sandbox workspace is created from host-provided file snapshots. Lumi does not scan or read the local filesystem directly. Binary previews are ignored, content previews are redacted and limited, and the workspace is an in-memory representation for safe review.

Recommended flow:

1. Register a project.
2. Upload file snapshots.
3. Create a sandbox workspace with `POST /sandbox/workspaces`.
4. Optionally apply a diff preview to the sandbox representation.

No host files are modified.
