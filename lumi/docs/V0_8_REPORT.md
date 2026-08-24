# Lumi v0.8 — Project Scanner & Improvement Runtime Foundation

## Base
Built on accepted `LUMI_V0_7_SDK_REST_INTEGRATION_SIDECAR_FOUNDATION.zip`.

## Added
- Host Project Registry
- Project Manifest Validator
- File Snapshot Store with preview redaction/truncation
- Project Inventory Builder
- Static Inspector with read-only issue detection
- Issue Detector with deduplication/count helpers
- Improvement Candidate Builder
- Improvement Planner with optional Action Gateway proposal for `create_patch_preview`
- Patch Plan Preview with `canApply=false`
- Project Scan Runtime
- `/projects/*` API
- Integration events for project manifest/snapshot/scan request
- Dialog commands for project scan/project summary/improvement plan

## Safety
- No local filesystem scanning
- No recursive path reads
- No code execution
- No file writes
- No real patch apply
- Patch preview only
- Secret-like content is redacted and surfaced as security findings without exposing raw values

## Checks
- `python -m compileall -q .`
- `pytest -q` — 155 passed
