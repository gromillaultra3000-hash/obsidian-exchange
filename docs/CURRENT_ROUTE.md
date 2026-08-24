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

The short-lived SCRAM, independent sealed credential-FD and exported-snapshot
SourceAdapter contract remains verified only in its disposable rehearsal.
Its PostgreSQL prerequisite is now deployed: production runs the exact pinned
PostgreSQL 17.11 image, and both the forward transition and a controlled
force-recreate restart preserved the cluster system identifier, checksums,
the dormant `NOLOGIN`/credential-absent reader and exact HBA. A root-owned
atomic runtime journal follows each new container ID; the enabled systemd
watchdog repeatedly verifies or removes orphaned reader authority. All seven
consumers were restored after the gate passed, with the payout worker last;
there are no failed units or error-priority entries in the restore window.
Fresh logical and cold physical backups passed 17.10, 17.11, reverse-17.10 and
logical restore rehearsals. Evidence is
`docs/e0-3-bot-b5-3-064a-postgres-17-11-watchdog-rollout.v1.json`; independent
architecture, security and operations reviews found no current P0. This still
does not authorize production `LOGIN`, credential issuance or a refresh.

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

Implement and independently review one concrete production Dump/Restore
supervisor plus authenticated consumption of the exact disposable-rehearsal
evidence. Keep the reader `NOLOGIN` and credential-absent throughout this
slice. A separate activation gate may be considered only after those two
named prerequisites pass; it is not implied by the PostgreSQL rollout.
