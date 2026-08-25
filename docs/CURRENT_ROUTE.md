# Current canonical route

Updated: 2026-08-25 UTC

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

The activation-specific v2 boundary and inert executor are now hardened through
pushed commit `ddc591beb815036c0fb13c0fedc880d38f8b6c63`, published only as
the unreferenced root-owned read-only release
`/opt/obsidian-exchange/releases/e0-e0.3-b5.3-064a/ddc591beb815036c0fb13c0fedc880d38f8b6c63`.
All 2152 Git blobs match. The inactive `candidate` symlink remains on
`abb22afc99e504cee29881d5e4b19ba15c0f343d`; no mutable deploy copy, unit,
timer, state root, signing package, daemon reload, service start or restart was
created. The CLI remains verify-only and the executor CLI remains an internal
proxy helper, so these bytes are not a production activation surface.

The normal executor still binds one sealed single-use activation capability,
fixed production roots, two durable journals, the watchdog interlock,
network-none `pg_dump` through an exact Unix proxy, same-snapshot source
fingerprints, inode-bound workspace cleanup and a PID-rebound held restore
socket. In addition, an exact historical signed package can now yield only a
sealed cleanup capability after decision and keyring expiry. Current artifact
closure is reverified first; that capability cannot execute or claim a lease
and can only reconcile an existing exact journal to `RECONCILED_HOLD`.

The signed effective plan now contains one non-contradictory network and
recovery contract; the old hardened plan is generated only as a deterministic
compatibility projection. A durable absent-name/create-intent record and exact
workspace-parent device/inode close the mkdir-to-inode-registration crash
window. Foreign, preexisting or swapped objects are preserved fail-closed.
Docker auto-remove observation has one real two-second deadline across all
references, including the underlying inspect calls.

The final real disposable PostgreSQL 17.11 run closed the normal journal,
rejected replay without a second executor call, supervised the live lease,
then recovered a separate pre-inode workspace after both signed expiries to
`ACTIVATION_RECONCILED_HOLD`. Receipt SHA-256 is
`03446838955a2d8e6e09676762f6de55e9868c79d12d2d5ffb7f9c319669cd58`.
Reader post-state is `NOLOGIN`, credential absent and zero sessions; all
disposable resources are absent. Focused regression passes 180/180, the full
related set passes 237/237, and all three independent latest-byte reviews
report inert GO with no P0/P1.

The cleanup-only production watchdog is now deployed from immutable commit
`12e0d1c018eacd7d9a1a59c4cd01308bb534ef6d`; all 2153 Git blobs match. Unit
pin commit `dcb76b5e7599f8a69ecce52900ffcbd24ee5bcf3` is pushed. Only the timer
oneshot has explicit recovery orchestration; PostgreSQL `ExecStartPost`
remains dormant-only and PostgreSQL was not restarted. Both the first
immutable oneshot and recurring tick returned
`DORMANT_VERIFIED_NO_RECOVERY_REQUEST`. The fixed request/package and
activation state root remain absent; the same healthy container, PID, start
time, system identifier, exact HBA and restart count zero are preserved. The
reader is `NOLOGIN`, password-absent and session-free; timer is
enabled/active/waiting and failed units are zero. Architecture, security and
operations latest-byte reviews report GO with no P0/P1. Evidence is
`docs/e0-3-bot-b5-3-064a-dormant-watchdog-cleanup-recovery-rollout.v1.json`.

The separate production launcher prerequisite is now complete and deployed
inert. Pushed implementation commit
`34bc167ebf192103f588524b521713ab588245e3` upgrades the activation boundary
to v3, includes launcher and watchdog bytes in the signed closure, enforces an
exact-empty production state both before credential access and again under the
global interlock, and supervises one child attempt with readiness/PDEATHSIG,
process-group termination, an exact 180-second wall and no retry. All 2157 Git
blobs match the root-owned read-only immutable release. Pushed pin commit
`2117e14a8bda531719f671b611f6c7f9edc1ffbc` binds the static launcher, recurring
watchdog and PostgreSQL dormant `ExecStartPost` to that same release.

