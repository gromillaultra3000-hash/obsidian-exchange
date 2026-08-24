# E4 hardened executor independent review

Date: 2026-08-23 UTC
Route: E4 / owner-gated disposable full-snapshot rehearsal
Review mode: separate read-only source/test pass; no Docker, PostgreSQL, age,
network, production or secret access

## Findings and dispositions

1. **Replay-to-consumption binding — fixed.** The first implementation checked
   that both objects were `CONSUMED` but did not bind the owner/reviewer replay
   claim to the formal receipt consumption. The consumption record now carries
   `replayClaimId`, `planId`, `targetRef`, `snapshotSha256` and `boundaryId`; the
   executor rejects any mismatch before the first runtime effect.

2. **Encrypted snapshot handle — fixed.** The source now opens the parent
   directory and final entry with no-follow flags, checks device/inode/size,
   regular-file type, expected hardlink count, optional parent device/inode,
   immutable flag and a second stat after digesting the ciphertext.

3. **Private-key handoff provenance — fixed at the interface boundary.** The
   executor accepts only an already-open FD. A linked regular file is rejected;
   only an unlinked regular file or FIFO can be used as an ephemeral source.
   Key bytes and key paths are never accepted or persisted. The caller must
   still obtain that FD from an independently controlled handoff mechanism.

4. **Ownership and TOCTOU teardown — pass with residual runtime dependency.**
   Docker labels, exact image, target name, container ID and ownership token are
   checked after creation and again before removal. A failed/ambiguous create
   cannot be retried automatically. Actual Docker daemon behavior remains
   unexecuted in this workspace.

5. **Authority provenance — concrete callback wiring added.**
   `relay/core/e4_authoritative_gate_callbacks.py` now performs the exact
   verifier → one-shot replay claim → formal receipt-consume sequence. It
   rechecks promotion/artifact bytes against the runner context, derives a
   bound public-artifact identity, normalizes the consumed evidence for the
   executor, and treats receipt failure after a committed claim as
   non-retryable ambiguity. Construction is lazy and does not read files or
   touch a ledger. Tests use synthetic public artifacts and temporary ledgers;
   the current expired/consumed handoff was not invoked.

6. **Teardown semantics — intentionally non-accepting.** The original staged
   ciphertext is retained. The result therefore reports source-retention
   review, not a completed destructive snapshot teardown. No deletion is added
   without a separate explicit owner decision.

## Verification

- hardened executor/provider and binding tests: `10/10` passed with stdlib
  `unittest`;
- authoritative callback wiring tests: `3/3` passed with real temporary
  replay/receipt ledgers and synthetic public artifacts;
- formal receipt-consumption contract functions: `6/6` passed through a local
  stdlib compatibility harness because the host has no `pytest` package;
- promotion `3/3`, replay registry `6/6`, owner/reviewer verifier `3/3`, and
  hardened preflight `3/3` passed;
- Python compilation and `git diff --check` are clean;
- no current one-shot claim was retried or consumed by this review.

## Verdict

`PARTIAL_PASS_NON_PRODUCTION`, not an execution or production approval. The
implementation is suitable for the next integration review, but the current
owner window and one-shot claim are not reusable. A real rehearsal still
requires a fresh exact owner/reviewer/replay receipt, invocation of this
file-backed verifier only inside that fresh window, an approved ephemeral
key-FD handoff, and an explicit decision on staged-ciphertext retention/
teardown.

Next canonical item: obtain a fresh exact owner-gated receipt if an actual
rehearsal is wanted; then run only the file-backed callback chain inside its
current window. Do not retry the consumed claim or create another signing key.
