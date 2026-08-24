# Project Scanner

The project scanner accepts host-supplied project manifests and file snapshots. It builds an inventory, detects indicators, and prepares improvement plans. It never reads the local filesystem directly and never writes files.

Flow:

1. Register a project manifest with `POST /projects/register`.
2. Send file snapshots with `POST /projects/{projectId}/snapshots`.
3. Run a scan with `POST /projects/scan`.
4. Review inventory, issues, improvement plan, and patch plan preview.

Patch plan previews are not diffs and cannot be applied in v0.8.