The launcher is loaded/inactive/static, was never started and has no enablement
symlink. The first v3 watchdog one-shot and a subsequent recurring tick both
returned `DORMANT_VERIFIED_NO_RECOVERY_REQUEST`; the timer is
enabled/active/waiting. PostgreSQL was not restarted and retained its exact
MainPID, container ID/PID/start time, image, system identifier, HBA and restart
count zero. Reader state is still `NOLOGIN`, password absent and zero sessions;
request/package/state remain absent and failed units are zero. Focused tests
pass 164/164, the real disposable lifecycle plus hard-kill recovery passed, and
architecture/security/operations report GO with no P0/P1. Evidence is
`docs/e0-3-bot-b5-3-064a-production-launcher-inert-rollout.v1.json`.

The activation signing-readiness slice is now deployed inert. Implementation
commit `8231d1ec61345118b184163e912abb63712fea0a` pins a production activation
trust registry, proves each activation/evidence key-ID pair derives from the
same public key, and rejects self-declared keyrings. Its exact v3 ceremony
builds deterministic secret-free offline/request archives, checks target/time/
revocation and immutable closure, verifies detached Ed25519 signatures before
root-only import, and assembles no runtime request. Pin commit
`176893d808d348b8a8bbda0c017c28a2e7806065` is pushed. Both immutable releases
have all 2162 Git blobs verified; the three installed units resolve to the
implementation release. PostgreSQL was not restarted, the launcher remains
inactive/static, and the post-pin watchdog returned
`DORMANT_VERIFIED_NO_RECOVERY_REQUEST` with the same healthy dormant production
tuple. The secret-free offline kit is
`/root/064A-activation-handoff/obsidian-064a-activation-v3-offline-kit-8231d1ec.tar`,
SHA-256 `1476cf4d0136ed9c0f57f9fb16c8e391b8d7d492e0c7c1e650199fa8c8b39774`.
A real disposable PostgreSQL 17.11 lifecycle passed normal/replay/cold-expiry/
hard-kill recovery; receipt SHA-256 is
`cd78ac9fd910f6cb2458e1eff664a2bb1b59f2ea0b6e419266927e7e62840a13`.
Evidence is
`docs/e0-3-bot-b5-3-064a-production-activation-signing-readiness-rollout.v1.json`.

The two external signer devices then independently verified the static kit.
Real ceremony preflight exposed two fail-closed integration defects before any
plan was signed: the online wrapper expected the absent watchdog field
`actionAllowed` instead of its actual `authorityIncreased:false` contract, and
Android/Termux denied the hard-link publication used for an offline detached
signature. Pushed commits
`aafcd312ac41406f384317b23387e3f46efd687a` and
`b36c3ebc4ec80526ed3a7abf4b9fb6b125e0d822` correct those exact boundaries.
The latter uses exclusive final-name creation, fsync and metadata validation
only for offline output; server-side hard-link atomicity is unchanged. Focused
ceremony/launcher/deployment regression passes 39/39, staged gitleaks and diff
checks pass, and both root-owned read-only fix releases match all 2163 Git
blobs. Both devices independently verified the replacement secret-free kit,
SHA-256
`e77eb3adad4965ed78567b1eb3f3683a6ad3822c874ade9680277d0a1b06fac9`.

One fresh exact v3 decision was then signed by the accountable owner and
independent reviewer and assembled through the immutable verifier with status
`SIGNED_V3_DECISION_VERIFIED_NOT_DEPLOYED`. Decision SHA-256 is
`de644329e9f428007e06d138a962d8980a133058376daa2732d4c88bb001a0be`;
the completed raw-file SHA-256 is
`050a88bee310e0de0dfe72619e7f26d4ce17e75884f0f4aeecb5141060725ac1`.
All runtime-authority fields remained false: no runtime request/package/state,
credential, dump, restore, customer-row read or launcher start occurred.
The decision expired unused; post-expiry verification returns
`INSUFFICIENT_DECISION_WINDOW_REMAINING`, so neither it nor either detached
signature can be reused.

The missing boundary is now implemented. Commit
`e466268d9c518c7025f3b6c5b2f3d23407e5a4e9` adds a fixed no-argument atomic
runtime-package committer to the signed artifact closure; pin commit
`8c31c55af2e0994991fe73e00c333b749dd5f611` targets that immutable
implementation. The committer re-verifies the fresh decision, trusted time,
artifact closure, exact dormant production tuple and absent runtime targets.
It publishes only the recovery package, four empty state roots, recovery
marker and launch marker, in that order, and never invokes the launcher.
Rollback covers each publication point and internal rename/link/fsync failure.
Immutable disposable fault/recovery tests pass 20/20, the non-Docker 064A
cluster 291/291, full watchdog regression 52/52 and focused pin tests 59/59;
compile/diff/staged gitleaks/systemd checks pass. Both root-owned read-only
releases match all 2166 Git blobs.

