# E4 private-action test invoker: independent security review

Date: 2026-08-22

Active roadmap route: E4, dormant/test-only `private-action-test-invocation-result.v1`.
The first unmet canonical E0 gate remains E0.3/B5.3/064A and is still
`BLOCKED_OWNER`; this review does not waive it or grant production authority.

## Scope and conclusion

Reviewed:

- `relay/services/e4_private_action_invoker.py`
- `relay/repositories/e4_action_handoff_store.py`
- `relay/core/e4_private_action_adapter.py`
- `relay/core/e4_route_authorization.py`
- `tests/test_e4_private_action_invoker.py`
- source references for HTTP/provider/runtime wiring

Conclusion: **accepted for the current dormant test-only scope; not approved
for HTTP or production persistence wiring**.

The invoker revalidates the complete chain, requires an explicitly test-only
store, uses the existing atomic handoff store, returns bounded metadata, and
hard-codes production/action/route flags to false. No source reference from a
production route was found. The targeted suite passed **69 tests**. `git diff
--check` passed. Optional PostgreSQL coverage was not run because
`TEST_POSTGRES_DSN` is unset.

## Findings

### E4-SEC-001 — trusted principal/actor binding is missing at the invoker boundary

- Severity: High pre-production blocker; current exposure: none while the
  adapter remains dormant and test-only.
- Location: `relay/services/e4_private_action_invoker.py:33-51`.
- Evidence: `validate_private_action_assessment()` receives
  `principal_ref=assessment.get("principalRef")`; the invoker has no separate
  trusted principal or actor argument supplied by authentication middleware.
- Impact if wired to an HTTP or production route: a caller-controlled
  assessment could select its own `principalRef` and `actorUserId`. The
  downstream store checks internal equality and destination/amount hashes, but
  that does not establish that the authenticated caller owns the selected
  principal or actor. This creates an IDOR/authorization-bypass path for order
  creation if request data reaches this boundary.
- Required fix before wiring: require server-derived
  `trusted_principal_ref` and `trusted_actor_user_id` (and the applicable
  authenticated web-user binding) as non-request parameters; reject any
  mismatch against assessment, reservation, draft and order. Invoke the
  existing route-authorization contract with those trusted values before
  handoff. Do not infer identity from the assessment itself.
- Mitigation currently in place: the function requires `store.test_only is
  True`, has no HTTP/provider import or route reference, and returns
  `productionInvocationAllowed:false`, `routeConnected:false` and
  `actionAllowed:false`. Keep those constraints until the fix and a new review
  are complete.

### E4-SEC-002 — `test_only` is a runtime guard, not a production authorization boundary

- Severity: Medium pre-production hardening condition; current exposure: none
  in the unreachable test-only surface.
- Location: `relay/services/e4_private_action_invoker.py:39-40` and
  `relay/repositories/e4_action_handoff_store.py:104-110`.
- Evidence: the test-only capability is represented by a mutable boolean on an
  injected store. A process that can import the module can construct a store
  with `test_only=True` and write to its selected database path.
- Impact if accidentally exposed: the boolean could be mistaken for an
  authorization control or allow an unintended caller to reach a database
  write. It does not protect a production endpoint by itself.
- Required fix before any production variant: keep the test adapter and
  production adapter as separate interfaces/modules, use an explicit
  deployment/feature gate and trusted route authorization for production, and
  never accept the store or database path from request data. Re-review the
  production boundary independently.
- Current disposition: acceptable for a deliberately injected disposable test
  store; not a reason to wire this function into a live route.

## Controls verified

- Exact-schema and hash validation rejects tampered invocation results.
- The full preview → acknowledgement → draft → assessment → reservation chain
  is rebuilt and compared before `handoff()` is called.
- The handoff store uses parameterized SQL, validates actor/destination
  fingerprints and amounts, and commits reservation plus order atomically.
- Created/replayed responses expose only bounded IDs and statuses; tests confirm
  raw destinations and payout details are absent.
- Store failures fail closed to bounded `NO_GO` metadata without returning the
  internal exception text.
- No FastAPI/APIRouter, HTTP client, socket, provider, environment-secret or
  logging surface exists in the invoker, and no production module references it.

## Decision

`REVIEW_PASS_TEST_ONLY_WITH_FINDINGS`: safe to retain as dormant test-only
code. The next E4 step is to implement trusted identity binding, add regression
tests, and repeat the independent review. No HTTP route, provider call,
production database write, deployment or restart is authorized by this review.
