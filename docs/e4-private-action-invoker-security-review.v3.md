# E4 private-action test invoker: capability-boundary follow-up

Date: 2026-08-22

Active roadmap route: E4, dormant/test-only `private-action-test-invocation-result.v1`.
The first unmet canonical E0 gate remains E0.3/B5.3/064A and is still
`BLOCKED_OWNER`.

## Decision

**`REVIEW_PASS_TEST_ONLY_CAPABILITY_BOUNDARY`**.

The test-only handoff capability is now explicit. The production-capable
SQLite/PostgreSQL handoff stores no longer accept or expose a mutable
`test_only` boolean. The invoker accepts only an `E4TestOnlyHandoffStore`
wrapper, and the wrapper is documented as an isolation marker rather than
authorization. No production module wraps or references it.

## Changes reviewed

- `relay/services/e4_private_action_invoker.py:22-40` defines the explicit
  fixture wrapper and forwards only the handoff call.
- `relay/services/e4_private_action_invoker.py:76-83` requires the wrapper by
  nominal type before invoking the chain.
- `relay/repositories/e4_action_handoff_store.py:104-112` and `:177-183`
  no longer expose a `test_only` constructor switch or attribute.
- `tests/test_e4_private_action_invoker.py` verifies direct production-capable
  stores are rejected, wrapper use remains required, identity drift never
  reaches the delegate, and the old boolean constructor switch stays absent.

## Residual security boundary

The wrapper is not an authorization mechanism. Code that can execute inside
the process can deliberately wrap a delegate, so a future production route
must use a separate production adapter, trusted route authorization, explicit
feature gates and a new independent review. The current source has no such
route or wrapper usage outside tests.

## Verification

- Full bounded E4 contract set: **138 passed**.
- Python compilation passed for the changed service, repository and tests.
- `git diff --check` passed.
- No production route/provider/HTTP reference to the invoker or wrapper was
  found.
- Optional PostgreSQL handoff coverage remains unrun because
  `TEST_POSTGRES_DSN` is unset.
- No production database, migration, service, flag, deployment or restart was
  changed.

The next ordered E4 operational item remains the disposable PostgreSQL
rehearsal, but it is owner-gated by an exact disposable target and snapshot
digest. This work does not satisfy or bypass that approval requirement.
