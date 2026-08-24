# E4 hardened executor review

Date: 2026-08-22 UTC
Route: E4 / owner-gated disposable full-snapshot rehearsal

## Bounded implementation

`relay/core/e4_hardened_executor.py` now contains a fail-closed executor
boundary and an injectable runtime contract. The concrete adapter is limited to
argv-only Docker/age calls and the pinned PostgreSQL image. It enforces:

- an authenticated `AUTHENTICATED_ACTIVE` trust result plus a separate
  `CONSUMED` one-shot replay result;
- exact plan, receipt, owner-approval, boundary, target name, label and
  container-identity binding;
- an encrypted snapshot opened with `O_NOFOLLOW`, inode/device/size checks,
  digest verification and an immutable-flag check;
- an external ephemeral key file descriptor only; key bytes and key paths are
  not accepted, copied or persisted;
- Docker `network=none`, `--pull=never`, read-only root, tmpfs-only storage,
  no published ports/host binds, non-root execution, dropped capabilities,
  `no-new-privileges`, bounded resources and bounded PostgreSQL health;
- a streaming age→`pg_restore` pipeline with no plaintext snapshot file,
  bounded restore time, no shell and no inherited environment;
- post-load write revocation, secret-free read-only evidence, exact proposal
  migration absence, ownership-aware teardown and target absence proof.

The adapter never contacts the production database or network and contains no
production DSN, migration application, persistent target or automatic retry.
The original staged ciphertext is not deleted by this implementation; only
the transient open FD/stream is released. Any future destructive staging
policy requires a separately explicit owner decision.

## Verification

- `tests/test_e4_hardened_executor.py`: `10/10` passed with the stdlib
  `unittest` runner;
- promotion: `3/3`; replay ledger: `6/6`; owner/reviewer verifier: `3/3`;
  preflight: `3/3`;
- Python compilation and `git diff --check` are clean.
- `tests/test_e4_authoritative_gate_callbacks.py`: `3/3` passed with synthetic
  public artifacts and real temporary replay/receipt ledgers. The concrete
  adapter is `relay/core/e4_authoritative_gate_callbacks.py`; it calls the
  file-backed promotion verifier before the one-shot replay registry and
  formal receipt ledger, but this current expired/consumed handoff was not
  invoked.

The synthetic runtime tests do not start Docker, PostgreSQL or `age`, do not
open the staged snapshot, and do not consume or retry the existing replay
claim. No production service, credential, plaintext snapshot or private key
was accessed.

## Status

`IN_PROGRESS` / non-authoritative. This implementation does not turn the
previous evidence into production or money authority. The current one-shot
claim is already consumed and the prior owner window is not reusable. Before
any real rehearsal consideration, this module needs an independent security
review and a fresh exact owner/reviewer/replay receipt plus an approved
ephemeral key-FD handoff and concrete authoritative callback wiring. Until then
Docker execution remains prohibited.

Next canonical item: obtain a fresh exact owner-gated receipt if an actual
rehearsal is wanted, then invoke the file-backed callback chain only inside its
current window. Do not retry the consumed claim or create another signing key.
