# E4 hardened executor preflight review

Date: 2026-08-22

Active route: `E4 / owner-gated disposable full-snapshot rehearsal`.

## Bounded slice

Added `relay/core/e4_hardened_executor_preflight.py`, a pure validator for the
frozen 12-step rehearsal proof. It checks replay-claim ordering before the
first Docker effect, target absence/ownership/container identity, digest-pinned
image and isolation settings, encrypted immutable pre-existing snapshot
provenance, trusted-clock shape, production isolation, all 12 ordered steps,
teardown/absence evidence and fail-closed authority flags.

It performs no probes and has no Docker, PostgreSQL, network, filesystem,
credential or process-launch surface. Even a complete synthetic mechanical
proof returns `MECHANICAL_PRECHECK_PASS_NON_AUTHORITATIVE` with
`executionEligible:false` and `actionAllowed:false`.

## Verification

- Hardened preflight regression/landmine harness: `3/3` passed.
- Owner/reviewer verifier harness: `3/3` passed.
- Replay registry harness: `6/6` passed.
- Python compilation and `git diff --check` passed.
- No private key, network, database, Docker or snapshot plaintext was used.
- No independent external agent was available in this environment; no such
  review is claimed.

## Status

This remains non-authoritative `IN_PROGRESS`. The current signed v4 handoff is
expired. Remaining blockers are authenticated trust registry, attested trusted
clock, real eligible verifier/replay integration, an actual hardened executor,
TOCTOU-safe target ownership and cleanup proof. No rehearsal launch is allowed.
