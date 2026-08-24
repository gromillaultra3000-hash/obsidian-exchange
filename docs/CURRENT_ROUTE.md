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

A dormant production supervisor preflight is now deployed from immutable
commit `30114cbb7ce25d49b3313d04f6564903bc29074a`. Its enabled six-hour timer
verifies the exact 16-artifact disposable-rehearsal closure, pinned PostgreSQL
17.11 client, synchronized UTC clock and current watchdog result. Both rollout
runs and the signing-workflow rollout returned
`DORMANT_SUPERVISOR_VERIFIED_AUTH_PENDING`; the role stayed
`NOLOGIN` and credential-absent, and no dump, restore, customer-row read or
production mutation occurred. The verifier implements a closed two-independent-
Ed25519 evidence-only package. Its v2 keyring now binds deterministic key IDs,
a seven-day maximum validity interval, an explicit revocation snapshot and an
externally supplied expected keyring digest. A tested offline ceremony creates
encrypted dedicated keys, an exact unsigned acceptance, two detached
signatures and a verified final package without moving private keys to the
server. An observed false error receipt after `--help` was corrected in commit
`bfe53faaba17a4e9e0cca83024f602d9d59c965a`; the full focused regression now
passes 165/165 and the current secret-free Termux signing kit SHA-256 is
`42582645ccc35e9888f46f6edf07b8861a06819eb89c24d45bfd177f4ffa02c6`.
Two dedicated public entries from distinct owner/reviewer identities and trust
domains are now validated. An explicit empty revocation snapshot, seven-day
digest-pinned v2 keyring and two-hour unsigned evidence-only acceptance were
created at `2026-08-24T08:08:02Z`; every authority field is false. The public
signing-request archive SHA-256 is
`7616d3de896eb33201a59259c19befd8b2d7a552c605807488ae3a5e425352c1`,
the keyring digest is
`a83cfac0c2a61edb83480ae782e077d3fafc6401b3e2f1694aeebf6fd24b113c`
and the unsigned acceptance digest is
`b482504a2166b1e410e6a4b97829dbfcf818807b872f6ca73530a6d130dd54ba`.
No private key or passphrase was received or read, no signature exists yet,
and independent agent review remains unavailable under the current system
mode. Evidence is
`docs/e0-3-bot-b5-3-064a-dump-restore-supervisor-rollout.v1.json` and
`docs/e0-3-bot-b5-3-064a-authenticated-evidence-signing-rollout.v1.json`, plus
`docs/e0-3-bot-b5-3-064a-public-key-intake-unsigned-acceptance.v1.json`.

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

Obtain exactly one detached owner signature and one detached reviewer signature
over the current acceptance before its `2026-08-24T10:08:02Z` expiry, without
transferring either private key or passphrase. Assemble and verify them against
the independently pinned keyring digest, deploy the completed package as a
separate non-activating slice and require the supervisor to return
`AUTHENTICATED_EXACT_EVIDENCE_ACCEPTED`. Keep the reader `NOLOGIN` and
credential-absent; this item does not authorize an execution entrypoint,
credential issuance or refresh. If the acceptance expires first, create a new
nonce/window and obtain fresh signatures; never reuse the expired payload.
