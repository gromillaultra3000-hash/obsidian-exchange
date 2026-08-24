# E4 owner/reviewer replay registry review

Date: 2026-08-22

Active route: `E4 / owner-gated disposable full-snapshot rehearsal`.

## Bounded slice

Added `relay/core/e4_owner_reviewer_replay_registry.py`, an explicitly
temporary SQLite one-shot claim ledger. It uses `BEGIN IMMEDIATE`, unique
payload/envelope identity, exact artifact digest binding, closed claim records,
replay/conflict responses and before/after-commit fault behavior. It is a
replay guard only: it cannot create an authorization receipt, enable money
action, run Docker or contact PostgreSQL/production.

The registry rejects any verifier result that is not explicitly
`AUTHENTICATED_ACTIVE`, `VERIFIED`, freshness-checked, trusted-clock-attested
and `replayEligible=true`. Therefore the current evidence-only v4 result cannot
be claimed or consumed.

## Verification

- Owner/reviewer verifier regression and tamper harness: `3/3` passed.
- Replay registry harness: `6/6` passed.
- Covered exact replay, same-payload envelope conflict, concurrent claims,
  before-commit rollback, after-commit ambiguity and closed-record tamper.
- Python compilation and `git diff --check` passed.
- No private key, network, database, Docker or snapshot plaintext was used.

## Status

This remains non-authoritative `IN_PROGRESS`. The current v4 artifacts are
expired and the verifier still reports `NO_GO`. Remaining blockers are an
authenticated trust registry, an attested trusted clock, a real verifier
integration that can produce an eligible result, and the full hardened
12-step executor with target ownership/cleanup proof.
