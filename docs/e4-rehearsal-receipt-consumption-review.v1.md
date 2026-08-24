# E4 receipt-consumption boundary review v1

Date: 2026-08-22 UTC
Route: E4 / disposable full-snapshot rehearsal
Decision: `REVIEW_PASS_BOUNDED_PREREQUISITE_WITH_EXECUTOR_BLOCKERS`

## Scope

The slice adds owner-window fields and owner-approved opaque reference digests
to the synthetic receipt, plus
`relay/core/e4_rehearsal_receipt_consumption.py`. The test-only SQLite ledger
atomically records one exact receipt consumption and rejects replay. It does
not execute Docker, PostgreSQL, snapshot loading, migrations, routes or money
actions.

## Independent reviews

- `agent:01a02a71-78ab-74b0-ab3a-ad4fee60e67e` performed a context-aware route,
  contract and next-slice review. It accepted formal receipt consumption as
  the one bounded next item and found target/reference, expiry, plan-phase and
  synthetic-owner landmines; the target-format and reference-binding findings
  were fixed in this slice.
- `agent:01a02a71-7958-74e2-88a5-c529bca65072` performed an independent
  security/DevOps review. It accepted the ledger as a prerequisite and kept
  owner authentication, trusted time, content-bound artifacts, full phase
  parity, Docker hardening, TOCTOU and cleanup ownership as executor blockers.

## Verification

- stdlib-only first consume → replay block → record validation: PASS;
- concurrent double claim: one `CONSUMED`, one `REPLAY_BLOCKED`;
- fault before commit rolls back; fault after commit blocks retry;
- owner window, plan/target/snapshot/boundary and opaque handle drift fail closed;
- `py_compile` and `git diff --check`: PASS;
- `pytest`: unavailable in the host (`No module named pytest`), not claimed.

## Status

`IN_PROGRESS`, non-production and non-authoritative. No real owner approval,
authenticated receipt, pre-existing production-disconnected snapshot or
executor exists. The next canonical item is the owner-gated fresh rehearsal
with those exact prerequisites; no production contact or mutation is allowed.