The three installed unit files now pin `e466268` and match the repository
bytes. No service was started or restarted. Post-rollout recovery package/
request, launch request and activation root remain absent; launcher is
inactive, both safety timers and PostgreSQL are active, failed units are zero,
and the reader remains `NOLOGIN`, credential-absent and session-free under
`DORMANT_VERIFIED`. The old signed decision is rejected with
`INVALID_ACTIVATION_ARTIFACT_SET`, proving it cannot authorize the expanded
closure. New secret-free kit SHA-256 is
`0b11ef3a6f1cd071a7ed78053c9a6470aad104e88d4fbc63723aacdf541f66c0`.
Evidence is
`docs/e0-3-bot-b5-3-064a-runtime-package-committer-inert-rollout.v1.json`.
The next freshly signed decision then exposed a fail-closed production
integration defect: deployed committer bytes required a root:root non-group-
writable activation parent, while the host parent was the legacy shared
`root:obsidian-payout 2770` directory. Decision `9eee5a12...` expired after
`RUNTIME_COMMIT_PARENT_UNSAFE`; no runtime path, credential, dump, restore,
customer-row read or launcher start occurred, and its signatures are
non-reusable.

The parent boundary is now corrected and deployed inertly. Implementation
commit `f10098625854aefcdfbaadf8f9d75e003f298497` requires the exact host
identity `root:obsidian-payout` (`uid 0`, `gid 986`) and sticky+setgid mode
`3770`; pin commit `d67171c7f5b1930b75cb3198a8764be7c3dc6073` is pushed.
The sticky bit prevents a payout-group member from removing the root-owned
activation tree while preserving existing group inheritance. A restricted-
namespace GID remap first produced candidate commits `387fab2`/`c1bef8a`, but
the host-level preflight rejected them before any mutation; those releases
remain unreferenced and superseded.

Both final immutable releases match all 2167 Git blobs. Focused tests pass
60/60, expanded final 064A tests 135/135 and host-namespace watchdog tests
52/52. Production parent mode changed reversibly from `2770` to `3770`; three
installed units now pin `f100986`. PostgreSQL retained MainPID `3136948`, its
start timestamp and restart count zero; launcher start timestamp remains zero.
The post-rollout watchdog returned
`DORMANT_VERIFIED_NO_RECOVERY_REQUEST`; seven consumers and both safety timers
are active, failed units are zero, runtime coordination/state paths are absent,
and the reader remains `NOLOGIN`, credential-absent and session-free. Evidence
is
`docs/e0-3-bot-b5-3-064a-activation-parent-contract-rollout.v1.json`.

The 266240-byte secret-free kit SHA-256 was
`1e24f747e5bca8fb9ae7f0cb3b1b020958be5d25dec4ce8925308853d7de9b35`.
Both device workflows later reported exact verification `PASS`, but the key-
custody finding below prevents that kit from authorizing another request.

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

The exact kit was subsequently reported as archive/internal-checksum `PASS` by
both device workflows, and one fresh request was created. Its decision digest
was `1d868150...`. The owner produced a local detached signature, but it was
never transferred or imported; no reviewer signature was produced. With only
92 seconds remaining above the committer's mandatory five-minute floor, the
server coordination was archived and the transfer link removed instead of
rushing the authority path. The request, nonce and local owner signature are
non-reusable.

That owner-terminal session also enumerated both owner and reviewer private-key
files. No private-key bytes or passphrase were received and the reviewer key
was not used, but co-residency invalidates the required independent-device
custody claim. Active route remains `E0/E0.3/B5.3/064A`, now `BLOCKED_OWNER` on
reviewer-key rotation: generate the replacement only on a separate controlled
reviewer device, revoke the co-resident key, update the pinned public trust
registry and rebuild/reverify the secret-free kit before any new request. The
immutable committer may publish runtime paths only while a future fresh
decision retains at least five minutes, and must still leave the launcher
inactive for the final exact pre-start verification.
Evidence is
`docs/e0-3-bot-b5-3-064a-fresh-request-owner-only-abort.v1.json`.
