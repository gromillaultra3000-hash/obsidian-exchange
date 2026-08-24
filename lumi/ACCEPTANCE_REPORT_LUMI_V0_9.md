# Lumi v0.9 Acceptance Report

Archive: `LUMI_V0_9_PATCH_PLANNER_DIFF_PREVIEW_TEST_ROLLBACK_FOUNDATION.zip`

Base: `LUMI_V0_8_PROJECT_SCANNER_IMPROVEMENT_RUNTIME_FOUNDATION.zip`

## Integrated scope

- Patch Request Normalizer
- Patch Safety Guard
- Patch Proposal Builder
- Synthetic Diff Preview Builder
- Test Plan Builder
- Test Runner Preview (dry-run only)
- Rollback Metadata Builder
- Patch Runtime
- API router `/patches/*`
- Dialog commands for patch preview, diff preview, test plan, rollback plan
- Integration events for patch preview, diff preview, and test plan requests
- Version metadata `0.9.0`
- Runtime counters for patch plans, diff previews, test plans, rollback metadata
- Documentation and examples

## Safety confirmations

- No local filesystem scanning.
- No direct file reads.
- No file writes.
- No patch apply.
- No test execution.
- No shell/subprocess execution.
- No git operations.
- No real external provider API calls.
- `PatchProposal.canApply` remains `false`.
- `DiffPreview.canApply` remains `false`.
- `FileDiffPreview.canApply` remains `false`.
- `TestPlan.canExecute` remains `false`.
- `TestRunPreview.canExecute` remains `false`.
- `RollbackMetadata.canRollback` remains `false`.
- Forbidden paths and path traversal are blocked.
- Secret-like content is redacted in patch/diff metadata and audit details.

## Checks

```bash
python -m compileall -q .
pytest -q
```

Result:

```text
163 passed
```

Additional check:

```bash
node --check sdk/javascript/src/*.js
node --check examples/integration/*.js
```

Result: passed.

## Known limitations

- In-memory storage only.
- Synthetic diff preview only.
- No real diff engine.
- No sandbox test execution.
- No approval-gated apply yet.
- No persistent database.
- No frontend UI.
