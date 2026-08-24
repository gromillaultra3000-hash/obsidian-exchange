# ADR 0039: E4 rehearsal receipt consumption boundary

Status: `IN_PROGRESS`; test-only keyless boundary, no production authority

## Decision

An E4 disposable full-snapshot rehearsal may consume an authorization receipt
only through a durable, explicitly temporary SQLite ledger. The consume call
must validate the exact plan, receipt, owner approval, target-bound runner
boundary, snapshot digest and owner-approved opaque snapshot/key-reference
digests before it writes anything. The receipt now carries the owner-approval
validity window so a consumer can verify freshness without trusting an
unbound `approvalId`.

The ledger inserts one immutable `CONSUMED` row under `BEGIN IMMEDIATE`, keyed
by `receiptId`. A successful first claim returns `CONSUMED`; every later claim
returns `REPLAY_BLOCKED` and cannot authorize a retry. A fault before commit
rolls back the claim. A fault after commit leaves the receipt consumed, so an
ambiguous caller outcome also blocks retry and requires a new owner-approved
invocation. The record binds the receipt, plan, target, snapshot and exact
runner-boundary digest and has no action effect.

## Deliberate limits

The module is explicitly test-only. It accepts only `/tmp` or `/var/tmp`
ledger paths, rejects production-like path markers and has no Docker,
PostgreSQL, network, environment, secret or HTTP surface. It does not execute
the runner, create a disposable target, load a snapshot, apply proposal 025,
connect a route or promote E4. Synthetic approvals and fixtures in tests are
not owner authentication or production evidence.

## Evidence and remaining gate

`docs/e4-rehearsal-receipt-consumption.v1.json` records the bounded evidence.
The focused stdlib harness covers first-consume/replay-block, concurrent
claims, before/after-commit faults, exact binding and record tamper rejection.
The host has no `pytest`, so pytest is not reported as passed.

The E4 gate remains `IN_PROGRESS`. Independent reviews accepted this as a
bounded prerequisite and retained these executor blockers: no authenticated
owner/trust-root decision, no trusted clock at the first fixture mutation, no
content/ownership proof for eventual snapshot/key material, a seven-phase
boundary that differs from the frozen twelve-step plan, incomplete Docker
hardening, target-name TOCTOU and cleanup ownership risks. The next canonical
item is an owner-gated fresh rehearsal using a genuinely pre-existing,
production-disconnected encrypted snapshot and a real exact receipt; until
those inputs exist, no executor, Docker target, migration or action route may
be run.
