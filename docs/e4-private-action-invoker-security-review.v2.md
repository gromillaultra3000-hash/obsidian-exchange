# E4 private-action test invoker: follow-up security review

Date: 2026-08-22

Active roadmap route: E4, dormant/test-only `private-action-test-invocation-result.v1`.
The first unmet canonical E0 gate remains E0.3/B5.3/064A and is still
`BLOCKED_OWNER`; this fix and review do not waive it or grant production
authority.

## Scope and result

This follow-up reviews the trusted-identity fix in:

- `relay/services/e4_private_action_invoker.py`
- `tests/test_e4_private_action_invoker.py`
- the existing E4 assessment, reservation, handoff and route-authorization
  contracts

Decision: **`REVIEW_PASS_TEST_ONLY_HARDENED`**.

The previous high pre-production finding is resolved at this boundary. The
invoker now requires server-derived `trusted_principal_ref`,
`trusted_actor_user_id` and `trusted_web_user_id`; it rejects identity drift
before `handoff()`, validates the assessment with the trusted principal, binds
the order actor, and checks the BUY order's `web_user_id` when that field is
present. The trusted values are not emitted in the bounded result.

The adapter remains dormant and test-only. This is not approval for HTTP,
provider calls, production database writes, deployment or restart.

## Finding disposition

### E4-SEC-001 — trusted principal/actor binding

Status: **RESOLVED** for the reviewed invoker boundary.

- Location: `relay/services/e4_private_action_invoker.py:33-85`.
- The function has no defaults for the three trusted identity parameters.
- Assessment `principalRef` and `actorUserId` must equal the trusted values.
- `order.user_id` must be a positive integer equal to the trusted actor.
- A BUY order's `web_user_id`, when present, must equal the trusted web user.
- `validate_private_action_assessment()` receives the trusted principal rather
  than selecting it from the assessment.
- Tests cover trusted principal, actor, web-user and order-actor drift plus an
  assessment that attempts to self-select a different principal; the injected
  handoff is never called.

The future production route must still derive these values from authenticated
server state and call the existing route-authorization contract. The SELL
order schema has no `web_user_id` field, so its web-session binding remains a
route-level responsibility rather than an invented order field.

### E4-SEC-002 — mutable `test_only` is not production authorization

Status: **OPEN BY DESIGN / TEST-ONLY CONSTRAINT**.

The `test_only` boolean remains a runtime guard on the injected store. It is
adequate for the deliberately injected disposable test store in this dormant
surface, but it must not be reused as a production authorization mechanism.
Any future production adapter requires a separate interface, explicit feature
gate, trusted route authorization and a new independent review.

## Verification

- Targeted E4 suite: **74 passed** (the previous 69 plus five new identity/
  boundary regressions).
- Python compilation passed for the changed invoker and test.
- `git diff --check` passed.
- Source scan still finds no production route, HTTP client, provider, socket,
  secret/environment or logging surface in the invoker.
- No production module references the invoker.
- Optional PostgreSQL coverage was not run because `TEST_POSTGRES_DSN` is
  unset; no PostgreSQL result is claimed.
- Bandit is not installed in the available environment; no Bandit result is
  claimed.

## Final disposition

The trusted-identity finding is closed for the dormant test-only adapter.
Retain the adapter disconnected from HTTP and production persistence. Any
production wiring must separately prove authenticated web-session binding,
feature/route authorization, production store capability separation and
rollback/reconciliation before it can be considered.
