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
domains, the explicit revocation snapshot and both detached signatures now
verify against the digest-pinned v2 keyring. The signed acceptance authenticates
only the exact disposable rehearsal evidence and keeps all eight authority
fields false. Its non-activating production one-shot returned
`DORMANT_SUPERVISOR_VERIFIED_AUTHENTICATED_EVIDENCE` with inner status
`AUTHENTICATED_EXACT_EVIDENCE_ACCEPTED`. The deployed keyring digest is
`a83cfac0c2a61edb83480ae782e077d3fafc6401b3e2f1694aeebf6fd24b113c`;
the signed acceptance raw-file SHA-256 is
`d592e24c1095ed16019ed306b1e6431909d0d6ef355456d231698cd6bd09134f`.
No private key or passphrase was received or read. A pre-deploy review caught
and avoided binding the two-hour acceptance to the six-hour recurring timer;
the deployed unit is a separate no-timer one-shot from commit `60bc058`, while
the recurring dormant supervisor remains active and returns `AUTH_PENDING`.
Evidence is
`docs/e0-3-bot-b5-3-064a-dump-restore-supervisor-rollout.v1.json` and
`docs/e0-3-bot-b5-3-064a-authenticated-evidence-signing-rollout.v1.json`, plus
`docs/e0-3-bot-b5-3-064a-public-key-intake-unsigned-acceptance.v1.json` and
`docs/e0-3-bot-b5-3-064a-authenticated-evidence-acceptance-rollout.v1.json`.
The reader remains `NOLOGIN` and credential-absent; no dump, restore, customer
row read or production mutation occurred. An unrelated duplicate `/swapfile`
entry in `/etc/fstab` caused two daemon-reload generator errors; swap remains
active and failed units remain zero. This slice did not change `fstab`.

A separate activation-specific plan/decision/receipt boundary is now
implemented and verified in a real disposable PostgreSQL 17.11 rehearsal. It
uses a distinct Ed25519 signature domain, fresh two-role signatures and
revocation snapshot, exact live artifact closure, a durable one-attempt journal
plus cross-process execution lock, 150-second work deadline with a reserved
30-second cleanup window, mandatory restore equality and post-close dormant
verification. The final rehearsal issued and revoked a real short-lived SCRAM
credential, used one exported snapshot and digest-pinned `pg_dump`, matched all
54 table fingerprints and 13 catalog sections in a distinct read-only-root
tmpfs restore, closed the journal, and rejected replay without a second
executor call. Final receipt SHA-256 is
`ebb45b20515124ef7217016b25502a15fcfd78b0e4bb847404c1ad183d2bb09b`.
The disposable source, volume, dump/restore containers, archive, workspace and
temporary HBA copy are absent. Production remained healthy with reader
`NOLOGIN` / credential absent / zero sessions and HBA SHA-256
`08b049674e7593bc87c8e78744ba6b65b557750807c17e860920931aa1b3d3b6`.
Evidence is
`docs/e0-3-bot-b5-3-064a-activation-entrypoint-rehearsal.v1.json`.
Implementation commit `82531d0ccdd290cf286cad0980943cdcda10f47c` is
pushed to `master`.
The CLI intentionally exposes package verification only: no production
executor or production activation package exists, and the earlier
evidence-only acceptance cannot authorize this boundary.

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

Implement and independently review an inert production executor that can only
plug the new activation decision/journal boundary into the already rehearsed
credential issue/revoke/reconcile, dump, restore, equality and cleanup
components. Rehearse that executor without production contact, then create a
fresh activation-specific offline signing package over the exact production
target and live artifact digests. The deployed evidence-only acceptance must
not be reused or promoted. Do not activate production before the distinct fresh
owner and independent-reviewer activation signatures verify.
