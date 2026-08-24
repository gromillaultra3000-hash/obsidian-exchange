# E4 rehearsal runner boundary review v1

Date: 2026-08-22 UTC
Route: E4 / isolated full-snapshot rehearsal
Decision: `REVIEW_PASS_NON_EXECUTING_RUNNER_BOUNDARY`

## Scope

`relay/core/e4_rehearsal_runner_boundary.py` adds the code-bearing boundary
between the target-bound authorization receipt and a future executor. It does
not execute Docker, read a snapshot, read a key, connect to PostgreSQL or read
environment variables.

The boundary accepts only an `ELIGIBLE` receipt whose plan ID, target reference,
snapshot digest and deterministic target-spec fingerprint agree. It emits one
fixed PostgreSQL image digest, `network=none`, read-only root, tmpfs-only data,
no published ports, no persistent volume, no automatic retry and mandatory
destroy/final-absence phases. Snapshot and key references are opaque tokens;
paths, DSNs, production markers and secret values are rejected.

## Verification

- `tests/test_e4_rehearsal_runner_boundary.py`: 7 passed.
- Tampered target network, published-port arguments, receipt status,
  fingerprint and path-like/secret-like references fail closed.
- The boundary contains no subprocess, database, socket, environment, HTTP,
  production-container or secret-reading surface.

## Status and remaining work

This is implementation evidence for a non-executing test-only boundary, not
production authorization or a promotion proof. The actual executor remains
owner-gated by the existing single-use machine-readable receipt and must keep
the source snapshot pre-existing and production-disconnected. No route, feature
gate, migration, ACL, service, deployment or production database was changed.
