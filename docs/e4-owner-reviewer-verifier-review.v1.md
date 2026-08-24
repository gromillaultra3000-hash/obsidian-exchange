# E4 owner/reviewer artifact verifier review

Date: 2026-08-22

Active route: `E4 / owner-gated disposable full-snapshot rehearsal`.

## Bounded slice

Added `relay/core/e4_owner_reviewer_verifier.py` as a fail-closed, non-executing
intake boundary. It reads only bounded regular files, rejects duplicate JSON
fields, verifies the two SSH signatures through `ssh-keygen -Y verify`, checks
the public-key fingerprints and raw-file digests, compares the registry,
payload, envelope, target, snapshot, plan, immutable handle and expiry fields,
and uses an injected evaluation timestamp. It never creates a receipt, opens a
database, starts Docker, contacts a network or grants authority.

## Evidence

- Owner payload: `E4-owner-handoff/e4-owner-decision-payload.v4.json`, SHA-256
  `6ba630bd3de5ba2149fbf420b420eec917194d21e159172dcca2b7adfc24a672`.
- Reviewer envelope: `E4-owner-handoff/e4-reviewer-review-envelope.v3.json`,
  SHA-256 `8702959ff95b4c79864c3f55ac07d418f017a96f8b193c07385e26dfae2429f2`.
- Focused regression/tamper harness: `tests/test_e4_owner_reviewer_verifier.py`,
  `3/3` tests passed with the stdlib `unittest` runner.
- With an injected timestamp inside the historical owner window, both owner
  and reviewer signatures and all exact bindings passed. The result remained
  `NO_GO` because the registry is `CANDIDATE_NOT_AUTHORIZED`, trusted clock is
  not attested, replay registry is not checked and hardened executor is absent.
- A read-only check at the actual current clock returned `NO_GO` with
  `OWNER_WINDOW_NOT_CURRENT`; the signatures and exact binding still passed.

## Status and blockers

This is evidence-only `IN_PROGRESS`, not an authenticated receipt or execution
authorization. No Docker, PostgreSQL, production network, credentials or
snapshot plaintext were used. The next canonical item is an authenticated
trust registry/replay decision and review of the hardened 12-step executor;
the expired v4 artifacts must not be reused.
