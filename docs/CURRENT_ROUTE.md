# Current canonical route

Updated: 2026-08-24 UTC

## Product objective

Build and operate one Obsidian ecosystem: Wallet as the primary interface,
ObsidianExchange as the private non-KYC RUB↔crypto lane, external CEX custody
through KAIROS, LUMI as a non-money advisory/risk layer, and a future native
non-custodial wallet whose keys never reach the server.

## Active route

`E0 → E0.3 → B5.3 → 064A`

Completed bounded slices:
`obsidian_b64_snapshot_reader` is deployed in production against the frozen
PostgreSQL migrations `001–023` profile as a dormant `NOLOGIN` role with no
credential, and its exact first-match HBA isolation is active. Exact
post-deploy verification is `match` / HBA `EXACT`; evidence is
`docs/e0-3-bot-b5-3-064a-snapshot-reader-dormant-rollout.v1.json` and
`docs/e0-3-bot-b5-3-064a-snapshot-reader-hba-rollout.v1.json`.

The next contract layer is verified in a disposable PostgreSQL 17.11 cluster:
short-lived SCRAM issuance, two independent sealed credential FDs, an
exported-snapshot SourceAdapter, a digest-pinned real `pg_dump`, exact
revocation/reconciliation and adversarial supervisor-failure cases all pass.
The reviewed closure from pushed commit `abb22afc99e504cee29881d5e4b19ba15c0f343d`
is now published as an immutable root-owned inactive release under
`/opt/obsidian-exchange/releases/e0-e0.3-b5.3-064a/`; its `candidate` pointer
has no service, timer or process consumer. Production remained unchanged:
PostgreSQL 17.10, reader `NOLOGIN`/credential-absent, HBA `EXACT`, healthy with
zero restarts. Evidence is
`docs/e0-3-bot-b5-3-064a-scram-source-adapter-rehearsal.v1.json` and
`docs/e0-3-bot-b5-3-064a-dormant-runtime-artifact-rollout.v1.json`. This does
not authorize production `LOGIN` or a refresh.

Deployed contract:

- exact non-elevated, no-membership NOLOGIN role, two-connection bound and
  bounded role settings, deployed dormant with no credential; LOGIN is enabled
  only by a later separately rehearsed activation slice;
- one exact direct database grant, schema usage and 54-table SELECT;
- SELECT-only on the exact 29 sequences solely because full `pg_dump` reads
  `last_value/is_called`; sequence `USAGE`/`UPDATE` (`nextval`/`setval`),
  user-function execution, other-user-schema access and write/DDL are denied;
- project verifier and adversarial regression tests;
- one disposable PostgreSQL 17 rehearsal;
- bounded production rollout and runtime verification when every preflight is
  green, with an explicit rollback path;
- exact role-scoped HBA first-match rules: local/replication denied, only
  `obsidian_exchange` from the proven network-namespace source
  `127.0.0.1/32` may use SCRAM, and every other IPv4/IPv6 path is denied;
- retained original-HBA backup plus crash-safe journal, strict rollback and an
  exact `--reconcile` path that preserves unknown evidence fail-closed;
- machine-readable evidence and independent review.

## Delivery policy

Owner decision dated 2026-08-23: code-first continuous delivery. `NO_GO` is
not a standing project state. Each normal iteration ends in project code,
tests and a bounded reversible rollout when its concrete preflight passes.
Documentation-only repetition is not progress. Failed tests, unavailable
credentials, uncertain money outcomes, irreversible data loss and missing
rollback remain exact blockers.

## Excluded from this slice

E4; customer-row inspection; secret disclosure; migrations `024+`; money or
Telegram actions; 064B/064D row disposition; unrelated worktree cleanup.

## Active bounded next slice

Take a separately bounded production PostgreSQL 17.11 upgrade plus watchdog,
boot and abnormal-exit reconciliation slice. It must preserve the dormant
reader and exact HBA policy through upgrade/restart and prove cleanup after
supervisor death. Only after that gate, authenticated consumption of the
disposable rehearsal evidence and a concrete bounded Dump/Restore supervisor
exist may a separate `LOGIN` activation be considered.
