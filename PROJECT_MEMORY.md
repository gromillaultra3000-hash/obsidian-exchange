# Project memory

Updated: 2026-08-24 UTC

## Current goal and status

- 2026-08-23 owner selected code-first continuous delivery: bounded reversible
  work proceeds as project code → tests → rehearsal/canary → rollout →
  post-deploy evidence. `NO_GO` is reserved for a concrete failed preflight,
  not a permanent suffix. New sessions use `docs/CURRENT_ROUTE.md`; unchanged
  long charters and history are not repeatedly reread within one logical task.

- 2026-08-24 active route is `E0 → E0.3 → B5.3 → 064A`; E4 and migrations
  `024+` remain out of scope. Production PostgreSQL is upgraded to the exact
  pinned 17.11 digest and healthy after a controlled force-recreate restart;
  cluster system identifier `7672203973020184609`, checksums and HBA SHA
  `08b049674e7593bc87c8e78744ba6b65b557750807c17e860920931aa1b3d3b6`
  are preserved. `obsidian_b64_snapshot_reader` remains `NOLOGIN`,
  password-absent, connection-limit two and session-free. The root-only atomic
  journal follows container ID changes, and the enabled watchdog timer returns
  `DORMANT_VERIFIED`. All seven consumers are active, payout worker was
  restored last, and the post-restore window has no error-priority entries or
  failed units. Independent architecture/security/operations post-deploy
  reviews report GO with no current P0; LOGIN/refresh remain excluded. Commits
  `b6a0141d2ab2ed5e6f8c15542864728601f3271d` and
  `5a3a061a18a7071321c6cb7365768be18eefd68a` are pushed. The root-only rollback
  bundle at
  `/var/backups/obsidian-exchange/postgres-17.11-b6a0141-20260824T0458Z`
  contains verified logical/cold-physical backups, the 17.10 image and
  preimages; restored physical 17.10/17.11/reverse-17.10 and logical rehearsals
  pass. Evidence:
  `docs/e0-3-bot-b5-3-064a-postgres-17-11-watchdog-rollout.v1.json`.
  An initial test-label collision interrupted PostgreSQL and the first staging
  start retained 17.10; both recovered without enabling reader authority and
  are closed by isolated contract labels, exact production-tuple assertions,
  full import-closure conditions and `--force-recreate`. The dormant
  Dump/Restore supervisor now runs from immutable implementation commit
  `30114cbb7ce25d49b3313d04f6564903bc29074a`, with systemd pointer commit
  `6a06086dde3575439cd0b30e1fae82467b154bc2`; its enabled six-hour timer
  returns `DORMANT_SUPERVISOR_VERIFIED_AUTH_PENDING`, validates the exact
  16-artifact rehearsal closure, pinned 17.11 client and NTP-synchronized UTC,
  and invokes neither credential issuer, dump nor restore. The tested offline
  ceremony and v2 verifier require dedicated independent Ed25519 identities,
  public-key-derived key IDs, an explicit seven-day revocation snapshot,
  external keyring-digest pin and two detached signatures; private keys never
  enter the server, and E4 keys are not implicitly reused. Focused regression
  passes 165/165; post-rollout PostgreSQL/watchdog/seven consumers are healthy,
  the cluster ID is unchanged, the reader remains `NOLOGIN`/credential-absent,
  and no unit or 064A-related error failed. Evidence:
  `docs/e0-3-bot-b5-3-064a-dump-restore-supervisor-rollout.v1.json` and
  `docs/e0-3-bot-b5-3-064a-authenticated-evidence-signing-rollout.v1.json`.
  Dedicated 064A owner/reviewer public entries and detached signatures now
  validate with distinct key IDs, identities, trust domains and roles; neither
  private key nor passphrase was received or read. The signed evidence-only
  acceptance keeps all eight authority fields false and has raw SHA-256
  `d592e24c1095ed16019ed306b1e6431909d0d6ef355456d231698cd6bd09134f`;
  keyring digest is
  `a83cfac0c2a61edb83480ae782e077d3fafc6401b3e2f1694aeebf6fd24b113c`.
  Its root-owned read-only production one-shot from commit `60bc058` returned
  `DORMANT_SUPERVISOR_VERIFIED_AUTHENTICATED_EVIDENCE` and inner
  `AUTHENTICATED_EXACT_EVIDENCE_ACCEPTED`. The reader remains `NOLOGIN`, its
  credential is absent, and no issuer, dump, restore, customer-row read or
  production mutation occurred. A pre-deploy review caught that a two-hour
  acceptance must not be bound to the six-hour recurring timer; candidate
  commit `1357640` was never deployed, the recurring supervisor remains
  active/enabled and its post-rollout result is the expected `AUTH_PENDING`.
  Focused verification passes 21 tests with one sandbox systemd-bus skip;
  changed-scope scans and systemd verification pass. Evidence:
  `docs/e0-3-bot-b5-3-064a-public-key-intake-unsigned-acceptance.v1.json` and
  `docs/e0-3-bot-b5-3-064a-authenticated-evidence-acceptance-rollout.v1.json`.
  An unrelated duplicate `/swapfile` line in `/etc/fstab` caused
  systemd-generator errors during daemon-reload; swap remains active and
  failed units are zero. It was observed, not changed. Exact next: implement
  and independently review a separate fail-closed activation entrypoint plus
  disposable rehearsal requiring a new activation-specific owner/reviewer
  decision. Current evidence grants no LOGIN/credential/refresh/064B/064D.
  Termux exposed a false `--help` error receipt before key generation; commit
  `bfe53faaba17a4e9e0cca83024f602d9d59c965a` fixes `SystemExit` handling and
  is pushed. Current secret-free signing kit `/root/k2.tar` has SHA-256
  `42582645ccc35e9888f46f6edf07b8861a06819eb89c24d45bfd177f4ffa02c6`;
  current signer SHA-256 is
  `ca1fedebe4fba5498a72260aa2957c697170b8ef5b327c75bcf2565a88694879`.

- 2026-08-23 E4 retained status is `IN_PROGRESS` with a `NO_GO` gate decision.
  The experimental one-shot and its server entry point are
  hard-disabled; legacy `e4_memfd_handoff.py` is superseded and fails closed
  because it transferred decrypted private-key bytes remotely. The payload
  generator is pinned to the exact E4 schema/bindings and 15-minute window
  (SHA-256 `7ec69b2effe9eca673b82900839c3a7d98e22a70ea334a391c97162aab5d6cc0`);
  focused generator tests pass 10/10, compilation and diff checks pass. Per
  owner direction, E4 verifier/executor were not rerun. v11-v13 are expired and
  non-current; v12/v13 used the rejected 30-minute drift. No Docker,
  PostgreSQL, decryption, production contact or private-key access occurred.
  Evidence: `docs/e4-one-shot-safety-freeze.v1.json` and updated
  `docs/e4-owner-payload-refresh-generator.v1.json`. Exact next canonical item:
  freeze a versioned v2 plan/receipt contract that retains the immutable
  ciphertext but proves destruction of the disposable target and transient
  plaintext; no new ceremony before independent review of that contract.

- 2026-08-23 E4 delivery diagnostic and refresh: SSH to `185.236.228.19`
  successfully reaches `obsidian69.io`, but the remote host did not contain
  the v6 payload. A pasted newline split the remote shell command and caused a
  secondary `REMOTE_FILE_OK: command not found` message. The v6 window expired
  and must not be signed or reused. Prepared fresh public payload
  `E4-owner-handoff/e4-owner-decision-payload.v7.json`, SHA-256
  `2440b60f8a0c62fcd093b5ad51c515d4f01373915a3ba339003e79f967e4c480`, with a
  new nonce/window and the same exact frozen snapshot/target binding. Added
  `E4-owner-handoff/08-e4-v7-owner-signing-instruction.md` and
  `docs/e4-owner-payload-v7-preparation.v1.json`; JSON and diff checks pass.
  Owner/reviewer signatures, trusted time, fresh replay consumption, key-FD
  handoff and execution remain false. Next canonical item: copy v7 to the
  controlled offline device, sign the exact bytes, then obtain the independent
  reviewer envelope; E4 remains non-production and execution-prohibited. An
  attempted workspace-to-server SCP did not upload the file because the server
  presented a changed SSH host key
  (`SHA256:QY5T7dl5kDMu7rvqx+Ndz91oFawIzt5JaaF4EsSQupc`) versus the local
  known-host entry; do not remove or accept the old key until the owner
  verifies the fingerprint from the authenticated server console. The owner
  verified it; the server then rejected the Codex workspace SSH key, so manual
  password-authenticated upload from Termux is required. The owner then
  confirmed the Termux source file was missing, so v7 could not be uploaded.
  Prepared fresh public payload
  `E4-owner-handoff/e4-owner-decision-payload.v8.json`, SHA-256
  `251c8a8851c688701905fd99a6a744d25bc636d8fb380896cd84c77a94cb7ac1`, with a
  new nonce/window and the same exact frozen snapshot/target binding. Added
  `E4-owner-handoff/08-e4-v8-owner-signing-instruction.md` and
  `docs/e4-owner-payload-v8-preparation.v1.json`; JSON and diff checks pass.
  Next canonical item: download v8 to the controlled offline device, verify
  the exact SHA, then sign and obtain the independent reviewer envelope.
  Owner later confirmed that v8 was uploaded to
  `/root/E4-owner-handoff/e4-owner-decision-payload.v8.json` on
  `obsidian69.io`; remote SHA-256 matched exactly, but no adjacent `.sig` file
  existed and the v8 window expired. A proposed manual jq-based v9 refresh was
  split by the chat/terminal copy path and failed before producing a valid v9;
  it granted no authority and must not be used. Stop manual JSON editing. The
  next safe prerequisite is an operator-friendly fresh-payload generator or
  another exact transport that requires no long pasted command.

- 2026-08-23 owner conversationally confirmed reuse of the existing encrypted
  snapshot and retention of its ciphertext after the rehearsal. Prepared the
  fresh public payload
  `E4-owner-handoff/e4-owner-decision-payload.v6.json`, SHA-256
  `2e7779db75a894be076753ab40ce5c2493bd22ca8895e75f8765c133dd14a0af`, with a
  new approval window/nonce and the previously owner-selected target, which
  was never created. Added the offline signing instruction
  `E4-owner-handoff/08-e4-v6-owner-signing-instruction.md` and evidence
  `docs/e4-owner-payload-v6-preparation.v1.json`. JSON, exact snapshot/target/
  manifest binding, fail-closed authority and diff checks passed. This is not
  cryptographic authorization: owner/reviewer signatures, trusted time, fresh
  replay consumption, ephemeral key-FD handoff and execution remain false.
  Next canonical item: offline owner signature on v6, then independent
  reviewer envelope/signature; do not sign or reuse v5.

- 2026-08-23 E4 hardened-executor verification recheck completed without
  invoking the current file-backed gate, Docker, PostgreSQL, age, production,
  secrets or private keys. Stdlib suites passed: executor 10/10, authoritative
  callbacks 3/3, preflight 3/3, replay registry 6/6 and owner/reviewer
  verifier 3/3; Python compilation and `git diff --check` passed. Broad
  discovery remains environment-limited because host `pytest` is unavailable
  (14 import errors were not counted as gate evidence). Evidence:
  `docs/e4-hardened-executor-verification-recheck.v1.json`. E4 remains
  `IN_PROGRESS`/non-production; the staged snapshot is still
  `STAGED_NOT_AUTHORIZED`, and the next canonical item is a fresh authenticated
  owner receipt plus approved ephemeral key-FD handoff and explicit snapshot
  retention/teardown decision.

- 2026-08-22 E4 trust-root public key remains staged at
  `E4-owner-handoff/e4-trust-root.pub`, fingerprint
  `SHA256:Ja+GZ9/o52eFmzZDztpju70RWmYpSvc0Fp+ayO1GcfM`; the owner attested its
  separate offline origin and that private material remains offline. The
  existing trust-root private key was used locally to sign the bounded
  promotion payload; it was not sent to the server.

- 2026-08-22 owner payload v5, reviewer envelope v4 and the DigiCert RFC 3161
  evidence are cryptographically verified, including exact cross-binding,
  message imprint, nonce and pinned responder chain. Evidence remains test-only
  and non-production. Hashes: owner signature
  `4be6ffd27a816983cfac8767035402765aefbfc11eb208af6ba2769919591f02`, reviewer
  signature `7697bd2660ae3b2594d4d35feb0e1f905840ce7f87385782082eced76aa85ccd`,
  TSA evidence `56789ace73f80579ddd5111a35861929404202eca2e24464dcf4f6e246db6377`.

- 2026-08-22 trust-registry promotion was verified with the existing
  `e4-trust-root` signature. The result is `VERIFIED` with
  `registryStatus=AUTHENTICATED_ACTIVE`, `trustedClockAttested=true` and
  `replayEligible=true`; execution and production flags remain false. The
  promotion payload is
  `E4-owner-handoff/e4-trust-registry-promotion-payload.v1.json` (SHA-256
  `63635fad160683ca50496831e4cdcc418c346e226def3e612cfec0b7b1f8458a`), with
  signature SHA-256
  `5668d7eadffc3025edb940d3ed170b356c1262d63edbc97bb990eaa1ca91e713`.

- 2026-08-22 one bounded claim was consumed in the temporary SQLite replay
  registry for the exact owner/reviewer/timestamp artifact. Evidence is
  `E4-owner-handoff/e4-authenticated-owner-reviewer-replay-evidence.v1.json`,
  SHA-256 `1d8edfbddf4640cef659e8026b7add968d211b1835073a27f5df5a69792251fd`.
  The claim must not be retried; the temporary ledger is not production state.

- 2026-08-22 active route remains E4 / owner-gated disposable full-snapshot
  rehearsal. All required handoff keys and signatures are now complete; no new
  key is needed. The hardened executor boundary is now implemented but remains
  `IN_PROGRESS`/not accepted by the authoritative verifier; no Docker/
  PostgreSQL target was created, no production service was contacted, and no
  execution occurred.
  Promotion/replay/verifier/preflight focused tests pass `15/15`; Python
  compilation and `git diff --check` are clean.

- 2026-08-22 implemented `relay/core/e4_hardened_executor.py` with a bounded
  injectable runtime and pinned Docker/age adapter. It requires authenticated
  trust plus a separate consumed replay gate, exact target/label binding,
  inode/digest snapshot verification, and an external ephemeral key FD only;
  it never accepts key bytes/path or persists plaintext snapshot files. Docker
  controls are network-none, read-only-root, tmpfs-only, non-root,
  cap-drop/no-new-privileges, no host bind/port, bounded health/restore and
  ownership-aware teardown. Evidence is
  `docs/e4-hardened-executor-review.v1.md`; executor/provider tests pass
  `10/10`.
  The original staged ciphertext is retained, not deleted automatically. The
  implementation is non-production and synthetic-only; independent review and
  a fresh exact owner/reviewer/replay receipt are still required because the
  existing one-shot claim is consumed and its owner window is not reusable.

- 2026-08-23 independent E4 executor review found and fixed replay-claim to
  formal-consumption binding, receipt plan/target/snapshot/boundary binding,
  parent/inode/hardlink snapshot checks and linked-file key-FD rejection.
  Review evidence is
  `docs/e4-hardened-executor-independent-review.v1.md` with verdict
  `PARTIAL_PASS_NON_PRODUCTION`; executor/provider/binding tests pass `10/10`.
  The concrete lazy verifier → replay claim → receipt adapter is now covered
  by `3/3` tests with real temporary ledgers and synthetic public artifacts.
  No current claim was retried or invoked. Remaining blockers are a fresh
  owner-gated receipt, approved ephemeral key-FD handoff and the explicit
  staged-ciphertext teardown decision.

- 2026-08-23 added
  `relay/core/e4_authoritative_gate_callbacks.py` as the concrete E4 authority
  composition boundary. It binds the file-backed trust-root/promotion verifier
  to the one-shot replay registry and formal receipt ledger, checks artifact
  context against the exact runner plan/target/snapshot/boundary, and fails
  closed if receipt consumption fails after a committed claim. Construction is
  side-effect free; tests use only synthetic public artifacts and temporary
  SQLite ledgers. The current expired owner window and consumed claim were not
  touched; no Docker, PostgreSQL, age, production service, secret or private
  key was accessed. E4 remains `IN_PROGRESS`/non-production.

- Historical E4 handoff setup details from before the promotion/replay
  verification: public, secret-free templates and the staged encrypted
  snapshot exist under `/root/E4-owner-handoff`; at that earlier point, no
  owner receipt, executor authority, production contact or target execution
  existed. The historical owner public
  key is `owner-signing.pub` (fingerprint
  `SHA256:rH+p26jdfF3/NIt+7g+jgST6t1qrU0xr6FPeLopipYU`) and its private half
  was not found. The current replacement public owner key is
  `owner-signing-v2.pub` (fingerprint
  `SHA256:G4szs+1DvEQygs3LZS1LDNNRyBYLUHZuX0a7C/gRjII`); its private half and
  passphrase remain offline. The distinct reviewer key fingerprint is
  `SHA256:fectcTsd7rxR2gztCa+SmgJ6wzbeJKqYDS1W7JsACyU`.

  Owner conversationally selected `targetRef=e4-disposable-pg-20260822-02`
  with deterministic fingerprint
  `3545e043156cd9023d46a5ebaaa12f0c964ceea2887cea79c9703395a1588ad3`; no
  target was created. The ciphertext is `0400`, immutable (`i`), inode
  `2412135`, device `801`, one hardlink, and SHA-256
  `47efc0dc293890243072bdf048d40cbcc1fee8fbe719e4b841fb5d156f658b3e`;
  staged manifest records immutable handle `fs-801-2412135` and remains
  `STAGED_NOT_AUTHORIZED`. The v2 public trust-anchor candidate is
  `/root/E4-owner-handoff/e4-owner-reviewer-trust-anchor-and-binding-candidate.v2.json`
  (SHA-256
  `6156d9d88b68245377e33065b432f78a7647510a6264c868e25a89fd20936f73`), with
  all authority flags false. The prior v1 payload expired unsigned after the
  missing private key was discovered. The v2 payload at
  `/root/E4-owner-handoff/e4-owner-decision-payload.v2.json` was signed with
  owner-signing-v2 and verified against the staged public key; payload SHA is
  `9bcbce998a68b39efa23b9573597838b09f9847063da6bba5a2cdd837eda7dd7` and
  owner-signature SHA is
  `11064f48d93ae7d9e1aab9f596d3caa017cf4228fc0936afb07dca07224c031b`.
  A public reviewer envelope was prepared for v2 at
  `/root/E4-owner-handoff/e4-reviewer-review-envelope.v1.json` with SHA-256
  `c78d2a126e0dea9b12eddf93988b472d4ef5844f15e8f342fd8dffe7dbc3d068`, then
  marked superseded because the owner payload window expired before reviewer
  signing. The previous v3 payload used a reviewer private key that was
  unavailable on the current device; its reviewer envelope is superseded. The
  replacement public reviewer key is staged at
  `/root/E4-owner-handoff/reviewer-signing-v2.pub`, fingerprint
  `SHA256:3YtNkuP+qf7PIcj9AmqSSTLr+Ocd4luwbeQSB8oRNq4`, public-file SHA-256
  `79013979c27cae19fc304269fd390861cb7bdd561d2ca955b96eda8a9e29a095`.
  Trust-anchor candidate v3 is staged at
  `/root/E4-owner-handoff/e4-owner-reviewer-trust-anchor-and-binding-candidate.v3.json`
  with SHA-256
  `d6cd4f6d65db765ffe1c6b446b56ddb6fdd8a3a340650e36c28ac06bc5c3ccad`, all
  authority flags false. The replacement v4 owner payload is staged at
  `/root/E4-owner-handoff/e4-owner-decision-payload.v4.json` with SHA-256
  `6ba630bd3de5ba2149fbf420b420eec917194d21e159172dcca2b7adfc24a672` and was
  signed with owner-signing-v2; the verified owner-signature SHA-256 is
  `8d3d003e9cf661f86b51b9064aae2be89d091a463ac9ff6fa2617a38393e1c4c`.
  A fresh reviewer envelope is staged at
  `/root/E4-owner-handoff/e4-reviewer-review-envelope.v3.json` with SHA-256
  `8702959ff95b4c79864c3f55ac07d418f017a96f8b193c07385e26dfae2429f2`, bound
  to the exact v4 payload/signature and replacement reviewer key. Its reviewer
  signature SHA-256 is
  `04722c9b6c8e92690b0f1af0fc04a3a7e317494f8168d1bdf82503e6457dd2b9` and was
  verified with the expected namespace/issuer. Cross-binding of payload,
  signatures, reviewer public key, plan, target, snapshot, scope and expiry
  passed; authority remains false. Added the non-executing verifier at
  `relay/core/e4_owner_reviewer_verifier.py` and focused stdlib regression/
  tamper tests passed `3/3`; evidence is in
  `docs/e4-owner-reviewer-verifier-review.v1.md`. Its actual-clock check found
  v4 expired (`OWNER_WINDOW_NOT_CURRENT`) while still confirming both
  signatures and exact binding. Next exact step is an authenticated trust
  registry/replay decision and hardened executor review; do not reuse v4 or
  contact Docker/production. Added the temporary one-shot replay ledger at
  `relay/core/e4_owner_reviewer_replay_registry.py`; its focused harness passed
  `6/6` and refuses the current evidence-only verifier result unless a future
  result explicitly proves `AUTHENTICATED_ACTIVE`, trusted clock and
  `replayEligible:true`. Evidence is in
  `docs/e4-owner-reviewer-replay-registry-review.v1.md`; authority and launch
  status remain unchanged. Added pure hardened executor preflight at
  `relay/core/e4_hardened_executor_preflight.py`; its focused landmine harness
  passed `3/3` and a complete synthetic proof still returns
  `executionEligible:false`. Evidence is in
  `docs/e4-hardened-executor-preflight-review.v1.md`; authenticated trust,
  trusted clock, eligible replay integration, actual executor and cleanup
  proof remain open. This historical setup entry is superseded by the current
  promotion/replay status above; the hardened executor remains the sole active
  blocker.

- 2026-08-22 read-only backup inventory found a real PostgreSQL custom dump at
  `/var/backups/obsidian-exchange/postgres/obsidian_exchange-cutover-20260810.dump`
  (459703 bytes, SHA-256
  `d61b888edabf3ff69cbbe861a5ea33f8b8f172b9a01e2a94f4bab82627dcf001`) with a
  matching checksum file, but it is not encrypted or E4-bound. The
  `/root/backups/exchange_*.db.gz.enc` files are OpenSSL-encrypted SQLite
  backups using a private local key and are not qualified PostgreSQL E4
  snapshots. No candidate was opened, decrypted, copied, or connected to.
  The encryption recipient and owner signing public key are now supplied;
  next exact input is the target-bound authenticated owner decision plus
  independent reviewer evidence. Only then may the existing PostgreSQL dump
  be staged as a new encrypted, provenance-bound E4 copy.

- 2026-08-22 owner supplied a public SSH Ed25519 recipient generated on an
  Android device; no private key or passphrase entered the server. Installed
  Ubuntu `age` and streamed the pre-existing PostgreSQL custom dump into
  `/root/E4-owner-handoff/obsidian_exchange-cutover-20260810.dump.age`.
  Ciphertext is 460027 bytes, mode `0600`, format `age encrypted file,
  ssh-ed25519 recipient`, SHA-256
  `47efc0dc293890243072bdf048d40cbcc1fee8fbe719e4b841fb5d156f658b3e`.
  Added `e4-disconnected-snapshot-staging-manifest.staged.v1.json`; JSON and
  secret-pattern checks passed. No plaintext was opened by the agent, no
  decryption or production contact occurred. Status remains
  `STAGED_NOT_AUTHORIZED`: immutable-handle proof, authenticated owner
  decision, independent review, target binding, and full executor remain
  pending/blocked.

- 2026-08-22 owner supplied the separate public signing key generated on
  Android; only the public line was staged at
  `/root/E4-owner-handoff/owner-signing.pub` and its Ed25519 fingerprint was
  verified with `ssh-keygen`. No signing was performed because the canonical
  payload still needs exact target binding and an independent reviewer; the
  encryption key is not reused for signatures.

- 2026-08-22 E4 owner-gated fresh-rehearsal launch preflight completed
  read-only at `docs/e4-owner-gated-fresh-rehearsal-preflight.v1.json`.
  No authenticated owner decision/eligible receipt, pre-existing
  production-disconnected encrypted snapshot, E4 executor or reusable target
  exists; the historical target/snapshot were destroyed and generic encrypted
  backups lack E4 binding/provenance. Docker showed only existing non-E4
  `obsidian-postgres` and `e03-relay-p5b-rehearsal`; no E4 target. Systemd/
  netlink diagnostics were sandbox-blocked. Two independent reviews returned
  `NO_GO_BLOCKED_OWNER`; no production DB, secrets, Docker execution, snapshot
  read or file mutation occurred. Next exact input is the authenticated owner
  receipt plus pre-existing disconnected snapshot; executor launch remains
  prohibited.

- 2026-08-22 active route is E4 / disposable full-snapshot rehearsal. Added
  the keyless test-only formal receipt-consumption boundary in
  `relay/core/e4_rehearsal_receipt_consumption.py`; the receipt now carries
  owner-window plus opaque snapshot/key-reference digests, and an explicitly
  temporary SQLite ledger atomically records one `CONSUMED` claim while
  concurrent/replayed claims return `REPLAY_BLOCKED`. Before-commit faults
  roll back; after-commit ambiguity blocks retry. Capability output separates
  `rehearsalInvocationAllowed` from `moneyActionAllowed:false`. Stdlib flow,
  concurrency/fault checks, compile and diff checks passed; pytest is
  unavailable. Independent reviews accepted this as a bounded prerequisite but
  retained blockers: no authenticated owner/trust root, trusted clock,
  content-bound snapshot/key proof, full 12-step executor, hardened Docker,
  TOCTOU-safe target ownership or cleanup proof. E4 remains `IN_PROGRESS`;
  no production contact/mutation occurred. Next canonical item is an
  owner-gated fresh rehearsal with a real exact receipt and a pre-existing
  production-disconnected encrypted snapshot.

- 2026-08-22 implemented the next safe E5/Android slices as rehearsal-only
  pre-auth, assertion-preflight and inert RP route boundaries at
  `native-wallet/rehearsals/attestation-dependencies/automated-minimal/tests/support/e5_android_webauthn_preauth.py`
  and `.../e5_android_webauthn_rp_contract.py`.
  They create distinct reviewer/owner challenge links, expose only pure GET/
  POST route responses and preflight a bounded
  WebAuthn assertion envelope: closed shape, canonical Base64URL, strict client
  JSON, exact challenge/origin, RP hash, 37-byte authenticator data and flags
  `0x05`. They deliberately have no Android API, RP endpoint, credential
  registry, revocation lookup, ES256 verification or authority; all
  auth/selection/crypto/runtime flags remain false. Focused direct harness
  passed 24/24; ADR-0032 and the beginner runbook were updated. The RP adapter
  has no socket, persistence, replay ledger or production route; the optional
  HTTPS harness is loopback-only, requires explicit TLS files and is never
  auto-started. E5 remains `BLOCKED_OWNER`; the next real step is an
  isolated staging HTTPS RP/verifier with an owner-approved domain/certificate,
  followed by credential enrollment and independent authenticated decisions
  over the exact envelope. No phone credentials were created.

- 2026-08-22 the proposed `pay.obsidianbtc.org` RP domain was rejected by
  read-only safety preflight. Existing E0.4 evidence classifies it as a public
  payment alias wildcard-proxying `/` to an unowned/unproven `127.0.0.1:8080`
  upstream; a current HTTPS probe timed out. No Nginx/DNS/certificate/service
  state was changed. The local harness now rejects non-loopback RP IDs. The
  real next item is a separately owned staging subdomain (for example
  `webauthn-staging.obsidianbtc.org`) with explicit DNS/TLS/deployment authority.

- 2026-08-22 phone-only feasibility reviewed for E5 owner/reviewer auth.
  Working recommendation (not yet owner-selected): dual WebAuthn human issuers
  with device-bound/non-backup credentials; ordinary synced phone passkeys are
  not assumed valid because the current profile requires `backup_eligible:false`
  and exact UP/UV, RP/origin and `0x05` flags. If phones cannot produce that
  state, each participant needs a separate device-bound FIDO2 authenticator via
  phone NFC/USB-C or an explicit owner-approved profile change. No credentials
  were enrolled; the repository has no Android APK/web RP endpoint or live
  verifier yet, so no phone action should be attempted. E5 remains
  `BLOCKED_OWNER`.

- 2026-08-22 added the beginner-oriented implementation guide
  `docs/e5-owner-reviewer-authenticated-handoff-runbook.md`. It explains the
  distinction between decision result, owner/reviewer assertions and handoff;
  exact public inputs/hashes; two-device reviewer-first then owner-countersign
  flow; secret handling; verifier checks; and why the existing E0.3 signer
  cannot be reused for E5. The guide records the real remaining prerequisites:
  concrete E5 decision-result fixture, owner-approved authentication method
  (DSSE offline roots or dual WebAuthn) and an actual trust-registry/replay
  verifier. No authentication or production authority was implemented.

- 2026-08-22 canonical E5 owner/reviewer preflight повторно подтвердил
  `BLOCKED_OWNER`: restrictive deferral bindings к decision-result schema,
  owner/reviewer handoff schema и scorecard совпадают по SHA-256, но реального
  authenticated owner decision или independent-reviewer decision artifact в
  docs/native-wallet нет. Synthetic tests и inert schemas не являются
  evidence; conversational `давай` не превращается в подпись. Issuer
  selection, crypto, runtime и production authority не активированы. Для
  продолжения нужен новый exact-envelope handoff с двумя независимыми
  аутентифицированными решениями; до этого дальнейшая design-only цепочка не
  является canonical progress.

- 2026-08-22 E5 retention/deletion audit boundary completed as the next
  bounded keyless slice under the restrictive owner/reviewer deferral. The
  closed deletion receipt now binds bundle/policy/workspace-inventory/deletion
  plan digests, caller nonce and canonical self-digest; receipt ID and nonce
  replay block consumption. Complete requires ordered trigger/completion time,
  full location inventory, zero failures/backups and a distinct independent
  witness; PARTIAL/FAILED/UNKNOWN and physical-erasure claims fail closed.
  Added ADR-0031 and two regression tests; retention module passes 8/8, full
  E5 Ed25519 stdlib harness passes 139/139 across 20 modules, offline Cargo
  tests pass, and JSON/diff integrity checks are clean. `pytest` remains
  unavailable. No external workspace, sensitive evidence, deletion, store,
  crypto or runtime authority exists. E5 issuer selection and owner/reviewer
  handoff remain `BLOCKED_OWNER`; next canonical item is the real
  authenticated accountable-owner plus independent-reviewer decision over the
  exact current envelope.

- 2026-08-22 E5 issuer-selection owner/reviewer handoff получил restrictive
  deferral в `docs/e5-issuer-selection-owner-reviewer-deferral.v1.json`.
  Deferral SHA-256-биндит decision-result schema, owner/reviewer handoff
  schema и scorecard; разговорный контекст не считается аутентифицированной
  подписью, все authority-флаги false, разрешены только
  keyless/read-only/non-production/docs-and-tests. В качестве следующего
  bounded пункта завершён persistence/fault audit boundary: ADR-0030 и два
  regression-теста фиксируют atomic audit/state commit, CAS, single-invocation
  external intent, `UNKNOWN_REVIEW` recovery и checkpoint-unavailable block.
  Stdlib E5 Ed25519 harness прошёл 137/137 в 20 модулях; `pytest` по-прежнему
  недоступен, `git diff --check` чистый. E5 owner/reviewer/issuer selection
  остаются `BLOCKED_OWNER`; следующий безопасный пункт — retention/deletion
  audit boundary, либо реальная authenticated owner+reviewer handoff при
  появлении обоих доказательств.

- 2026-08-22 E5 owner/independent-reviewer decision handoff boundary completed
  as the final keyless preparation slice. The closed handoff binds exact
  decision-result/context/scorecard digests, separates owner/reviewer roles,
  identities, trust domains and assertion digests, and enforces 24-hour
  freshness, future skew, single-use handoff ID/nonce and self-digest. Context,
  role/domain/assertion reuse, replay, time, shape and authority drift fail
  closed. Structural handoff validity is not consumability; synthetic ACCEPT
  pairs remain evidence-only with all auth/selection/production flags false.
  Focused handoff harness passed 6 tests; `pytest` remains unavailable. Next
  canonical item is a real authenticated owner plus independent-reviewer
  decision over the exact envelope; status `BLOCKED_OWNER`.

- 2026-08-22 E5 immutable issuer-selection decision-result envelope audit
  completed as a test-only contract. Added a closed schema and validator whose
  canonical self-digest covers outcome, candidate, `selected_option:null`, exact
  handoff/context, source digests, domain, timestamps and caller nonce. It
  enforces four outcomes, ten-minute lifetime, future skew, unique decision ID
  and single-use decision ID/nonce; context, digest, field, time and replay
  drift fail closed. Focused scorecard harness passed 14 tests; `pytest` remains
  unavailable. No owner decision, issuer authentication, selection, crypto or
  runtime capability exists. Next: audit explicit owner/independent-reviewer
  decision handoff boundary.

- 2026-08-22 E5 final issuer-selection decision boundary audit completed as a
  test-only contract. Added four explicit non-authoritative outcomes:
  `NOT_EVALUATED`, single-candidate review required, tie requiring a separate
  ADR and blocked invalid state. Automatic selection, selected-option drift,
  current-state drift and capability-flag mutation all fail closed; synthetic
  all-pass input never grants authority. Focused scorecard harness passed 11
  tests; `pytest` remains unavailable. No issuer/authentication/crypto/runtime
  capability exists. Next: audit the immutable decision result envelope,
  outcome/context digest binding and replay/freshness limits.

- 2026-08-22 E5 issuer-selection scorecard handoff audit completed as a
  test-only contract. Added a closed six-field handoff binding scorecard,
  independence, supporting-bundle, conflict-matrix and issuer-challenge
  digests plus review domain; cross-contract name drift is rejected. The
  conjunctive evaluator now requires exact common/option-specific gate sets,
  canonical digest evidence, minimum evidence cardinality and all gates `PASS`;
  omissions, extras, invalid states and missing evidence fail closed. Frozen
  state remains `NOT_EVALUATED`, `selected_option:null`, with no issuer,
  authentication, crypto or runtime authority. Focused scorecard harness passed
  9 tests; `pytest` remains unavailable. Next: audit the final
  non-authoritative issuer-selection decision boundary and tie rule.

- 2026-08-22 E5 supporting-evidence bundle and control-conflict audit completed
  as a test-only contract. The closed bundle validator now binds expected
  independence/scorecard/challenge/review-domain context, all 14 unique
  canonical artifact records, `COMPLETE` status, hash-only external bytes,
  bounded issue/lifetime, capture ordering and artifact expiry coverage. Matrix
  checks now reject extra/missing/duplicate/invalid cells, enforce the exact
  transitive relationship inventory and explicitly forbid waivers, majority
  scores and compensating controls. Focused stdlib harness passed 8 tests; no
  evidence bytes, acceptance, issuer authentication, selection, crypto or
  runtime capability exists. `pytest` remains unavailable. Next: audit issuer-
  selection scorecard handoff and exact digest bindings.

- 2026-08-22 E5 independence-evidence issuer authentication boundary audit
  completed as a test-only contract. Challenge coverage now asserts the exact
  closed field order and rejects selected-root drift, stale/over-future context,
  revocation-epoch rollback and caller-nonce replay. Pair coverage validates the
  closed independence record, `INDEPENDENT` decision, all nine schema-declared
  cross-review fields and three within-record separation groups. Focused stdlib
  harness passed 10 tests; no issuer assertion, root selection, evidence
  acceptance, crypto call or runtime integration exists. `pytest` remains
  unavailable. Next: audit the supporting-evidence bundle and control-conflict
  matrix boundary.

- 2026-08-22 E5 reviewer-result authentication handoff audit completed as a
  test-only contract. The closed external-result schema/helper now carries and
  checks all 11 ADR-0024 mandatory bindings: review request, assertion,
  challenge, evidence, credential/revocation, verifier build/policy, result
  issue/expiry and caller nonce. It rejects extra/missing fields, digest/context
  drift, expired/future timestamps, caller-supplied consumed nonce/evidence and
  non-authoritative green claims. Added schema↔shortlist regression coverage.
  Focused stdlib harness passed 27 tests (including 3 provenance tests); native
  Rust 50/50, isolated parser 11/11, Clippy/rustfmt clean. No result signer,
  issuer/root selection, credential enrollment, verifier trust or runtime
  capability exists; `pytest` remains unavailable. Next: audit the
  independence-evidence issuer authentication challenge and pair-separation
  boundary.

- 2026-08-22 E5 Ed25519 corpus independent-review gate audit completed as a
  test-only boundary. The closed response/pair policy now validates the exact
  response shape, binds review time and assertion-envelope digest into the
  WebAuthn challenge, rejects generator identities and malformed/expired/future
  responses, and rejects cross-review reuse of evidence, credential roots,
  recovery authorities or assertion envelopes. The review request's bound
  authentication-fixture digest was updated; no real response, credential,
  verifier, trust root or runtime authority exists. Direct stdlib harness:
  6 review-bundle and 3 provenance tests passed; native Rust remains 50/50,
  isolated parser 11/11, strict Clippy/rustfmt clean. `pytest` is unavailable,
  so Python tests were invoked directly through the stdlib harness. Next:
  audit the verification-only reviewer-result authentication handoff boundary;
  issuer selection and authenticated acceptance remain blocked.

- 2026-08-22 E5 verification-only BIP340 foundation slice completed after the
  owner's explicit E5 reprioritization. The existing pinned 19-row official
  corpus now has an executable SHA-256 provenance assertion; the test-only
  parser, locked secp256k1 verification harness and key/message/signature/
  length mutation cases pass. Rust workspace tests: 50 passed; strict Clippy
  and rustfmt checks passed. No application verifier, key material, key
  installation, signing, trust activation or network capability was added.
  `pytest` was unavailable in the host shell, so the Python E5 suite was not
  run in this slice. Next: implement the verification-only application
  message-binding preimage contract with field/domain/length drift tests.

- 2026-08-22 E5 application message-binding slice completed as a test-only
  contract. The harness now rejects unsupported domains and oversized signer
  identifiers, binds the exact ADR-0003 tagged SHA-256 preimage and passes
  field/domain/length drift cases. It remains outside wallet-core/UniFFI with
  no signature verification, key installation, approval acceptance or trust
  activation. Next: independently audit and finalize the existing
  verification-only terminal decision matrix.

- 2026-08-22 E5 terminal decision-matrix audit completed. The symbolic
  test-only matrix now rejects oversized claim sets and duplicate active slots
  as `MALFORMED_BINDING`, retains exact 2-of-3 quorum semantics and leaves the
  positive result non-authoritative. Rust verification remains required before
  any later slice; no key, signature, trust or runtime capability was added.
  Next: independently audit the existing active-key-set evidence mapping.

- 2026-08-22 E5 active-key-set evidence audit completed. The test-only mapping
  contract now rejects reviewer overlap with signer slots and explicitly covers
  duplicate slot ordering plus review-time/content drift, while retaining exact
  ceremony-set, x-only key and commitment-set binding. Reviewer claims remain
  unauthenticated and no key/trust/runtime authority exists. Next:
  independently audit the existing keyset review-acceptance bundle.

- 2026-08-22 E5 keyset review-acceptance audit completed. The test-only bundle
  now has explicit regression coverage for unknown domains, reviewer ordering,
  zero/before-window observations and the bounded validity interval, while
  retaining exact ceremony/mapping/algorithm binding and the
  `REVIEW_CLAIMS_BOUND_NON_AUTHORITATIVE` result. No attestation verification,
  key installation or trust activation exists. Next: audit reviewer-identity
  policy and attestation envelope boundaries.

- 2026-08-22 E5 reviewer-policy and human WebAuthn-envelope audit completed.
  Reviewer policy now receives the active signer set and rejects reviewer
  overlap; existing checks cover independent domains/roots/recovery authorities,
  replay, revocation epoch and bounded freshness. The envelope now binds the
  exact expected evidence ID and challenge while remaining structural only:
  signature verification, enrollment authentication and acceptance are false.
  Next: audit the automated build-attestation envelope.

- 2026-08-22 E5 automated build-attestation envelope audit completed. The
  test-only review now requires an independently supplied rebuild SHA-256 in
  addition to checking envelope subject equality, DSSE/SLSA identifiers,
  builder/source, exact dependency order, allowlisted external parameters and
  canonical digest fields. Signature/root/builder authentication and
  reproducible-build acceptance remain false. Next: audit DSSE PAE/parser
  limits and the closed semantic decision boundary.

- 2026-08-22 E5 DSSE PAE/parser and semantic-boundary audit completed. The
  test-only parser limits now explicitly gate ASCII payload types and optional
  `keyid`; canonical Base64 and exact public PAE remain covered. The symbolic
  decision matrix now tests invalid-signature short-circuiting before all later
  payload/policy checks. No parser, crypto verifier, root or authority was
  added. Next: audit DSSE source-provenance and corpus-manifest boundaries.

- 2026-08-22 E5 source-provenance and corpus-manifest audit completed. Added a
  stdlib-only metadata policy test that verifies immutable revisioned raw URLs,
  source/derived fixture hashes and no-key/no-authority flags, plus cross-field
  corpus rules for unique case IDs, independent reviewer/result domains,
  offline generators, sealed expectations and corpus-hash agreement. Its three
  unittest cases pass; the Rust workspace remains 50/50 with strict Clippy and
  rustfmt clean. No source was fetched or executed; no verifier or runtime
  authority was added. Next: audit the isolated strict attestation parser
  rehearsal boundary.

- 2026-08-22 E5 strict attestation parser and dependency-boundary audit
  completed. Added a stdlib-only policy test binding all three isolated Cargo
  profiles' lock SHA-256 values, registry counts, exact direct versions and
  standalone workspace boundaries to `RESULTS.json`; it also proves the native
  wallet workspace excludes those rehearsal roots and dependencies. The
  `automated-minimal` rehearsal passed 11 offline tests and the schema comparison
  profile compiled offline. No external source was fetched or executed, and no
  signature/key verification, trust-root installation, runtime authority or
  UniFFI surface was added. Next: audit the Ed25519 corpus independent-review
  gate.

- 2026-08-22 strict roadmap status audit: no complete E0–E5 production stage is
  `VERIFIED`, so production-readiness completion is 0/6 stages under the
  charter. E0 has 2/5 criteria `VERIFIED` (E0.2/E0.5), E0.1 is `SUPERSEDED`,
  and E0.3/E0.4 remain `IN_PROGRESS`; this is not a claim that only 0% of code
  exists. E1 has a keyless/read-only partial surface but its full gate is open;
  E2/E3 remain offline-foundation `NO_GO`; E4 is `IN_PROGRESS` with dormant
  action UX and 145 bounded tests; E5 is a non-shipped native scaffold. No
  production push is authorized while E0.3 is the first unmet gate.

- 2026-08-22 the owner explicitly authorized one bounded keyless/read-only
  refresh. A single PostgreSQL 17 `REPEATABLE READ READ ONLY` snapshot observed
  145 notification jobs: 127 SENT, 4 PENDING and 14 SENDING, including 14
  stale; invalid state/kind/lifecycle/active-recipient counts were zero. The
  549963-byte custom dump was restored into a removed network-none,
  read-only-root/tmpfs PG17 container through tracked bootstrap/prepare,
  `pg_restore --role=obsidian_migrator --no-owner --no-privileges` and runtime
  ACL scripts. All 54 table and 13 catalog digests matched. Evidence:
  `docs/e0-3-bot-b5-3-064a-production-source-refresh.v4.json`, SHA-256
  `99531224f6eac8d13ce07b14fdf6408f333fca2a10426e7876613ce3da812a80`;
  candidate:
  `docs/e0-3-bot-b5-3-064a-decision-candidate.v4.json`, SHA-256
  `32d54d2bfaf555c7d795cc70b8b92561d7a6d9a19262eb1089eb3611aafd2316`.
  Archive/manifests/containers/tmpfs were removed; no identifiers, payloads,
  production rows, credentials, deploys or restarts were touched. Authority
  remains fully restrictive and E0.3 remains `BLOCKED_OWNER`; 064B/064D and
  all production action remain prohibited. Next: authenticated accountable
  owner plus applicable independent-reviewer decision over exact v4 digest.
  A follow-up read-only intake check at 2026-08-22T04:13:26Z found the v4
  source/candidate/deferral hashes unchanged; the source window remains open
  until 2026-08-23T03:25:06Z. Candidate effect is still
  `EVIDENCE_ACCEPTANCE_ONLY`, owner/reviewer approvals are false, and no new
  authenticated owner/reviewer decision or restrictive re-deferral was
  present. Runtime read-only inventory still shows only the existing relay
  rehearsal and healthy `obsidian-postgres` containers. Rehearsal artifacts
  remain non-authorizing.
  The owner reports access to only one device; this cannot satisfy the current
  separate-offline-device requirement for two-person authenticated approval by
  itself. Do not emulate a second reviewer with another account, profile or VM;
  use a genuinely independent reviewer with a separate device, or explicitly
  re-defer while retaining `BLOCKED_OWNER`.
  To keep progress moving without weakening that boundary, the offline signer
  was extended fail-closed for the current v3 restrictive-deferral schema and
  an exact v4 synthetic statement/reviewer/owner/verifier rehearsal passed in a
  disposable temp directory. Evidence:
  `docs/e0-3-bot-b5-3-064a-v4-synthetic-one-device-preflight.v1.json`.
  Synthetic keys/envelopes were destroyed; no human independence, authenticated
  acceptance or production authority is claimed. Signer and regression test
  changes are local preparation only; E0.3 remains `BLOCKED_OWNER`.
  A follow-up no-client 064B rehearsal was completed as a distinct disposable
  PostgreSQL 17 container using a digest-pinned image, network none,
  read-only root, tmpfs data and synthetic legacy rows only. A new rehearsal
  bundle adds only nullable v2 job columns, NOT VALID conditional constraints,
  token/evidence tables, ungranted versioned functions and CONCURRENTLY
  indexes; it does not backfill recipients, replace the legacy state check,
  create roles/grants, fence producers/dispatchers or touch production. The
  old insert and pending→sending→sent path passed, pre-v2 rollback restored
  the legacy schema, and rollback after a synthetic v2 claim failed closed.
  Two implementation defects found by the rehearsal (FK drop order and
  ambiguous RETURNS TABLE id qualification) were fixed and rerun. Evidence:
  `docs/e0-3-bot-b5-3-064b-expand-rehearsal.v1.json`; package:
  `deploy/postgres/rehearsal/`. The rehearsal is non-authorizing; E0.3 remains
  `BLOCKED_OWNER`, 064B production expand remains prohibited, and the next
  canonical item is still authenticated owner plus applicable independent
  reviewer decision over the exact v4 candidate. Since the existing v3 offline
  handoff is stale for this candidate, a separate v4 handoff was added for
  preparation:
  `docs/b64-064a-offline-signing-v4.md`, bound to the v4 candidate/source and
  v3 prior/deferral hashes. Its static regression test passed; it requires two
  genuinely independent offline devices and grants no production authority.
  Evidence: `docs/e0-3-bot-b5-3-064a-v4-handoff.v1.json`, SHA-256
  `621a1c8ce2c932d2e5bc0d91edced5fa9542a144de9d552300e9d64c42169dfa`.

- 2026-08-22 read-only v4 intake revalidation at 04:29Z confirmed all nine
  cross-file bindings: source/candidate/deferral/handoff digests match, the
  source is 3,863 seconds old against the 86,400-second limit, candidate state
  is `AWAITING_NEW_AUTHENTICATED_DECISION`, owner/reviewer approvals and every
  action authority remain false, and the synthetic one-device rehearsal is
  non-authorizing. Focused 064A protocol/refresh/deferral/handoff/signer tests
  passed 27/27; systemd-bus inspection was unavailable under the sandbox, so
  runtime claims remain limited to the read-only Docker inventory. E0.3 stays
  `BLOCKED_OWNER`; next is the real authenticated owner plus independent
  reviewer decision over exact v4 digest, or an explicit restrictive re-deferral.

- 2026-08-22 the owner explicitly reprioritized away from the owner-blocked
  E0.3/064A route and requested the next safe canonical roadmap slice. E0.3,
  064B and 064D remain deferred and unverified; no production authority,
  migration or row disposition was inferred. The active route is now
  E4/keyless `private-action-test-invocation-result.v1`: the workspace
  implementation revalidates preview → acknowledgement → draft → assessment
  → reservation → BUY/SELL handoff, permits only an explicitly test-only store,
  returns bounded metadata and keeps HTTP/production invocation false. Pure and
  SQLite E4 tests passed 69/69; optional PostgreSQL tests were not run because
  `TEST_POSTGRES_DSN` is unset. The follow-up capability-boundary review is
  `REVIEW_PASS_TEST_ONLY_CAPABILITY_BOUNDARY` in
  `docs/e4-private-action-invoker-security-review.v3.md`: production-capable
  handoff stores no longer expose a mutable `test_only` switch; the invoker
  requires an explicit test-only wrapper, while trusted principal/actor and
  applicable BUY web-user bindings remain enforced before handoff. No
  production route/provider/HTTP reference was found. The wrapper is isolation,
  not production authorization. A later explicit conversational approval
  allowed one read-only source snapshot acquisition and disposable PostgreSQL
  restore; evidence is `docs/e4-full-snapshot-rehearsal.v1.json` with
  `NO_GO_NON_AUTHORITATIVE`: restore completed, 54 tables and absent 025
  objects were observed, but live-source drift, intentionally different fixture
  ACLs, production contact during acquisition and no machine-readable
  single-use receipt prevent promotion evidence. Target, encrypted snapshot
  and ephemeral key were destroyed; no production DML, migration, restart or
  route wiring occurred. Do not apply 025 or promote the action route.
  A follow-up code slice implemented the non-executing
  `relay/core/e4_rehearsal_runner_boundary.py`: it accepts only an ELIGIBLE
  target-bound receipt/spec fingerprint, pins the image and networkless
  read-only/tmpfs target, rejects paths/DSNs/secret-like refs, and mandates
  teardown/absence checks. Seven focused tests pass. Evidence:
  `docs/e4-rehearsal-runner-boundary-review.v1.md`; the actual executor and
  all production action remain blocked by the formal receipt.

- 2026-08-22 read-only inspection confirmed `obsidian-postgres` is the
  production PostgreSQL service, not a rehearsal target: it has the persistent
  read-write `obsidian-postgres-data` volume, a bind-mounted PostgreSQL secret,
  application service dependencies and a loopback-published port. Under the
  owner's explicit one-off approval it was contacted only to create the
  encrypted snapshot used by the disposable diagnostic; no production DML,
  migration, restart or service mutation occurred. The production container
  remains forbidden as the E4 target.

- 2026-08-19 owner selected restrictive re-deferral for exact v3 candidate
  `771ce159032de810d8b09731be109af6a2bb317fc1b8b6e2f5a0d3fff9a08ddf`.
  Evidence: `docs/e0-3-bot-b5-3-064a-owner-deferral.v3.json`. Conversation
  context is explicitly not an authenticated signature or evidence acceptance.
  Only keyless/read-only/non-production/documentation-and-tests remain allowed;
  064B/064D, deploy, restart, delivery, retry and row disposition remain
  prohibited. E0.3 stays `BLOCKED_OWNER`; no further refresh loop is canonical.

- 2026-08-19 E0/E0.4 `RESTRICTIVE_STATUS_REPORT` is complete as a closed
  documentation artifact, not as remediation or gate acceptance. It raw-byte
  SHA-256-binds the gap register, remediation plan, empty intake, synthetic
  rehearsal and intake review; the eight confirmed gaps remain explicitly a
  lower bound. All authority, acceptance, waiver, verification and readiness
  flags are false. Two independent read-only reviews found and closed risks of
  hash drift, status conflation, vacuous authority checks, synthetic-PASS
  promotion, stale evidence and owner/reviewer conflation. Evidence:
  `docs/e0-4-restrictive-status-report.v1.json`. E0.3 remains first unmet and
  `BLOCKED_OWNER`; E0.4 and E0 remain `IN_PROGRESS`. The prior 064A source
  window is expired. Next canonical item: a new read-only source refresh and
  exact candidate as prerequisite to the authenticated accountable-owner plus
  applicable independent-reviewer decision; 064B/064D and production actions
  remain prohibited.

- 2026-08-18 E0/E0.4 `DEPLOYMENT_RELEASE_AUTOMATION` is classified and rejected
  for production acceptance. The enabled persistent 15-minute timer runs an
  untracked `/root/deploy.sh` as unrestricted root against mutable unsigned
  `master` and a 889-entry dirty checkout using plaintext credential storage.
  Critical correctness failure: it pulls/tests `/root`, but effective Relay,
  bot and monitor units execute `/opt/obsidian-exchange`; no artifact promotion
  exists, yet unchanged `/opt` processes may restart and `/root` HEAD may be
  recorded deployed. An is-active failure is swallowed by `|| echo FAILED`,
  after which state and Deploy complete are still written. Preflight, service
  coverage, provenance, approvals, atomicity, readiness, rollback/recovery,
  hardening and operator UX are unaccepted. Three independent reviews reject
  acceptance; eight focused checks pass, JSON/diff are clean. No git pull,
  credential value, script execution, deploy, restart, unit/timer or production
  mutation occurred. Evidence:
  `docs/e0-4-deployment-release-automation-runtime-observation.v1.json`. E0.4
  remains `IN_PROGRESS`; next: read-only classification of
  `EDITORIAL_NEWS_DELIVERY` across subscription identity, source provenance,
  idempotency, credentials, consent, retention and operator authority.

- 2026-08-18 E0/E0.4 `RATE_LOCKS` is classified across all six surfaces and
  rejected for production acceptance. Telegram is the sole implemented
  customer surface; production has three rows (one active, two expired unused,
  none consumed/bound), observed counts-only in a read-only transaction. The
  critical defect is truthful-fee failure: UI twice says 100 RUB is deducted,
  but fee_rub is only stored/read and crypto is calculated from the full RUB
  amount with no accounting attribution. Additional blockers are stale/static
  fallback becoming a guarantee without provenance, free replay/renewal,
  caller-supplied quote vectors not DB-bound to the persisted lock, a
  concurrent-first-insert active-lock race, silent regular-quote fallback
  without re-consent, and missing constraints/audit/retention/compensation.
  Positive controls are owner/currency/DB-expiry reads and atomic single-use
  consumption with fallback. Three independent reviews reject acceptance;
  eight focused checks pass, JSON/diff are clean. No customer identifiers,
  price call, lock/order writer, auth, secret, deploy or restart occurred.
  Evidence: `docs/e0-4-rate-locks-runtime-observation.v1.json`. E0.4 remains
  `IN_PROGRESS`; next: read-only six-surface classification of
  `DEPLOYMENT_RELEASE_AUTOMATION` and its source trust, credentials, checks,
  restart authority, audit, rollback and recovery.

- 2026-08-18 E0/E0.4 post-25 closure reconciliation disproved completeness of
  the current matrix. Read-only enumeration observed 346 inferred FastAPI route
  objects (Relay 98, KAIROS 42, LUMI 206), 29 generated Laravel routes and 13
  enabled Nginx location blocks. Five material families remain outside the 25:
  `RATE_LOCKS`, `DEPLOYMENT_RELEASE_AUTOMATION`, `EDITORIAL_NEWS_DELIVERY`,
  `TELEGRAM_CHANNEL_POST_PROCESSING` and `LEGACY_PAYMENT_EDGE_UPSTREAM`.
  Public trust/legal content and framework-generated docs/Livewire/storage
  surfaces require explicit mapping decisions. The enabled 15-minute root
  autodeploy is a production code/restart writer; two public pay domains point
  at an unowned/unmapped `127.0.0.1:8080`; legacy `/root` units coexist with
  `/opt` evidence. Three independent reviews reject closure. Eleven focused
  checks pass; JSON/diff are clean. No auth, secret, customer data, endpoint,
  provider, writer, deploy or restart was used. Evidence:
  `docs/e0-4-post-25-closure-reconciliation.v1.json`. E0.4 remains
  `IN_PROGRESS`; next safe item is six-surface read-only classification of
  `RATE_LOCKS`, including quote/fee/expiry/persistence/money authority.

- 2026-08-18 the owner explicitly re-deferred exact E0/E0.3 B5.3/064A
  candidate SHA-256
  `760ef8b1a6848ce782dea27c0e3da672ce79f264590b40b1fbd47b25c2dbc99e`
  and authorized continuation only as keyless/read-only/non-production/tests
  and documentation. Immutable evidence:
  `docs/e0-3-bot-b5-3-064a-owner-deferral.v2.json` (SHA-256
  `e5d76a90c4f750ef936eb125eda011678a91ae7c76e794cd9dae634a46973ffb`).
  It accepts no evidence and authorizes neither 064B nor 064D, deploy, restart,
  cutover, Telegram delivery, retry or production mutation; 13 SENDING rows
  (11 stale) remain untouched. Two independent semantic/landmine reviews agree
  and are not acceptance signatures. Twenty-seven focused checks pass. A test
  caught stale signer/runbook digests in the v1 freshness policy after the v2
  handoff adaptation; bindings were refreshed and package-integrity tests are
  green. E0.3 remains first-unmet `BLOCKED_OWNER`. Active safe route:
  `E0/E0.4/POST_25_CLOSURE_RECONCILIATION` over the full deployed/generated
  route, startup/import-writer, worker/service and UI/bot-consumer universe.

- 2026-08-18 E0/E0.3 B5.3/064A v2 candidate now has a fail-closed offline
  owner/reviewer handoff. `create-statement` accepts only the closed v2 schema,
  exact `ACCEPT_BOUNDED_EVIDENCE_ONLY` label, all restrictive authority flags
  and issuance inside the candidate-bound 24-hour source window. Ambiguous 064B
  scope, `actionAllowed:true` and stale source time are regression-tested and
  rejected. The runbook now pins candidate SHA-256
  `760ef8b1a6848ce782dea27c0e3da672ce79f264590b40b1fbd47b25c2dbc99e`
  and requires independent comparison of candidate/source evidence bytes.
  Fourteen protocol/signer/candidate tests pass; compile and diff checks pass.
  No key, registry, signature, enrollment, trusted time, revocation, replay
  ledger or production effect was created. Evidence:
  `docs/e0-3-bot-b5-3-064a-v2-offline-handoff.v1.json`. E0.3 remains
  `BLOCKED_OWNER`; next is the real accountable-owner plus applicable
  independent-reviewer authenticated accept-or-re-defer decision before the
  source window expires, otherwise another read-only refresh/new candidate.

- 2026-08-18 E0/E0.3 B5.3/064A source evidence was refreshed read-only and a
  new unambiguous evidence-only candidate was frozen. Production PG17 now has
  94 notification jobs: 81 SENT, 13 SENDING, including the same 11 stale rows;
  all state/kind/lifecycle/recipient-shape checks remain valid. One exported
  MVCC snapshot restored into a distinct network-none/read-only-root/tmpfs PG17
  container; all 54 table digests and all 13 bounded catalog-v2 sections match.
  The 522111-byte sensitive archive, manifests, container and tmpfs were
  removed. Evidence:
  `docs/e0-3-bot-b5-3-064a-production-source-refresh.v2.json`; candidate:
  `docs/e0-3-bot-b5-3-064a-decision-candidate.v2.json` (SHA-256
  `760ef8b1a6848ce782dea27c0e3da672ce79f264590b40b1fbd47b25c2dbc99e`).
  The v1 input and owner deferral hashes are unchanged. Four new plus ten
  freshness tests pass; JSON and diff checks are clean. E0.3 remains
  `BLOCKED_OWNER`: freshness cannot authorize anything, 064B is prohibited,
  and this exact new candidate requires a new authenticated accountable-owner
  accept-or-re-defer decision plus applicable independent-reviewer acceptance.
  Next canonical item: obtain those decisions before the 24-hour source window
  expires; otherwise refresh source evidence again. The 13 SENDING rows require
  separate 064D immutable disposition and were not mutated.

- 2026-08-18 E0/E0.4 KAIROS_EXCHANGE_DISCOVERY classification is complete but
  not accepted. Bearer-protected KAIROS operator routes locally register names
  and persist registry/draft files; this is an effect writer, not external
  discovery. The bounded routes accept no credentials and activate no connector
  or trade. Blockers: unverified static provenance, premature READ_ONLY status
  and dormant READY overclaim if re-enabled,
  non-transactional/corruption-unsafe JSON, lossy identity collisions, and no
  immutable review/revision/retention/recovery lifecycle. All 25 currently
  enumerated families now have six-surface classifications, but empty bounded
  omissions do not accept E0.4 or E0. No post-expansion closure rescan of the
  full deployed/generated route, startup/import-writer, worker/service and
  UI/bot-consumer universe was performed. No auth/network/provider/customer/secret/writer/
  deploy/restart action occurred. Evidence:
  `docs/e0-4-kairos-exchange-discovery-runtime-observation.v1.json`. E0.4 stays
  `IN_PROGRESS`; canonical work returns to first-unmet `E0.3` and its
  owner-blocked bot execute-only ACL route.

- 2026-08-18 E0/E0.4 AI_ASSISTANT classification is complete but not accepted.
  Mini App exposes a public single-turn FAQ assistant through Relay and loopback
  Ollama; the inspected path uses text rendering and has no tools, customer/order
  retrieval, persistence, signing or money action. Blockers: unauthenticated
  inference lacks AI-specific concurrency/admission; hard-coded financial facts
  contradict runtime policy; privacy copy, advisory/sensitive-data boundary,
  safe errors, streaming, grounding, model provenance/readiness and evaluations
  are unaccepted. KAIROS/LUMI control/advisory paths remain separate families.
  No auth/customer row, secret, model/network call, writer, deploy or restart
  occurred. Evidence: `docs/e0-4-ai-assistant-runtime-observation.v1.json`.
  E0.4 remains `IN_PROGRESS`; that slice has since completed and the canonical
  route is now first-unmet `E0.3`.

- 2026-08-18 E0/E0.4 OPERATIONS_MONITORING classification is complete but not
  accepted. Active standalone and embedded checks, public status and operator
  risk views were classified across six surfaces. Blockers: observer failures
  can produce false green; alerts lack durable incident/delivery/ack/escalation;
  no independent dead-man or general SLO/error budget; public readiness
  overstates one-provider health; backup restore continuity and telemetry
  retention are unproved; monitor runs as root with an overbroad environment.
  Effectful watchers remain owned by their original control families. No auth,
  customer row, secret, external probe, Telegram message, writer, deploy or
  restart occurred. Evidence:
  `docs/e0-4-operations-monitoring-runtime-observation.v1.json`. E0.4 remains
  `IN_PROGRESS`; that slice has since completed and current route is
  `KAIROS_EXCHANGE_DISCOVERY`.

- 2026-08-18 E0/E0.4 CUSTOMER_ENGAGEMENT classification is complete but not
  accepted. Telegram supplies campaigns, rate alerts, reviews, promos and
  loyalty/referral UX; durable one-shot jobs have dedupe and ambiguous-send
  quarantine. Blockers: marketing defaults on without purpose-specific consent
  or usable global opt-out; several audiences bypass suppression; direct
  campaigns have no recipient ledger; stuck `sending` has no recovery; personal
  win-back codes are transferable/logged; review publication consent, promo
  bounds, loyalty exactly-once accounting and retention/erasure are absent. No
  auth/customer row, secret, Telegram message, external call, writer, deploy or
  restart occurred. Evidence:
  `docs/e0-4-customer-engagement-runtime-observation.v1.json`. E0.4 remains
  `IN_PROGRESS`; that slice has since completed and current route is
  `KAIROS_EXCHANGE_DISCOVERY`.

- 2026-08-18 E0/E0.4 PUBLIC_MARKET_INFORMATION classification is complete but
  not accepted. Public site/API, Telegram and Mini App expose indicative RUB
  market data, while the same fallback-capable rate helpers feed transactional
  calculations and automated limit triggers. Blockers: static emergency prices
  can reach money decisions; source/as-of/fallback/confidence are erased and a
  current response timestamp can disguise stale data; no quorum/sanity circuit,
  immutable quote boundary or operator price-health surface; Mini App direct
  CoinGecko display diverges from backend calculator semantics. No market,
  provider, authenticated, customer, secret, writer, deploy or restart action
  occurred. Evidence:
  `docs/e0-4-public-market-information-runtime-observation.v1.json`. E0.4 remains
  `IN_PROGRESS`; that slice has since completed and the current route is
  `KAIROS_EXCHANGE_DISCOVERY`.

- 2026-08-18 E0/E0.4 WALLET_RECEIVE_TRANSFER classification is complete but
  not accepted. Mini App/Relay construct TON receive, free-transfer and
  order-bound sell-payment requests; the customer's external TON Connect wallet
  retains key, confirmation, signature and broadcast authority. Receive uses a
  stored verified public address and sell drafts are owner/order-bound.
  Blockers: failed pre-sign intent persistence returns a usable draft; no
  immutable request identity/idempotency/single-use lifecycle; free transfer
  has no durable receipt/reconciliation; send-signed is unbound and false-
  success prone; current signer account/content receipt, expiry, retention and
  non-TON/native parity are absent. Three independent reviews agree. No auth,
  customer row, wallet/RPC, secret, signature, broadcast, writer, deploy or
  restart occurred. Evidence:
  `docs/e0-4-wallet-receive-transfer-runtime-observation.v1.json`. E0.4 remains
  `IN_PROGRESS`; that next slice has since completed and the route is now
  `KAIROS_EXCHANGE_DISCOVERY`.

- 2026-08-18 E0/E0.4 PAYOUT_SETTLEMENT_RECONCILIATION classification is
  complete but not accepted. A canonical server-custodial branch persists an
  immutable intent before a dedicated signer and atomically reconciles
  succeeded intent, order sent/TXID, accounting and outbox. Critical blockers:
  Telegram/Relay/Laravel format-only TXID completion bypasses; mutable signer
  ledger/path absence can authorize unsafe requeue; submitted is treated as
  confirmed; reserve/circuit excludes in-flight obligations and can fail open;
  stale processing and dual-notifier ambiguity lack safe recovery. Installed
  and enabled units were observed, but active runtime was not provable from the
  sandbox. Three independent reviews agree. No secret/customer row, wallet,
  provider/RPC/authenticated call, writer, deploy or restart occurred. Evidence:
  `docs/e0-4-payout-settlement-reconciliation-runtime-observation.v1.json`.
  E0.4 remains `IN_PROGRESS`; the route has since advanced to read-only
  `KAIROS_EXCHANGE_DISCOVERY`.

- 2026-08-18 E0/E0.4 PAYMENT_PROVIDER_LIFECYCLE classification is complete but
  not accepted. Telegram, site and Mini App create live provider invoices and
  Relay owns transactional local `pending -> paid` truth. Critical blockers:
  provider submit and ambiguous retry precede durable immutable attempt;
  callbacks do not bind exact provider invoice/amount/currency; public numeric
  `/pay/{order_id}` can disclose the high-entropy payment-session bearer and
  payment facts; callback payload logging and reconciliation/manual authority
  are fragmented. Three independent reviews agree. No authenticated/provider
  call, customer row, secret value, writer, deploy or restart occurred.
  Evidence: `docs/e0-4-payment-provider-lifecycle-runtime-observation.v1.json`.
  E0.4 remains `IN_PROGRESS`; the route has since advanced to
  `WALLET_RECEIVE_TRANSFER`.

- 2026-08-18 E0/E0.4 ACCOUNT_AUTH_PROFILE classification is complete but not
  accepted. Deployed site auth, Telegram/Mini App identity, profile mutations,
  identity binding and separate Laravel admin auth are classified across six
  surfaces. Positive controls include bcrypt, Secure/HttpOnly/SameSite cookie,
  CSRF on profile writes, Telegram HMAC/freshness and Nginx throttles. Blockers:
  login-CSRF-prone state-changing Telegram-binding GET; no session revocation
  after password/TOTP changes; raw session/CSRF and plaintext customer TOTP DB
  material; replayable second-step token; no verified email, reset/recovery,
  unlink, revoke-all or canonical identity merge/unmerge. Three independent
  reviews agree; focused checks, JSON, compile and diff validation pass. No
  authenticated call/customer row/secret/writer/deploy occurred. Evidence:
  `docs/e0-4-account-auth-profile-runtime-observation.v1.json`. E0.4 remains
  `IN_PROGRESS`; the route has since advanced through payment lifecycle to
  `PAYOUT_SETTLEMENT_RECONCILIATION`.

- 2026-08-18 E0/E0.4 SWAPS classification is complete but not accepted.
  Telegram and authenticated site can create real SwapUZ orders; external
  submit occurs before any durable local intent/attempt, ambiguous outcomes
  lack reconciliation-before-retry, and the public bearer status GET exposes
  addresses while performing provider I/O and a local CAS transition. P0 review
  proved a `finished -> unknown -> finished` path can repeat the currently
  non-idempotent referral credit. A checkout-only fail-closed SwapUZ transition
  guard plus four regression checks passes compilation/diff validation, but it
  is not deployed, so production remains vulnerable. One independent review
  accidentally exposed a provider secret in private tool output; never record
  the value and rotate it through the provider console before accepted rollout.
  Evidence: `docs/e0-4-swaps-runtime-observation.v1.json`. E0.4 remains
  `IN_PROGRESS`; the canonical route has since advanced through
  `ACCOUNT_AUTH_PROFILE` to `PAYMENT_PROVIDER_LIFECYCLE`.

- 2026-08-18 E0/E0.4 KAIROS autonomous trade-control classification is
  complete but not accepted. The active `kairos-svc` loopback service has 38
  statically enumerated API routes; public health is 200 and unauthenticated
  operator status is fenced 401. Mounted trade routes always refuse with 409,
  and every worker/chat execution path reaches an unconditional `HOLD` before
  dormant legacy CCXT `create_order` code; the older direct-execution router is
  not mounted. No active money writer is reachable through the observed
  entrypoint. Blockers remain: one broad operator bearer can change live flags
  and start the worker, LUMI is non-gating advisory, and persisted immutable
  intents, idempotent claims, durable attempts and ambiguous-submit recovery
  are absent. Eleven focused/reconciliation tests pass. Evidence:
  `docs/e0-4-kairos-autonomous-trade-control-runtime-observation.v1.json`.
  E0.4 remains `IN_PROGRESS`; next is read-only `SWAPS` classification.

- 2026-08-18 E0/E0.4 LUMI control-plane classification is complete but not
  accepted. A no-import AST scan found 203 mounted deployed routes across 28
  routers (107 GET, 94 POST, 2 DELETE). The loopback `lumi-svc` process has a
  real host-file apply/rollback surface plus vault, provider, policy, action,
  project and persistence control. Live public status was protected but
  `configured:false`: restart loses its in-memory administrator password and
  the first loopback caller can claim public setup. One bearer has all routes;
  real-apply approval and test IDs are presence-only and do not bind a real
  approval/pass. This violates the advisory-only boundary although no money/
  ACL writer, provider call or plaintext-secret disclosure was observed. Two
  independent reviews reject acceptance. Evidence:
  `docs/e0-4-lumi-control-plane-runtime-observation.v1.json`. E0.4 remains
  `IN_PROGRESS`; next is read-only `KAIROS_AUTONOMOUS_TRADE_CONTROL`.

- 2026-08-18 E0/E0.4 comprehensive reconciliation corrected the bounded
  thirteen-family matrix: an empty omission list was not completeness evidence.
  Read-only inspection of five hash-bound deployed application entrypoints and
  two independent reviews recorded 12 material unclassified families. The
  highest-priority gap is `LUMI_CONTROL_PLANE`: deployed project/patch/sandbox,
  real-apply/rollback, vault/provider-runtime and policy/action routes are much
  broader than the accepted advisory boundary; code presence does not prove
  reachability or authority. KAIROS trade controls, swaps, auth/profile,
  provider payments, payout/reconciliation, wallet actions, public market
  information, engagement, operations, Relay AI and exchange discovery are
  also explicit omissions. The evidence honestly leaves exact generated route/
  handler/worker coverage, six-surface classification and production acceptance
  false; E0.4 and E0 remain `IN_PROGRESS`. JSON validation, diff check and 32
  focused tests pass. No secret/customer data/authenticated call/provider call,
  money writer, deploy, restart or runtime mutation was used. Evidence:
  `docs/e0-4-deployed-route-feature-reconciliation.v1.json`. Next: classify
  `LUMI_CONTROL_PLANE` across all six surfaces and verify its authority boundary
  read-only.

- 2026-08-18 E0/E0.4 bounded six-surface inventory now includes all 13
  explicitly listed families after adding LUMI advisory. LUMI, KAIROS and Relay
  are active as dedicated non-root services on loopback; LUMI health is 200 and
  unauthenticated resolver/committee access is fenced 401. The deployed
  KAIROS→LUMI generic shared-token bridge is source-equal to checkout, but it is
  not the frozen E2 wire: it lacks bounded canonical schema, replay/freshness,
  signed response receipt and durable content-bound audit, and errors preserve
  a possible committee `APPROVE` instead of forcing `HOLD`. More importantly,
  KAIROS records then ignores the advisory before its execution path. Thus LUMI
  currently has no money/ACL authority, but also provides no accepted veto gate;
  generic LUMI may misleadingly emit `actionAllowed:true`. Telegram/site/Mini
  App/native are justified `N/A/NOT_IMPLEMENTED`; operator admin and API are
  `OPERATOR_ONLY/PARTIAL`. Acceptance is `PARTIAL_NOT_ACCEPTED`. Two independent
  reviews were incorporated; 56 matrix/KAIROS/shadow tests plus three isolated
  LUMI service-auth tests pass. Deployed LUMI service-auth code matches checkout
  but is untracked, so provenance remains a blocker. No secret value, customer
  data, authenticated call, advisory/provider call, money writer or production
  mutation was used. Evidence:
  `docs/e0-4-lumi-advisory-runtime-observation.v1.json`. E0.4 remains
  `IN_PROGRESS`: the later deployed route/feature reconciliation supersedes its
  former next item and records the still-unclassified families.

- 2026-08-18 E0/E0.4 six-surface inventory now includes native signing.
  The checkout contains a real Rust/UniFFI Bitcoin Signet preview scaffold and
  synthetic Python E5 boundary/consent contracts, all explicitly fail-closed:
  they cannot create or hold keys, authenticate locally, sign, persist,
  broadcast, use a production network or authorize an action. No iOS/Android
  shell, deployed native artifact, device-keystore integration, durable replay
  ledger, recovery execution or signed release provenance exists; the native
  and E5 checkout artifacts are untracked. Telegram/admin are
  `N/A/NOT_IMPLEMENTED`; site/Mini App are `READ_ONLY/NOT_IMPLEMENTED`; API and
  native are `READ_ONLY/PARTIAL` and `REQUIRED/PARTIAL`. Acceptance is
  `PARTIAL_NOT_ACCEPTED`. The deployed TON Connect send flow is external-wallet
  signing, not native signing; both Relay send routes do exist, so two reviewer
  route-absence claims were explicitly rejected. Fifty Rust tests, 91
  synthetic E5 tests and 22 inventory tests pass. No key, signature, network,
  broadcast, mobile build, deploy or production mutation occurred. Evidence:
  `docs/e0-4-native-signing-runtime-observation.v1.json`. E0.4 remains
  `IN_PROGRESS`. The canonical route has since advanced to comprehensive E0.4
  deployed route/feature reconciliation.

- 2026-08-18 E0/E0.4 six-surface inventory now includes operator workflows.
  Read-only production observation proves active Laravel admin, Telegram bot,
  Relay and KAIROS units plus unauthenticated fences. Laravel is the strongest
  contour with named `is_admin`, TOTP replay protection, CSRF, read-only
  defaults and append-only audit triggers; deployed Telegram/Mini App, Relay
  admin routes and KAIROS operator APIs are also present. Telegram, Mini App,
  admin and API are `OPERATOR_ONLY/PARTIAL`; customer site and native are
  justified `N/A/NOT_IMPLEMENTED`. Acceptance is `PARTIAL_NOT_ACCEPTED`:
  admin/bot still run as root, roles are broad or shared, Telegram confirmation
  is same-chat pseudo-2FA, high-risk actions lack four-eyes, cross-service audit
  and support delivery are non-durable, moderation is last-write-wins, and
  KAIROS UI/credential claims contradict disabled effects. Two independent
  reviews supplied useful findings but their false claims that Relay admin
  routes were absent and all services ran as root were explicitly rejected
  using deployed route scans and runtime users. Seventeen Python tests and 14
  Laravel tests (76 assertions) pass; a legacy PostgreSQL script that exits
  during pytest collection is not claimed. No operator auth, customer data,
  secret value, writer, deploy, restart or configuration mutation occurred.
  Evidence: `docs/e0-4-operator-workflows-runtime-observation.v1.json`. E0.4
  remains `IN_PROGRESS`. The canonical route has since advanced to E0/E0.4
  LUMI advisory inventory.

- 2026-08-18 E0/E0.4 six-surface inventory now includes CEX portfolio.
  Read-only production observation proves active KAIROS/Relay/bot/admin units,
  green KAIROS health, scoped auth fences, deployed connector/list/events/
  disconnect/aggregate code and an enabled 300-second refresh scheduler. The
  production connector store is absent, so no credential, connector, real
  permission proof, balance or revoke lifecycle exists. Telegram and native
  are `REQUIRED/NOT_IMPLEMENTED`; site, Mini App and API are
  `REQUIRED/PARTIAL`; admin is `OPERATOR_ONLY/PARTIAL` because the separate
  KAIROS operator UI contradicts its disabled legacy endpoints. Acceptance is
  `PARTIAL_NOT_ACCEPTED`: customer connect is unavailable, transport is Bybit
  testnet-only, malformed KAIROS responses can appear empty/complete, stale
  timestamps and negative balances can appear fresh, cookie disconnect lacks
  explicit CSRF binding, and persistence/retention/backup plus surface parity
  are unaccepted. Thirty-two focused/integration checks pass after four stale
  next-item assertions were updated; two independent reviews accepted the
  bounded inventory while rejecting acceptance. No credential/customer row,
  external provider, authenticated customer route, writer, deploy, restart,
  config or DB mutation was used. Evidence:
  `docs/e0-4-cex-portfolio-runtime-observation.v1.json`. E0.4 remains
  `IN_PROGRESS`. The canonical route has since advanced to E0/E0.4 native
  signing inventory.

- 2026-08-18 E0/E0.4 six-surface inventory now includes external wallet
  linking. Read-only production observation proves active Relay/bot units, an
  enabled PostgreSQL wallet store, deployed proof/link/list/disconnect code,
  the exact four-column catalog and zero current links; no HTTP, auth, proof,
  explorer, customer identifier, address or writer was exercised. Telegram,
  site, Mini App and API are `REQUIRED/PARTIAL`; admin is
  `OPERATOR_ONLY/NOT_IMPLEMENTED`; native is `REQUIRED/NOT_IMPLEMENTED`.
  Acceptance is `PARTIAL_NOT_ACCEPTED`: challenges are replayable for 15
  minutes, Relay verify/disconnect can report false success, replacement is a
  blind upsert, revocation is an unaudited hard delete, datastore failures look
  like no link, throttling/data lifecycle controls are absent, and wallet proof
  reuses the cross-purpose `RELAY_SECRET` instead of a dedicated rotation
  domain. Seven focused tests plus TON Connect and wallet-store suites pass;
  two legacy fixture suites remain red and are not acceptance evidence. Two
  independent reviews accepted the bounded claims after the secret-domain
  finding was incorporated. No deploy/restart/config/DB mutation occurred.
  Evidence: `docs/e0-4-wallet-link-runtime-observation.v1.json`. E0.4 remains
  `IN_PROGRESS`. The canonical route has since advanced to E0/E0.4 operator
  workflows inventory.

- 2026-08-18 KAIROS operator UI is now externally reachable at the existing
  TLS origin under `/kairos/`, protected by a separate Basic Auth gate, API
  rate limiting and a root-only Nginx include that injects the existing KAIROS
  bearer credential upstream. Port 8000 remains loopback-only. Nginx rewrites
  the single-page client's absolute API paths under the prefix and suppresses
  the redundant local token prompt. External acceptance proved unauthenticated
  401, authenticated page 200 and authenticated operator API 200; `nginx -t`
  passes and the existing site remains the same virtual host. Rollback preimage
  is `/root/obsidian-exchange.org.pre-kairos-20260818`; no credential is stored
  in project memory. The canonical route has since advanced to E0/E0.4 CEX
  portfolio inventory.

- 2026-08-18 read-only P0/privacy inventory of the production KAIROS AI
  committee found one verified participant: Cerebras Cloud using
  `gpt-oss-120b`. It explicitly owns `risk` and `liquidity`; committee
  round-robin also assigns it the uncovered `critic` role, and it is the
  fallback final arbiter, so all four advisory calls leave the host for
  Cerebras. A configured local Ollama `qwen2.5:1.5b` entry is unverified and
  excluded, although Ollama is active locally with five installed models.
  LUMI is active locally on 8010 and remains an advisory resolver, not a
  committee LLM. Production AI credentials are vault references backed by a
  service-owned encrypted store; no plaintext was observed, but no provenance,
  accountable owner, issuance, billing-account, rotation or revocation evidence
  proves that the Cerebras key belongs to the project owner. No credential,
  config, service or network mutation occurred. The canonical route has since
  advanced to E0/E0.4 CEX portfolio inventory.

- 2026-08-18 E0/E0.4 six-surface inventory now includes gift vouchers under
  the frozen Telegram-only contract. Read-only production observation proves
  active bot/admin units, enabled PostgreSQL gift flag, deployed bot/store/admin
  artifacts, the exact 11-column catalog, five pending vouchers, five issue-
  attributed orders, zero redemption-attributed orders and no observed binding
  anomalies; no codes, customer identifiers, auth, Telegram delivery or money
  writers were exercised. Telegram is `REQUIRED/PARTIAL` because redeem calls
  an undefined `store` and the promised paid-card sender has no caller. Admin
  is `OPERATOR_ONLY/PARTIAL`; site and Mini App are `N/A/PARTIAL` because they
  advertise vouchers without a workflow/handoff; API/native are justified
  `N/A/NOT_IMPLEMENTED`. Acceptance is `PARTIAL_NOT_ACCEPTED`. Blockers include
  plaintext non-expiring ~30-bit bearer codes exposed in preview/admin/order
  metadata, an unthrottled state oracle, stale/hard-coded or zero rates, absent
  immutable intent/idempotency/quote/redemption ledger, ambiguous schema order
  binding and non-durable post-commit delivery. Thirteen focused checks and two
  independent reviews pass. No deploy/restart/config/DB mutation occurred.
  Evidence: `docs/e0-4-gift-runtime-observation.v1.json`. E0.4 remains
  `IN_PROGRESS`. Next: add wallet linking, the first remaining omitted family,
  to the exact six-surface inventory.

- 2026-08-18 E0/E0.4 six-surface inventory now includes limit orders under
  the frozen Telegram-only contract. Read-only production observation proves
  the bot and admin units are active, the PostgreSQL flag is enabled, deployed
  bot/store/admin artifacts and the exact 12-column catalog are present, and
  there are zero limit rows and zero limit-attributed orders; no auth,
  Telegram delivery or money writer was exercised. Telegram code presence is
  `IMPLEMENTED`, admin is `OPERATOR_ONLY/PARTIAL` because its sortable
  `created_at` is absent from production and it advertises unsupported ETH,
  and site/Mini App/API/native are justified `N/A`; acceptance remains
  `PARTIAL_NOT_ACCEPTED`. Blockers include missing immutable intent and
  idempotency, stale/hard-coded fallback prices, confirm-time auth/offering
  gaps, silent post-commit notification loss, unbounded scans/expiry, broken
  customer guidance and weak schema integrity. Eleven focused checks and two
  independent rereviews pass. No deploy/restart/config/DB mutation occurred.
  Evidence: `docs/e0-4-limit-order-runtime-observation.v1.json`. E0.4 remains
  `IN_PROGRESS`. Next: add gifts, the first remaining omitted family, to the
  exact six-surface inventory.

- 2026-08-18 E0/E0.4 six-surface inventory now includes DCA under the frozen
  Telegram-only contract. Production observation proves the bot unit is active,
  its PostgreSQL DCA flag is enabled, deployed DCA code is present, the table
  exists, and there are zero schedules and zero DCA-attributed orders; no auth,
  Telegram delivery or money writer was exercised. Telegram code presence is
  `IMPLEMENTED`, admin is `OPERATOR_ONLY/PARTIAL`, and site/Mini App/API/native
  are justified `N/A`; overall acceptance is `PARTIAL_NOT_ACCEPTED`. Recorded
  blockers include missing authenticated and bounded non-production lifecycle
  acceptance, absent generic intent/idempotency binding, zero-rate order risk,
  silent post-commit notification loss, unlimited recurrence, and admin drift
  (`runs_limit` plus unsupported statuses). Seven focused matrix/DCA checks and
  two independent reviews pass. Evidence:
  `docs/e0-4-dca-runtime-observation.v1.json`. E0.4 remains `IN_PROGRESS`.
  Next: add limit orders, the first remaining omitted family, to the exact
  six-surface inventory.

- 2026-08-18 E0/E0.4 now has production-specific, non-authorizing SQL release
  `e04sql_9b64809f...bfa30` (`f240570b...21e2b`) bound to an observed ABSENT
  eight-function production catalog preimage and the real `obsidian_migrator`
  owner/`obsidian_app` executor roles. It creates no roles or credentials and
  changes no legacy privileges. PostgreSQL 17 production-schema rehearsal
  proved expand -> rollback -> repeated rollback -> forward repair; re-expand
  and exact ACL drift fail before destructive action. Rollback fingerprints
  direct bodies, complete interfaces, security metadata and exact ACL tuples.
  Two initially rejecting independent reviews accepted after race, convergence,
  63-byte identifier, interface and ACL landmines were fixed. Two focused tests,
  compile and diff checks pass. No production SQL/deploy/restart/config occurred;
  E0.4 stays `IN_PROGRESS`. Evidence:
  `docs/e0-4-owner-auth-sql-release-rehearsal.v1.json`. Next: add the first
  omitted E0.4 family, DCA, to the exact six-surface matrix.

- 2026-08-18 E0/E0.4 exact code rollback preimages are now hash-bound to
  release `e04rel_0e07692e...aa4f`: six root:root 0644 deployed files plus the
  exact prior absence of `relay/core/order_access.py`. Component-wise nofollow
  reads, strict seven-path bindings and metadata checks fail closed on symlink,
  hardlink or drift. A copied-production-layout 8x8 matrix proved recovery for
  all 64 forward/rollback interruption combinations, including rerun
  convergence, SHA/mode/UID/GID and absence. Focused tests (3), compile and diff
  checks pass; two independent reviews accepted the bounded code-rollback
  claim. No production action occurred and E0.4 remains `IN_PROGRESS`.
  Evidence: `docs/e0-4-owner-auth-rollback-rehearsal.v1.json`. Next: create a
  narrow production-specific additive SQL migration plus exact catalog
  preimage and hash-bound rollback/forward-repair rehearsal with flags OFF.

- 2026-08-17 E0/E0.4 has deterministic release `e04rel_0e07692e...aa4f`
  (`8d71caba...38c93`, 1,013,760-byte uncompressed USTAR), explicitly
  non-deployable; verification requires externally pinned archive SHA-256 and
  release ID and rejects self-consistent rehashed-manifest substitution. The
  artifact is non-authorizing. The canonical manifest binds all seven
  candidate artifacts plus four SQL files isolated as rehearsal-only evidence,
  exact base/source/candidate hashes, sizes, target paths, default-off flags,
  exclusions, blockers and phased rollout/rollback order. Two independent
  builds are byte-identical; fixed archive metadata, sorted allowlist members,
  exclusive output and zero secret/env/DB/log/venv/cursor members are verified.
  Builders now accept explicit source/deployed roots, and a copied-root build
  is byte-identical. The strict verifier checks the pinned raw archive before
  parsing, then checks manifest/payload bindings, member allowlist/type/metadata
  and rejects traversal.
  Independent reviews
  require narrow production-specific additive migrations rather than executing
  proposals verbatim, code with flags OFF, Relay flag/canary before bot flag,
  and no direct-SQL revocation in this slice. Production action remains NO_GO;
  no deploy/restart/config/DB/Telegram action occurred. Evidence:
  `docs/e0-4-owner-auth-release-preflight.v1.json`. Next: bind exact rollback
  preimages for the seven deployed files and rehearse recovery after every
  partial replacement point in copied production-layout trees.

- 2026-08-17 E0/E0.4 prior PostgreSQL ACL incompatibility is resolved in the
  candidate behind two atomic default-off flags. Six Relay methods call only
  proposal-032 authorized read functions when enabled; two bot review methods
  call proposal-042 functions. Function/permission errors never trigger direct-
  SQL fallback. Review comment/finalize now also require review owner to match
  the canonical order owner across SQLite, Postgres fallback and proposal SQL.
  Two independent tmpfs PostgreSQL 17 containers proved the Relay 028+032 and
  bot 035+042 domains separately under execute-only roles: owner/token cases
  pass, cross-owner/inconsistent review cases fail, direct fallback gets
  `InsufficientPrivilege`, relation access stays denied, and bot replay is a
  no-op. Two initially rejected rehearsals exposed wrong package import and
  tuple-row handling; both were corrected before acceptance. Final independent
  rereview also found and fixed a review-finalization TOCTOU by repeating the
  current order-owner predicate in the terminal CAS across all three backends.
  The final two-container rehearsal passed again and containers were removed.
  No production/Telegram/deploy/restart occurred. Evidence:
  `docs/e0-4-owner-auth-pg-adapter-rehearsal.v1.json`. E0.4 stays `IN_PROGRESS`.
  Next: immutable release manifest plus coordinated Relay+bot rollout/rollback
  preflight; actual production action remains owner-authorized.

- 2026-08-17 E0/E0.4 owner/auth candidate passes a copied-production-layout
  hermetic Relay matrix for Telegram owner/foreign identity, conflicting token
  precedence, opaque tokens, internal key plus stored user id, numeric proof
  missing/wrong/expired cases, valid proof redirect, opaque payment rendering
  and SQLite review ownership. Socket calls and money writers were trapped; the
  temporary import DB hash stayed unchanged and no WAL remained. Independent
  review found and the checkout corrected two issues: signed Telegram identity
  now takes precedence over a conflicting bearer token, and unauthenticated
  `/pay` requests no longer write the page-open audit. Candidate Relay hash is
  now `cdd840fe...04f3`. A separate blocker was proven: selected Postgres store
  methods use direct table SQL but target roles from proposals 028/032 and
  035/042 are execute-only. Candidate remains NO_GO, E0.4 `IN_PROGRESS`; no
  production/DB/Telegram/deploy/restart occurred. Evidence:
  `docs/e0-4-owner-auth-candidate-runtime-matrix.v1.json`. Next: surgical
  feature-gated adapters to approved Relay read and bot review functions, then
  two isolated disposable PostgreSQL 17 execute-only-role rehearsals.

- 2026-08-17 E0/E0.4 now has a digest-bound surgical seven-artifact
  owner/auth candidate builder. An initial entrypoint-only build was rejected
  by independent security review because deployed stores lacked the required
  owner-bound methods. The corrected builder selects exact Relay/bot functions,
  a new pure `order_access` module and only required methods from four stores;
  it excludes notification writers, executor/dotenv changes and unrelated
  repository drift. Exact-input guards, exclusive output, deterministic hashes,
  compile, forbidden-symbol and mismatch-fail-closed checks pass. Independent
  review is conditional: runtime route/effect traps and production-equivalent
  PostgreSQL privileges are not yet tested. `/api/order` is not classified as
  read-only because existing provider polling can mark an order paid. The 2h
  proof reuses `RELAY_SECRET`, leaving URL/log/referrer and blast-radius risk.
  No production/DB/Telegram/deploy/restart occurred. Evidence:
  `docs/e0-4-owner-auth-candidate-build.v1.json`. E0.4 remains `IN_PROGRESS`.
  Next: production-layout hermetic matrix for cross-owner/proof/token/internal-
  key/review ownership plus network/writer traps and PostgreSQL ACL compatibility.

- 2026-08-17 E0/E0.4 checkout/deployed drift is now reconciled as read-only
  evidence, not deployed. Effective drop-ins select `/opt/obsidian-exchange`
  Relay and bot entrypoints. Current Relay drift is +79/-45 and mixes
  owner-bound read/payment hardening with default-off test isolation and a
  connection-budget change; bot drift is +183/-11 and mixes owner/payment
  fixes with a deferred notification money-writer proposal. Three independent
  reviews reject whole-tree/whole-file synchronization as an E0.4 shortcut.
  `docs/e0-4-artifact-drift-reconciliation.v1.json` binds exact hashes and keeps
  deploy/restart false. A separate P0 finding identified a plaintext historical
  payout secret in a backup-like systemd drop-in; its value is not recorded,
  active overrides clear it, but it must be treated as compromised. Rotation,
  revocation and exact-target removal are `BLOCKED_OWNER`. E0.4 remains
  `IN_PROGRESS`. Next: build and hermetically verify an immutable minimal
  Relay+bot owner/auth-hardening candidate excluding notification writers;
  production rollout remains separately owner-authorized.

- 2026-08-17 E0/E0.4 now has an isolated authenticated synthetic route-wiring
  rehearsal for site and Mini App owner-scoped reads. A pytest-discoverable
  wrapper always launches a fresh subprocess with a temporary SQLite auth DB,
  empty `DATABASE_URL`, synthetic Telegram HMAC key, disabled background tasks,
  no lifespan and pre-import socket/effectful-dependency traps. The first
  rehearsal was rejected because `main.py` manually overwrote the synthetic
  token from production `.env`; no value was exposed or external call made.
  Checkout `main.py` now has a default-off `OBSIDIAN_SKIP_DOTENV` test control,
  and the corrected child asserts after import that its token is synthetic, DB
  path is temporary, `DATABASE_URL` is empty and dotenv loading was skipped.
  Independent rereview accepted the corrected harness with the claim narrowed
  to the exercised route/auth wiring; the production default remains unchanged.
  Two web sessions see only
  their own dashboard order/support/referral sentinels and receive 404 for the
  other support ticket. Two independently signed Telegram initData subjects see
  only their own history/referral/pending-sell sentinels even when `user_id`
  query parameters conflict; missing/bad signatures return 403. All requests
  are GET and the temporary DB hash is unchanged. This proves auth subject →
  route/read-argument wiring only; read stores/templates are fakes and SQL owner
  isolation remains separate E0.3 evidence. Production credentials/network/DB,
  Telegram and money writers were not used. E0.4 remains `IN_PROGRESS` because
  deployed Relay and bot hashes differ from checkout and omitted feature
  families remain. Next: reconcile checkout/deployed Relay and Telegram bot
  artifact drift before authenticated evidence can describe production.

- 2026-08-17 active canonical route is E0/E0.4 feature/status inventory while
  E0.3/064A remains `BLOCKED_OWNER`. Read-only unauthenticated local-production
  evidence now covers the five-family matrix: `/webapp` is 200; customer site
  routes redirect to login; owner-scoped history/referral/pending APIs reject
  missing auth with 403; public sell options is 200; GET against POST-only buy/
  sell creation is 405; admin resources redirect to admin login; relevant units
  are active. Served Mini App HTML contains exchange/history/referral but no
  support surface. This proves only static UI, route, auth-fence and service
  presence—not authenticated E2E acceptance. Independent review found and local
  hashes confirmed that deployed Relay and bot sources differ from checkout;
  only Mini App HTML matches, so repository anchors are not production evidence.
  The finding is incorporated in
  `docs/e0-4-route-runtime-observations.v1.json`. No auth, POST, Telegram, DB,
  deploy or restart occurred. E0.4 remains `IN_PROGRESS`. Next: bounded
  authenticated synthetic acceptance observations for existing site and Mini
  App owner-scoped read paths, without exercising money writers.

- 2026-08-17 the owner explicitly deferred 064A authenticated acceptance and
  064B production expand and requested safe forward work. The restrictive
  decision is recorded in
  `docs/e0-3-bot-b5-3-064a-owner-deferral.v1.json`: E0/E0.3 remain
  `IN_PROGRESS`, 064A remains `BLOCKED_OWNER`, 064B is not authorized, every
  production/deploy/restart/cutover/Telegram/ambiguous-row permission is false,
  and the 11 SENDING rows are untouched. Independent review accepted those
  semantics. Safe keyless work moved to E0/E0.4 without bypassing E0.3. The
  first bounded surface-inventory slice covers RUB buy, crypto sell and customer
  order history across bot/site/Mini App/admin/API/native with a reason and
  repository anchor for every cell; omitted families are explicit and E0.4 is
  still `IN_PROGRESS`. Two structural/deferral checks and JSON/diff validation
  pass. Next: add support/referral cells with exact evidence, then obtain
  route-level runtime observations before treating implemented cells as
  acceptance evidence.

- 2026-08-17 E0/E0.3 B5.3/064A blocker was revalidated after the P0 work and
  remains `BLOCKED_OWNER`. The exact decision-input digest is still
  `f8abf0cb858232df2497221c44a319975403ccb7a8e2d2403bd57bda8c904bbb`;
  all seven bound artifact digests match, and nine focused protocol/offline
  signing checks pass. An independent read-only review confirms that chat
  `continue` is preparation authority only and cannot authorize 064B, deploy,
  restart, migration, database/runtime mutation or disposition of the 11
  ambiguous SENDING rows. No further technical preparation is necessary for
  the current human gate. The next and only canonical action is for a genuinely
  independent reviewer and the accountable owner, on separate offline devices,
  to sign, reject or defer this exact current package using
  `docs/b64-064a-offline-signing.md`; production registry, trusted time/
  revocation and durable replay acceptance remain absent.

- 2026-08-17 P0 follow-up removed the entire public Mini App transaction
  metric strip (`обменов сегодня`, `объём 24ч`, `сделок всего`) and its polling
  code. No synthetic values or database rows were introduced; real reporting
  remains available to internal/admin paths. The change was applied surgically
  to the exact production HTML, `/webapp` was verified to contain none of the
  removed IDs/labels, relay reports `operational` with five healthy providers,
  and relay/nginx remain active. Canonical work returns to E0/E0.3 B5.3 064A
  `BLOCKED_OWNER`; next item is authenticated owner/reviewer decision evidence.

- 2026-08-17 P0 availability interruption is mitigated and production relay is
  healthy. `/dashboard` and `/dashboard/orders` failed because PostgreSQL could
  not infer an untyped nullable parameter in `web_customer_orders`; the query
  now relies on normal NULL equality semantics. `/api/reserves` failed on
  `Decimal * float`; both operands are normalized before the public RUB-value
  calculation. A second bounded hotfix stops a failed Brabus provider-cancel
  drain after one retryable attempt instead of immediately reclaiming the same
  row up to 200 times and delaying HTTP startup. Production received surgical
  patches over exact deployed files (the dirty `/root` tree was not copied),
  `relay-fastapi` restarted cleanly, `/api/reserves` and `/api/system-status`
  return 200, dashboard unauthenticated flow returns 302, deployed NULL-user SQL
  returns an empty list, all ten critical units are active, and synthetic test
  IDs were removed. Hidden fabricated Mini App transaction/turnover metrics were
  not implemented; only real aggregates or an unmistakably labelled,
  default-off demo mode are acceptable. Active canonical route returns to
  E0/E0.3 B5.3 proposal 064A `BLOCKED_OWNER`; next item remains authenticated
  owner/reviewer decision evidence over the current 064A input.

- 2026-08-17 E0/E0.3 B5.3/064A now has a rehearsed offline candidate-signing
  handoff, while the real acceptance prerequisite remains `BLOCKED_OWNER`.
  `scripts/b64_064a_offline_signer.py` generates encrypted PKCS#8 Ed25519
  candidate keys, combines distinct reviewer/owner public entries, builds a
  short-lived exact statement, signs reviewer then owner-countersigned envelopes
  and performs stateless local verification. Private files require absolute
  paths under owner-only directories, `0600`, regular/single-link/owner checks
  after `O_NOFOLLOW` open; outputs are exclusive/no-overwrite and fsynced.
  Passphrases never use argv/env, and receipts omit keys/signatures. A full
  synthetic two-device logical flow plus tamper, existing-output, permissive-key
  and symlink cases passes; nine focused tests total pass. Runbook:
  `docs/b64-064a-offline-signing.md`; evidence:
  `docs/e0-3-bot-b5-3-064a-offline-signing-rehearsal.v1.json`. No real keys were
  created. Owner and reviewer must generate them on separate offline devices and
  return only public entries/envelopes. Candidate verification remains
  non-authoritative until authenticated registry enrollment, trusted time/
  revocation and durable replay consumption exist; all production/cutover flags
  remain false.

- 2026-08-17 E0/E0.3 B5.3 proposal 064A technical evidence is rehearsed for
  the declared bounded projection, but its acceptance prerequisite is now
  explicitly `BLOCKED_OWNER`; E0.3 remains `IN_PROGRESS`. A pure two-person
  Ed25519 protocol binds one exact decision-input digest, route/scope/expiry/
  nonce, independent reviewer envelope and accountable-owner countersignature.
  Roles and trust environment come from a pinned registry; owner/reviewer key,
  identity and trust domain must all differ; an injected atomic pair-consumer
  rejects replay. Every output keeps production mutation, expand, cutover,
  Telegram, ambiguous-row disposition and action authority false. Six tests
  pass for synthetic valid, symbolic authenticated-registry, digest/route/scope/
  signature tamper, revoked key, expiry, replay and missing signer cases. This
  proves protocol mechanics only: no production registry, real signatures,
  trusted time or replay ledger exists. Chat `continue` is preparation authority,
  not authenticated acceptance or migration GO. Evidence:
  `docs/e0-3-bot-b5-3-064a-authenticated-decision-rehearsal.v1.json`; unsigned
  exact input: `docs/e0-3-bot-b5-3-064a-decision-input.v1.json`. Next canonical
  item requires real accountable-owner and independent-reviewer signatures over
  that current input (or explicit reject/defer). No later migration phase is
  authorized; 11 ambiguous SENDING remain a separate 064D blocker.

- 2026-08-17 E0/E0.3 B5.3 proposal 064A remains `IN_PROGRESS`, but the
  snapshot-bound bounded catalog restore slice is now rehearsed. One PostgreSQL
  17 `REPEATABLE READ READ ONLY` transaction exported the snapshot, computed
  both 54-table and 13-section catalog v2 fingerprints, and remained open while
  `pg_dump --snapshot` imported that exact snapshot. The custom archive restored
  single-transaction into a distinct pinned PG17 cluster with `network=none`,
  read-only root, tmpfs data, no mounts or ports. All 54 table row multisets and
  all 11 declared database-local catalog sections matched after deterministic
  role/ownership/ACL reapplication; the two selected cluster-global sections
  (`membership`, `db_role_setting`) also matched but are explicitly classified
  as separately reconstructed, not archive-restored. A disposable column ACL
  drift produced exact `column_acl` MISMATCH/exit 1. Eleven focused tests pass.
  Sequence runtime state remains excluded as non-MVCC; this is bounded catalog
  equality, not physical/PITR/full-cluster equality or owner approval. All
  production-sensitive temporary files and the container/tmpfs were deleted and
  absence verified. Evidence:
  `docs/e0-3-bot-b5-3-catalog-source-restore-rehearsal.v1.json`. Next canonical
  item is authenticated owner/reviewer decision evidence for 064A; no cutover is
  authorized. The 11 ambiguous legacy SENDING rows remain a separate 064D
  blocker.

- 2026-08-17 E0/E0.3 B5.3 proposal 064A catalog-security drift work remains
  `IN_PROGRESS` and has advanced to `CANONICAL_BOUNDED_DRIFT_REHEARSED`.
  Fingerprint v2 uses fixed `pg_catalog` search path, stable names rather than
  serialized OIDs, canonical JSON objects and ordered JSON-array hashing across
  13 fixed sections. It covers ACL provenance, cluster memberships/settings,
  RLS/policies, internal triggers, function security, constraints including
  domains, indexes, type ACL/enums, sequence definitions plus OWNED BY, and
  extension owner/version. A clean disposable PG17 rehearsal proved three-run
  determinism, exact changed-section isolation for 17 mutations, hostile
  search-path equivalence, equivalent fingerprint after function OID churn and
  explicit non-drift after `setval`; four static tests pass. Production was
  untouched. Sequence runtime state remains excluded as non-MVCC, and wider
  catalog classes plus some hostile ACL/name cases remain outside the bounded
  claim. Evidence:
  `docs/e0-3-bot-b5-3-catalog-security-drift-rehearsal.v1.json`. Next canonical
  slice is v2 source-to-disposable-restore comparison with cluster-global state
  reported separately. The 11 ambiguous legacy SENDING rows and authenticated
  owner/reviewer GO remain independent blockers.

- 2026-08-17 E0/E0.3 B5.3 proposal 064A backup/restore evidence advanced but
  remains `IN_PROGRESS`. A PostgreSQL 17 custom archive imported the exact
  exported REPEATABLE READ READ ONLY snapshot used for source fingerprints and
  restored single-transaction into a distinct `network=none`, read-only-root,
  tmpfs-only PG17 container. All 54 public table row multisets matched by count
  and SHA-256 (`differentTables=[]`); normalized schema SHA-256 matched; 835
  selected effective ACL entries and four baseline role envelopes matched after
  canonical ACL reapplication. An initial live-source mismatch correctly exposed
  the need for exported-snapshot binding; a later verifier mismatch exposed and
  fixed inconsistent newline encoding. Six focused tests, compile and diff pass.
  Independent reviews accept only this bounded claim: sequence state,
  column/default ACL, memberships, DB role settings, RLS/policies, triggers,
  function security attributes and future B5 roles are not yet covered. All four
  temporary production archives, manifests, source-container copy, disposable
  container and tmpfs were deleted and absence verified. Production business
  data/catalog were read only. Evidence:
  `docs/e0-3-bot-b5-3-snapshot-restore-equality-rehearsal.v1.json`. Cutover stays
  blocked by full catalog-security fingerprint, authenticated owner review and
  the 11 ambiguous legacy SENDING rows. Next canonical slice: expand the
  catalog-security fingerprint to the missing ACL/security/catalog classes and
  rehearse drift detection. E0.3 remains `IN_PROGRESS`.

- 2026-08-17 E0/E0.3 B5.3 proposal 064A production dirty-data scan is
  `IN_PROGRESS` and cutover is blocked. A repeatable-read/read-only,
  secret-free checker attested the expected production database, PostgreSQL 17
  and critical legacy column types/nullability, then observed 80 jobs: 69 SENT,
  zero PENDING and 11 SENDING, all 11 older than 24 hours. No invalid state,
  kind, lifecycle or active-recipient shape was found; the one historical
  Montera admin job is SENT and remains v1 history. The 11 ambiguous SENDING
  jobs cannot be retried or relabelled without immutable operator evidence.
  Independent reviews rejected an initial false-GO/raw sending-to-sent test; it
  was removed. The corrected phased contract fences producers before draining
  pending, fences the dispatcher only afterward, preserves historical v1 rows,
  and forbids downgrade after first v2 submit. Three focused tests, a
  synthetic-shaped PG17 BLOCKED rehearsal, compile/JSON/diff checks pass;
  production was not mutated. Evidence:
  `docs/e0-3-bot-b5-3-production-dirty-data-scan-rehearsal.v1.json`. Remaining
  064A gates are catalog/ACL hash, backup/restore equality and authenticated
  owner/reviewer evidence; 064D later owns ambiguous operator disposition.
  Next canonical slice: catalog/ACL object hash plus custom backup and clean
  PostgreSQL 17 restore equality rehearsal. E0.3 remains `IN_PROGRESS`.

- 2026-08-17 E0/E0.3 B5.3 proposal 063 is complete only as
  `REHEARSED_PROPOSAL_ONLY`. Persisted submit authorization now classifies stale
  attempts as pre-submit abandoned versus authorized/no-terminal-evidence; both
  conservatively transition once to MANUAL with exact append-only review and no
  automatic retry. `UNCERTAIN` evidence cannot carry provider identifiers. A
  separate DB-only one-shot reconciler contract attests its exact principal,
  uses bounded statement/lock timeouts, emits fixed privacy-safe counters and is
  paired with hardened proposal-only systemd service/timer units. Clean
  PostgreSQL 17 proved eight-worker convergence, accepted-evidence recovery
  without Telegram, replay zero, and full rollback/recovery after injected
  failure between review insert and state transition. Nineteen focused tests,
  compile, systemd verify and diff checks pass; production was untouched.
  Evidence: `docs/e0-3-bot-b5-3-stale-review-reconciler-rehearsal.v1.json`.
  Canary remains rejected pending production-safe expand/backfill migration,
  OS/service credential provisioning and rotation, operator resolution,
  alerting, backup/restore and rollback evidence. Next canonical slice: proposal
  064 production expand/fence/drain/backfill/validate/cutover/contract migration
  package and rehearsal. E0.3 remains `IN_PROGRESS`.

- 2026-08-17 E0/E0.3 B5.3 proposal 062 is complete as
  `REHEARSED_PROPOSAL_ONLY`. Delivery evidence now stores a separate exact
  `client_correlation_id` FK to submit authorization while Telegram
  `provider_request_id` remains NULL; legacy recorder and mark-sent EXECUTE are
  revoked. One exact audited consume primitive is shared by delivery and a
  distinct reconciler principal. In clean PostgreSQL 17, eight concurrent
  reconciler calls produced one SENT transition and append-only audit, replay
  produced zero, and Telegram was never called. Runtime no longer writes
  UNCERTAIN after ACCEPTED persistence. Each new background/delivery/transport
  connection attests exact principal/non-elevated attributes, zero memberships,
  lane function allowlist/cross-lane denial, SECURITY DEFINER owner/search_path,
  PUBLIC denial and absence of direct relation/sequence grants. Twenty-two
  focused tests plus the legacy dispatcher contract pass; compile/JSON/diff are
  clean, production was untouched and the container removed. Evidence:
  `docs/e0-3-bot-b5-3-truthful-evidence-reconciliation-rehearsal.v1.json`.
  Canary remains rejected because 062 is clean-schema only, the reconciler is
  not a separately supervised production service, process credential rotation/
  isolation is unproven, terminal-evidence-absent stale attempts need an
  operator workflow, and production migration/observability/restore/rollback
  evidence is absent. Next canonical slice: proposal 063 ambiguity-safe stale
  attempt review + supervised reconciler process contract and fault/metrics
  rehearsal, then the production migration package. E0.3 remains `IN_PROGRESS`.

- 2026-08-17 E0/E0.3 B5.3 hardened runtime wiring is complete only as a
  default-off `REHEARSED_PROPOSAL_ONLY` slice. Proposal 061 adds an immutable
  token/recipient/client-correlation submit authorization, recipient-first lock
  ordering, revoke-aware replay denial, a truthful local render-failure MANUAL
  transition and recipient-scoped Telegram message uniqueness. The new runtime
  store requires separate background/delivery/transport DSN paths and rejects
  legacy-flag mixing; the dispatcher addresses only the claimed `recipient_id`,
  sends one Montera job per admin, persists evidence and never blindly retries
  an exception after Telegram invocation. A real adapter composition over
  proposals 058–061 passes in clean PostgreSQL 17, including ALLOW→revoke→
  replay DENY and late UNCERTAIN→MANUAL. Twenty focused tests plus the legacy
  dispatcher contract pass; compile/JSON/diff checks are clean and the container
  was removed. Evidence is
  `docs/e0-3-bot-b5-3-hardened-runtime-rehearsal.v1.json`. Canary is rejected:
  exact `session_user` startup attestation, truthful separation of client
  correlation from provider request ID, process-level credential isolation,
  ACCEPTED-but-unconsumed reconciliation, full race/fault/log/ACL matrices and
  the production expand/fence/drain/backfill/cutover migration remain. Next:
  proposal 062 runtime identity preflight + correlation schema correction +
  accepted-evidence reconciler/fault rehearsal. E0.3 remains `IN_PROGRESS`.

- 2026-08-17 E0/E0.3 B5.3 proposal 060 is rehearsed on clean disposable
  PostgreSQL 17 as authenticated policy governance plus emergency recipient
  control. Approval, activation and revoke/restore actors come from distinct
  database `session_user` principals; approval/activation/revocation history is
  append-only, activation uses expected-head CAS and monotonic versions, and
  shared/runtime logins have no direct governance DML. Recipient revoke
  atomically quarantines pending jobs without inventing delivery evidence and
  fences already-sending jobs as possible in-flight while preserving the 058
  evidence path; a late UNCERTAIN receipt was reconciled to MANUAL. Restore does
  not revive a pending-origin quarantine or clear an in-flight fence.
  Claim and enqueue fail closed for revoked recipients. The real PostgreSQL
  rehearsal and 17 focused/static tests pass; JSON/diff checks are clean,
  production was untouched. Evidence is
  `docs/e0-3-bot-b5-3-policy-governance-revocation-rehearsal.v1.json`.
  Canary remains rejected: 060 is a clean-schema proposal, an in-flight provider
  request cannot be recalled, and runtime still uses the old ID-only dispatcher.
  Next: joint default-off adapter/dispatcher rehearsal using recipient-bound
  claim, token, transport evidence, sent/pre-submit/manual transitions and a
  pre-submit revocation recheck; then production expand/fence/drain/backfill/
  validate/cutover/contract migration. E0.3 remains `IN_PROGRESS`.

- 2026-08-17 E0/E0.3 B5.3 proposal 059 is rehearsed in clean disposable
  PostgreSQL 17 as server-time, policy-bound, per-recipient producers. All five
  producers accept only limit, snapshot one DB time and an immutable policy,
  create one Montera job per concrete recipient, and run under a distinct
  execute-only background principal. PostgreSQL recomputes the canonical policy
  digest; composite FKs bind jobs/current pointer to exact policy id+version.
  Eight-way runs converge once for every producer, and injected failure on the
  second admin rolls back the marker and all sibling jobs. Fourteen focused tests
  pass; production was untouched and the container removed. Independent review
  accepts producer mechanics but rejects canary: approval/activation provenance
  is still fixture-only, the active pointer lacks monotonic append-only audit,
  emergency recipient revoke is absent, and runtime still uses proposal-048
  APIs/live ADMIN_IDS. Evidence is
  `docs/e0-3-bot-b5-3-server-policy-producers-rehearsal.v1.json`. Next: proposal
  060 policy governance + recipient revoke, then joint adapter/dispatcher
  token/evidence rehearsal. E0.3 remains `IN_PROGRESS`.

- 2026-08-17 E0/E0.3 B5.3 hardened delivery lifecycle proposal 058 is rehearsed
  in clean disposable PostgreSQL 17, but remains `IN_PROGRESS` and explicitly
  no-rollout. It adds PostgreSQL UUID attempt tokens, immutable attempts,
  single-assignment provider-scoped terminal evidence, exact token/evidence-bound
  sent/retry-pre-submit/manual transitions, max-attempt MANUAL and disjoint
  execute-only delivery/transport principals. Eight-way claims, ABA/stale-token,
  conflicting ACCEPTED-vs-NOT_STARTED evidence denial, replay, global provider
  receipt uniqueness and injected rollback pass; 15 focused/static tests pass.
  Independent review found and caused correction of the critical conflicting-
  evidence resend race. Production is untouched and the container was removed.
  Proposal 058 is intentionally not wired because proposal-048 producers cannot
  populate its immutable recipient snapshot. Evidence is
  `docs/e0-3-bot-b5-3-hardened-delivery-rehearsal.v1.json`. Next: proposal 059
  server-time/versioned-policy/per-recipient producers and distinct background
  principal, then a joint adapter/dispatcher rehearsal. E0.3 remains `IN_PROGRESS`.

- 2026-08-16 E0/E0.3 B5.3 adapter wiring is complete as a default-off rehearsal,
  not rollout-ready. `PostgresB5BotNotificationStore` maps all five due producers
  plus claim/sent/retry to the eight proposal-048 functions behind
  `BOT_NOTIFICATION_B5_ACL_ADAPTER_ENABLED`; noncanonical direct enqueue helpers
  fail closed in ACL mode and legacy remains the default. Focused adapter,
  dispatcher and inventory tests pass. A clean PostgreSQL 17 run through the
  real execute-only adapter passed all producers, eight-way unique claims,
  sent/retry CAS, invalid-parameter denial and zero direct table/sequence access;
  the container was removed and production untouched. Independent security
  review rejected canary until ID-only attempts become token/evidence-bound,
  ambiguity gains MANUAL/REVIEW, producer time/promo policy stop trusting the
  caller, partial fan-out gains evidence, and a distinct background principal
  plus narrow migration are rehearsed. Evidence is
  `docs/e0-3-bot-b5-3-adapter-rehearsal.v1.json`; E0.3 remains `IN_PROGRESS`.

- 2026-08-16 E0/E0.3 B5 adapter wiring has begun with the first default-off
  runtime slice: PostgreSQL `user_profile_store.upsert_user` and
  `claim_referrer` call the bounded proposal-047 functions only when
  `BOT_B5_ACL_ADAPTER_ENABLED` is explicitly true; legacy behavior remains the
  default and production was untouched. Fourteen focused tests pass. A clean
  disposable PostgreSQL 17 adapter rehearsal under the execute-only bot login
  passed eight-way claim concurrency, exact retry/self-referral denial and
  verified zero direct INSERT privilege; the container was removed. Independent
  security review confirmed proposals 035/047–057 must not be deployed verbatim:
  production needs narrow idempotent migrations without the synthetic password
  or blanket revokes, plus schema/data/default-privilege preflight. Operator
  mutations remain deferred until authenticated actor provenance is audit-bound.
  Evidence is `docs/e0-3-bot-b5-user-profile-adapter-rehearsal.v1.json`; next is
  a safe default-off background adapter package, then production migration and
  canary authorization. E0.3 remains `IN_PROGRESS`.

- 2026-08-16 E0/E0.3 bot ACL B route B5.2–B5.11 is now
  `B5_REHEARSED_PROPOSAL_ONLY`; the requested continuous B5.3–B5.11 scope is
  complete. Proposals 047–057 cover the exact 39-method remainder once each.
  Final B5.11 adds immutable order terms, source-bound order/gift/swap/sell
  credits, exact referral reservations/debits, principal-owned chain/swap/sell/
  hold evidence, canonical destination digests, exact replay validation and
  atomic outboxes/projections. A clean PostgreSQL 17 run passed eight-way
  concurrency, corruption/mismatch denial, catalog privilege checks and injected
  rollback for order/referral/swap/sell. Independent final review returned
  ACCEPT; exact-set/hash/diff/JSON/plan checks pass. Production remains untouched.
  Next canonical prerequisite is separately authorized adapter wiring and
  rollout rehearsal; current repository methods still execute legacy raw SQL,
  and the shared bot login still collapses caller provenance.

- 2026-08-16 continuous E0/E0.3 B completion advanced through B5.10. B5.8
  derives order payout debt only from a locked authoritative paid order and
  serializes referral balance snapshots; concurrent retries converge to one
  intent. B5.9 replaces unsafe sell lifecycle semantics with pending-only claim,
  terminal non-revival, unique deposit identity and token/evidence-bound
  NOT_STARTED release. B5.10 replaces caller free-text chain claims with a
  principal-owned immutable evidence registry, globally unique TXID, exact
  debt/network/destination/amount/finality binding and consume-once CONFIRMED or
  NOT_STARTED transitions plus atomic audit. Clean PostgreSQL 17 rehearsals pass
  for all three; containers were removed and production was untouched. Next and
  only remaining implementation package: B5.11 ledger-backed money finalization,
  followed by full B-set equality/review/status audit. Goal remains active.

- 2026-08-16 owner authorized continuous completion of all remaining E0/E0.3
  B packages. B5.3 notification queues, B5.4 order creation and B5.5
  automation/gifts are `REHEARSED` in clean disposable PostgreSQL 17 runs.
  B5.6 is intentionally `IN_PROGRESS`: paid/sent delivery is rehearsed, while
  payout_held/payout_triggered were rejected as delivery markers and moved to
  payout-intent/evidence work. B5.7 is `REHEARSED` with an ambiguity-safe schema
  redesign: token-bound claims, exact sent receipt, digest-backed pre-submit-only
  retry and terminal manual-review state for uncertain external delivery. Legacy
  blind retry was not copied. Independent reviews also require immutable client
  idempotency for generic order creation, a redemption ledger for gifts, strict
  sell pending-only claim/release evidence and machine-verifiable globally unique
  chain evidence. Production remains untouched. Next canonical slice: B5.8
  payout intent creation writers; continue automatically through B5.11.

- 2026-08-16 E0/E0.3 bot ACL B5 is `IN_PROGRESS`; B5.2 is `REHEARSED` for
  five residual non-money writers: promo creation, provider reset, atomic support
  admin reply, immutable referral claim and bot-user identity UPSERT. A clean
  disposable PostgreSQL 17 run proved bounded inputs, eight-way first-writer
  referral attribution, normalized promo creation, exact provider reset, support
  message/status fault rollback, profile UPSERT, PUBLIC denial and zero direct
  bot relation/sequence access. Failed clean runs exposed required embedded
  `ON CONFLICT`/`RETURNING` reads; only those owner columns were added. Six
  focused plan/decomposition tests pass; JSON, compile and diff checks are clean;
  the container was removed and production was untouched. Independent review
  correctly moved `add_vip` and `credit_referral_bonus` to B5.11: both are
  non-idempotent additive MONEY_WRITE and discard immutable order/swap source
  identity, so they require a ledger-backed atomic finalization contract.
  Residual shared-login actor, phantom-referrer, support-delivery and provider
  audit risks are recorded. Next canonical slice: B5.3 bot notification queue
  writer bodies.

- 2026-08-16 E0/E0.3 bot ACL B3 is now `REHEARSED`. B3.2b adds two
  proposal-only execute functions for exact-owner pending-order cancellation and
  retry amount update. A clean disposable PostgreSQL 17 rehearsal proves
  cross-owner/non-pending denial, explicit NULL/NaN/Infinity/nonpositive/range
  rejection, same-value retry semantics, twelve-caller cancellation with one
  winner, injected-update rollback, PUBLIC EXECUTE denial and zero bot direct
  relation access. The complete B3 set-equality gate covers 17 distinct methods
  across engagement, admin/config and owner workflow. Eight focused static tests
  pass; JSON and diff checks are clean; the container was removed; production
  was untouched. Independent review confirmed the minimal body grants and
  identified residual risks recorded in evidence: caller-supplied owner identity
  is not DB-authenticated, retry lacks old-value/version/idempotency CAS, and an
  amount mutation has no immutable intent/audit record. Next canonical slice:
  B4.1 operator order-workflow transition bodies in disposable PostgreSQL 17.

- 2026-08-16 Active route remains E0/E0.3 bot execute-only ACL. B3.2 is now
  explicitly split into B3.2a admin/config and B3.2b exact-owner order workflow.
  B3.2a is `REHEARSED` in a clean disposable PostgreSQL 17 instance: seven
  bounded `SECURITY DEFINER` functions preserve role allowlisting, first-writer
  block semantics, exact unblock, staff UPSERT/deactivation, address UPSERT and
  bounded reserve UPSERT while the bot retains zero direct table access. Eight
  concurrent block calls produced one winner; injected reserve failure left no
  row. The first run exposed missing UPSERT read columns and the clean rerun
  passed after narrowing them explicitly. Seven focused static tests pass; JSON
  and diff checks are clean; the task container was removed; production was
  untouched. Independent review confirmed the nine-method B3.2 boundary and
  flagged the residual shared-login/admin-identity limitation and consequential
  reserve configuration, both recorded without claiming DB-level admin policy.
  Next canonical slice: B3.2b exact-owner pending-order cancel and retry-amount
  writer bodies with cross-owner, finite-positive amount, concurrency and fault
  evidence.

- 2026-08-15 E0.3 Relay function-body coverage is complete at 43/43 read and 26/26 writer
  bodies. The disposable PostgreSQL 17 P5B and R1–R4 rehearsals prove exact grants,
  raw-access/PUBLIC denial, concurrency and injected-fault rollback. P5B fixed
  three ambiguous PL/pgSQL references and declared the implicit VIP UPSERT read.
  R1 adds bounded append-only audit plus atomic support creation/reply, requiring
  exactly one positive Telegram or web owner ID and returning no row/writes for
  cross-owner replies. R2 adds eight one-function-per-method lifecycle/payment/
  sell outbox writers: three queues produced twelve distinct `SKIP LOCKED`
  winners under twelve callers, attempts incremented once, completion/retry used
  exact sending-state CAS, and injected failure preserved the claimed state.
  R3 proves one winner under twelve concurrent block attempts, exact-ID unblock,
  and a no-argument audit cleanup fixed at 90 days; injected DELETE failures
  preserve both blocked-user and audit rows.
  R4 proves bounded concurrent order/sell/swap creation, fixed pending order/
  sell states, narrow swap status/provider values, web synthetic-user
  compatibility, exact ID-only `RETURNING` reads and insert fault rollback.
  Fifty-three targeted evidence tests pass; JSON and diff
  checks are clean; task-created containers were removed; production was not
  R5A proves verification/sell single-winner CAS, expected-status swap transition
  and bounded referral-address UPSERT; exact predicate/conflict reads were found
  through rehearsal. Production was untouched. E0/E0.3 remains `IN_PROGRESS`:
  R5B re-attestation adds explicit repeat/no-op evidence for expiry and
  paid-to-sent while preserving the existing concurrency and rollback evidence
  for failed-session and pending-to-paid. R6 settlement proves concurrent
  single-winner execution and atomic sell status, immutable ledger, VIP credit
  and outbox rollback. The Relay body subplan is 69/69, but the bot graph,
  shared roles/bundles and root money-capable services remain. Independent agent
  review was unavailable because delegation requires explicit owner permission.
  Next canonical slice: build the exact exchange-bot caller-to-repository/DB
  capability graph before any role design or rollout.
  The source-bound bot graph is `EXACT_STATIC_GRAPH`: 22 repository imports,
  19 factory bindings, 183 call edges, 39 relations and zero direct SQL,
  unresolved methods or uncalled imports. Exact relation/column/scope/transition
  evidence now covers all 135 unique methods (63 read-only, 72 writer/schema;
  21 dynamic-SQL), with union audit reporting zero gaps. The payment-session
  recent limit was safely capped at 100 in SQLite/PostgreSQL. Evidence also
  exposes blockers that prohibit ACL design: unbounded lists, runtime SQLite
  schema ensures, missing review owner predicates, non-serialized rate toggles
  and ambiguous referral aggregate modes. `referral_bonus` now fail-closed
  separates owner totals (`user_id`, no dates) from the intentional operator
  period aggregate (`user_id=None`, both dates); mixed modes fail and a two-user
  regression proves isolation. The completion audit proves 135 expected/135 covered/zero
  missing; all 36 bot evidence tests pass, with JSON, compile and diff checks
  clean. Review comment/finalization now require exact order and Telegram owner,
  remain in `pending_comment`, deny cross-owner access and use a PostgreSQL row
  lock plus CAS for terminal publication/review. Bot callers pass identity
  explicitly. Admin audit writes now require a positive actor, action length
  1..80, optional integer target and details at most 500 before SQL. Twelve
  focused tests pass. Recipient, subscriber and order-customer reads now retain
  their full-list caller contract while using deterministic `user_id` keyset
  pages of 500; a 505-row boundary regression proves no recipients are dropped.
  The repository script and 18 focused evidence tests pass; JSON, compile and
  diff checks are clean. SQLite rate toggles now use `BEGIN IMMEDIATE` and an
  atomic invert with `RETURNING`; PostgreSQL retains its atomic row-locking
  update. Twelve concurrent SQLite toggles prove six true/six false results and
  the correct final parity. The engagement package is now verified with zero
  blockers; the repository script and 18 focused evidence tests pass. Production
  was not changed. `engagement_store.ensure_review` no longer creates its table
  or index in the user request path; the test fixture owns schema creation and
  missing migrations now fail instead of being silently repaired. The same 18
  evidence tests pass after source re-attestation. Alert throttle/watermark
  operations also no longer create tables in request paths. Their SQLite schema
  is now explicit in `deploy/sqlite/017_alerts.sql`, both relations are required
  by startup validation, the metadata-only PostgreSQL proposal matches that
  contract, and a missing-migration repository test fails closed. Alert tests
  pass (repository plus 17 behavioral checks), the SQLite runtime validator
  passes, and 28 static E0.3 tests pass; the PostgreSQL rehearsal was not rerun
  because `TEST_POSTGRES_DSN` is unset. Status-notification and receipt methods
  now also contain no runtime `CREATE`/`ALTER`: explicit SQLite migrations cover
  gift vouchers, sent markers and receipts, `order_receipts` moved into the
  shared startup profile, and missing receipt schema fails closed. This reduced
  the exact bot matrix from 72 to 71 writer/schema methods (64 read-only), with
  all 135 methods still evidenced. Three repository/schema scripts and 30 E0.3
  tests pass; JSON, compile and diff checks are clean. Production was untouched.
  Ops, wallet and provider-health request paths now contain no DDL. Explicit
  SQLite migrations cover all six relations, and the shared startup profile now
  validates them, including previously unchecked `wallet_send_intents`; the P7
  metadata-only proposal was expanded without granting business-table reads.
  Source reclassification removes `CREATE` from the Relay graph (22 relation
  objects) and narrows the bot matrix to 66 read-only / 69 writer-or-schema,
  still 135/135 evidenced. Four repository/schema scripts and 36 focused E0.3
  tests pass; JSON, compile and diff checks are clean. Production was untouched.
  Payment-transition and reconciliation constructors/methods now contain no
  DDL. Explicit SQLite migrations own their four tables and indexes;
  reconciliation's compatibility `ensure_sqlite_schema` is now a read-only
  presence check. All four relations moved into shared startup validation and
  the metadata-only P7 proposal was synchronized. Three repository/schema
  scripts and 36 focused E0.3 tests pass; compile and diff checks are clean.
  Production was untouched. Remaining DDL-bearing repositories are exactly six:
  address-book, bot-notification, lifecycle, payout, settlement and
  shadow-payout. Address-book and shadow-payout no longer expose or invoke
  `ensure_schema`; their explicit SQLite migration owns both relations and the
  payout-shadow index. Both moved from bot-only expectations into the shared
  startup profile, and P7 metadata validation was synchronized without adding
  business reads. Three repository/schema scripts and 28 focused E0.3 tests
  pass; JSON, compile and diff checks are clean. Production was untouched.
  Bot-notification and lifecycle constructors now perform no DDL. Explicit
  SQLite migrations own both durable queues; `order_lifecycle_work`, which was
  previously absent from startup validation, is now required by the shared
  profile and P7 metadata-only proposal. Three repository/schema scripts and 36
  focused E0.3 tests pass; JSON, compile and diff checks are clean. Production
  was untouched. Exactly two DDL-bearing repositories remain: payout and
  Payout and sell-settlement now contain no DDL; payout compatibility
  `ensure_schema` functions are read-only presence checks. Explicit SQLite
  migrations own all six payout/settlement relations, which now belong to the
  shared startup profile and P7 metadata contract. A repository-wide regression
  proves zero `CREATE TABLE`, `CREATE INDEX`, `ALTER TABLE` or `executescript`,
  and all SQLite migrations apply together to an empty database. Payout,
  referral, reconciliation, settlement and schema scripts pass; 42 focused E0.3
  tests pass; JSON, compile and diff checks are clean. Production was untouched.
  Runtime-DDL remediation is complete. Bot ACL design is still blocked by
  boundedness debt in order-read, payout, reconciliation, reporting,
  small-store and support packages. Both payout review lists and reconciliation
  pending-order lists now clamp caller limits to 1..100 identically in SQLite
  and PostgreSQL. Their evidence packages are verified with zero blockers;
  repository scripts and eight focused graph/package tests pass, with JSON,
  compile and diff checks clean. Production was untouched. Remaining boundedness
  packages were order-read, reporting, small-store and support. Support ticket
  lists now clamp to 100 and Telegram threads retain the latest 500 messages;
  swap unfinished reads accept at most 32 final statuses and return at most 500
  rows; payout candidates clamp the window to 168 hours and result limit to 100.
  SQLite/PostgreSQL implementations match, and both support/small-store evidence
  packages are verified with zero blockers. Three repository scripts, 20 graph/
  matrix tests and four focused package tests pass; JSON, compile and diff checks
  are clean. Production was untouched. Order-read now bounds customer history
  and workers to 100, exports to 10,000, activity/stuck results to 1,000 and the
  activity window to 365 days. Reporting caps promo/reserve/currency rows at 100
  and rejects cumulative-stat input collections above 32. SQLite/PostgreSQL
  implementations and source-bound evidence agree; every bot capability package
  now has zero blockers, and 27 focused package/graph/matrix/schema/repository
  tests pass. Production was untouched. Next canonical slice: design the exact
  bot ACL and prove it in a disposable PostgreSQL rehearsal before any rollout.
  `docs/e0-3-bot-acl-plan.v1.json` now defines that proposal: one NOINHERIT
  exchange-bot login, one NOLOGIN function owner, 135 bounded SECURITY DEFINER
  entry points, execute-only login access and zero direct relation/sequence
  grants. It explicitly records that the current single process necessarily
  receives the union of owner/operator/background functions; it does not claim
  unimplemented role separation. Nineteen focused tests pass with JSON and diff
  checks clean. Next canonical slice: measure the bot connection envelope, then
  implement B1 role-envelope rehearsal in disposable PostgreSQL 17. Read-only
  runtime observation proves one active exchange-bot process, two host CPUs,
  seven process threads, no custom executor and no repository connection pool.
  The bounded maximum is seven PostgreSQL clients (six Python 3.12 default
  executor workers plus one serialized event-loop slot); the proposal limit is
  ten with three diagnostic/recovery slots. PostgreSQL 17 has 97 ordinary slots,
  and the current shared role remains capped at 60. The source/unit-bound budget
  is `docs/e0-3-bot-connection-budget.v1.json`; ten focused budget/ACL/matrix
  tests pass. Production was untouched. B1 now passes in a clean disposable
  PostgreSQL 17 container: the login has exactly four representative EXECUTEs,
  zero direct relation/sequence access, no DDL/TEMP or membership, fixed
  statement/lock timeouts and a rehearsed ten-connection ceiling. Operator,
  exact-customer, background payout-candidate and reserve reads enforce their
  bounds; invalid identity/window/limits fail closed. The eleventh connection
  is denied. Evidence is `docs/e0-3-bot-b1-role-envelope-rehearsal.v1.json`;
  the task container was removed, ten focused static tests pass, and production
  was untouched. B2 was split without overstating completion: B2.1 covers all
  seven owner-scoped reads and B2.2 will cover operator reads. B2.1 passes in a
  clean disposable PostgreSQL 17 container. Rate state, VIP total, owner-only
  referral bonus, creation-limit state and three Telegram support projections
  bind a positive exact owner; both cross-owner thread directions return zero,
  support lists cap at 100 and threads at the latest 500. The bot login retains
  zero direct SELECT. Evidence is
  `docs/e0-3-bot-b2-1-owner-reads-rehearsal.v1.json`; the container was removed,
  eight static ACL/budget/matrix tests pass, and production was untouched. Next
  canonical slice: B2.2 operator read bodies. B2.2a now passes in a clean
  disposable PostgreSQL 17 container: four execute-only engagement projections
  prove enabled-only broadcast count/keyset IDs, distinct customer keyset IDs
  and a bounded aggregate-only referral period. Page limits above 500, invalid
  cursors and reversed or >366-day periods fail closed; the bot retains zero
  direct table SELECT. Evidence is
  `docs/e0-3-bot-b2-2a-operator-engagement-reads-rehearsal.v1.json`; production
  was untouched. B2.2b now passes in a clean disposable PostgreSQL 17
  container. Ten execute-only functions cover every operator method in the
  order-read package, including bounded history/dashboard/activity/export,
  exact quote/snapshot, customer lookup and aggregate-only projections.
  Invalid IDs and limits fail closed, missing quote raises, missing snapshot
  remains null per the source contract, and the bot retains zero direct table
  SELECT. Evidence is
  `docs/e0-3-bot-b2-2b-operator-order-reads-rehearsal.v1.json`; production was
  untouched. Next canonical slice: B2.2c remaining operator payment, payout,
  reporting, sell and support reads. B2.2c1 now passes in a clean disposable
  PostgreSQL 17 container. Three payment-session and five payout execute-only
  reads preserve latest/recent/provider lookup, exact order/referral intent and
  bounded processing/review projections. Invalid IDs, provider modes and limits
  fail closed; the bot retains zero direct SELECT on payment/payout tables.
  Evidence is
  `docs/e0-3-bot-b2-2c1-operator-payment-payout-reads-rehearsal.v1.json`;
  production was untouched. Next canonical slice: B2.2c2 remaining reporting,
  sell and support operator reads. B2.2c2a now passes in a clean disposable
  PostgreSQL 17 container. Seven execute-only functions cover active promos,
  provider health/attempt aggregates, exact sell snapshot, support open count
  and both bounded staff ticket lists. Invalid limits, IDs and provider windows
  fail closed; the bot retains zero direct SELECT. Evidence is
  `docs/e0-3-bot-b2-2c2a-operator-config-sell-support-reads-rehearsal.v1.json`;
  production was untouched. Next canonical slice: B2.2c2b four remaining
  reporting operator reads. B2.2c2b now passes in a clean disposable
  PostgreSQL 17 container. Four execute-only reporting functions cover reserves,
  database-day summary, a bounded inclusive period report and cumulative
  aggregates with object/array types and 32-member caps enforced inside SQL.
  The first rehearsal caught unsupported `jsonb_object_length`; the proposal
  was corrected to count `jsonb_object_keys` and the clean rerun passed.
  A source-to-evidence set-equality test proves all 33 unique operator-read
  methods are covered exactly once. B2 owner/operator reads are `REHEARSED`;
  production was untouched. Evidence is
  `docs/e0-3-bot-b2-2c2b-operator-reporting-reads-rehearsal.v1.json`. Next
  canonical slice: B3 non-money writer bodies. B3.1 now passes in a clean
  disposable PostgreSQL 17 container. Eight execute-only engagement functions
  cover bounded audit append, owner review CAS/finalization, broadcast/rate
  disables, rate updates and serialized toggle. Rehearsal caught a missing
  `SELECT(id)` required by `INSERT ... RETURNING` and then an overbroad
  `SELECT *` blocked by column ACL; both were narrowed before the clean pass.
  Eight concurrent toggles produce exact parity, cross-owner review mutations
  return no change, injected audit failure rolls back, and bot direct DML stays
  denied. Evidence is
  `docs/e0-3-bot-b3-1-engagement-non-money-writers-rehearsal.v1.json`;
  production was untouched. Next canonical slice: B3.2 admin/config and owner
  workflow non-money writers.

- The owner reaffirmed the unified Obsidian ecosystem and canonical E0–E5
  route as the controlling project objective. `/root/docs/MEGA_PROMPT.md` is
  now the durable execution charter and `/root/AGENTS.md` requires reading it
  at the start of every task. It defines source precedence, deterministic
  `continue` semantics, bounded slices, gate statuses, component/trust roles,
  safe internet/open-source research, the FastAPI/aiogram/Laravel/PostgreSQL/
  Redis/Rust/native/Docker/Kubernetes technology policy, agent/plugin/DevOps
  usage, independent reviews, supply-chain gates and iteration closeout.
  `/root/docs/ecosystem-master-roadmap.md` remains the sole canonical product
  roadmap. Commercial/acquisition work is supporting evidence/backlog and must
  not replace the first unmet E0–E5 gate without an explicit owner decision.
  The first evidence-backed E0 audit is now recorded in
  `docs/e0-gate-status.v1.json` and `docs/e0-gate-audit.md`. E0 is
  `IN_PROGRESS`. On 2026-08-15 the owner explicitly removed Aurevia from the
  ecosystem scope; E0.1 is `SUPERSEDED`. E0.2 is now `VERIFIED`: the authoritative
  `docs/ecosystem-contracts.v1.json` plus concise Markdown replace the
  contradictory historical snapshot and inventory implemented/dormant Wallet,
  Exchange, KAIROS, LUMI, provider, operator and signer edges. The inventory
  truthfully records shared-process/dormant money capability, raw credential
  ingress on the disabled connect edge, shared Relay identity for shadow scope,
  advisory-only LUMI semantics and the linked-web disconnect CSRF gap. E0.4
  surface inventory remains `IN_PROGRESS`. E0.3 is now `IN_PROGRESS` with
  `docs/operational-ownership.v1.json`: it inventories twelve datastore classes,
  secret-reference groups and eight effectful writer classes without reading
  values/customer rows, and exposes shared full-schema DML, root principals,
  dormant money capability and UNKNOWN/PARTIAL lifecycle policy. Independent
  review originally rejected completion because owner-role labels were not accepted.
  On 2026-08-15 the project owner explicitly accepted the accountability map and
  remains the sole accountable principal/escalation authority for every role
  until written delegation; workloads are not owners. The decision is recorded
  in `docs/decisions/2026-08-15-e0-accountability-map.md`. A metadata-only member manifest now records exact credential
  variable names, missing/forbidden legacy refs, distinct signing domains and
  exact active/staged service-to-PostgreSQL-role bindings without storing values.
  The read-only PostgreSQL verifier reports the declared ACL matrix as a match
  (54 tables, 29 sequences, two functions), while shared `obsidian_app`, root
  principals and incomplete rotation/revocation/expiry remain open. E0.5 definition
  of CEX SLO/metrics/runbooks is `VERIFIED`. Read-only runtime observation found
  all seven named core units active, Relay/signer/KAIROS/LUMI on dedicated users,
  but exchange bot, support bot and Laravel admin still run as root. Two
  independent audit/review passes required corrections to scope the ledger to
  E0, derive first-unmet status, validate evidence paths and avoid broadening
  E0.5 into a runtime requirement. Five targeted tests pass with JSON and diff
  checks. E0.2 passed context-aware and independent product/security reviews
  after correcting false capability, CSRF, dormant-route and credential-flow
  claims. Next canonical dependency: define and verify the bounded lifecycle
  and remediation plan for shared secret bundles and broad money-writer roles;
  production rollout still requires separate authority and rollback evidence.
  `docs/e0-3-remediation-plan.v1.json` now freezes two independently planable,
  deployment-blocked workstreams: provider/identity credential-family splitting and per-process
  PostgreSQL roles with narrow transition functions. Unknown rotation or DB
  outcomes fail closed to disabled/HOLD/MANUAL plus reconciliation. No runtime
  mutation was authorized. Bounded partial artifacts now inventory eleven
  units/environment sources and source-ground notifier plus dormant-shadow DB
  capabilities. Relay/bot graphs are unassessed, shadow launches
  the full Relay entrypoint and must have no DB credential, and notifier targets
  three future bounded functions. Next repository-only slice: sanitized observed
  exact per-unit variable-name partitions with set-equality tests; then disposable
  PostgreSQL notifier ACL/function positive and adversarial denial rehearsal.
  A closed names-only observer now derives effective `/etc/systemd/system`
  EnvironmentFile chains, reset/order, inline-empty/unset names and exact configured
  name sets with stable bounded reads and restrictive metadata checks. The fresh
  observation is exact for configured names (not manager/PAM-injected process
  variables), emits no values and correctly exits NO_GO because the inactive
  callback unit's required env file is missing. The PostgreSQL 17 notifier
  function/ACL rehearsal is now green in a disposable
  container: exactly three proposed `SECURITY DEFINER` calls work, while direct
  table/sequence DML, DDL and TEMP plus invalid bindings are denied. The first
  run caught missing column-level SELECT for the bounded gift-voucher update;
  the second caught ambient PUBLIC TEMP privilege, and both proposal defects
  were corrected. This is proposal-only evidence: no production role/function/
  ACL/service changed. A follow-up twelve-caller rehearsal proved exactly one
  successful completion/review insert with eleven idempotent replays. A trigger-
  injected exception between notification marker insertion and gift update
  rolled both changes back, and a caller-side fault rolled review creation back.
  E0.3 remains `IN_PROGRESS`; Relay/bot graphs, shared roles/bundles and root
  money-capable services remain open. The disposable PostgreSQL 17 relay-shadow
  connection and money-SQL denial rehearsal is now green: the proposal forces NOLOGIN,
  null password, no memberships, no CONNECT/TEMP/schema/table/sequence/function
  capability, and money SQL/DDL/TEMP attempts fail. It also rejects ambient
  `PUBLIC CONNECT` or function `EXECUTE` rather than claiming a false pass. The
  production unit remains dormant, overprivileged in its template and `NO_GO`
  because it launches the full Relay entrypoint; nothing was deployed or
  restarted. Next canonical slice: exact Relay caller-to-repository/database
  capability graph. That source-hash-bound static graph is now complete: AST
  analysis covers all 17 repository factories, 71 caller edges and 23 relation
  objects; every import is called, every edge resolves to SQL evidence and the
  authoritative entrypoint contains no direct SQL/connection site. It confirms
  broad order/payment/sell/settlement money writers but grants no permission and
  reads no values or rows. E0.3 remains `IN_PROGRESS`; exact Relay writer columns
  and transition invariants, the bot graph, shared roles/bundles and root money-
  capable services remain open. Next canonical slice: classify exact Relay
  writer columns and transition invariants before designing its ACL.
  That PostgreSQL matrix is now complete for all 26 unique Relay writer methods
  across eleven source-hash-bound repositories. It records exact mutated columns
  or row-delete semantics, effect class, row locking, CAS, idempotency and same-
  transaction requirements. It confirms broad critical capabilities including
  order create/paid/sent/expiry, sell create/cancel/settlement, session failure,
  outboxes, access control and payout-destination metadata. No grant, function,
  migration, DB row or service changed. E0.3 remains `IN_PROGRESS`; next
  canonical slice: derive a proposal-only target Relay ACL/function design from
  this matrix before any disposable rehearsal or production consideration.
  That design now partitions all 26 writers into six ordered packages behind
  one future bounded `SECURITY DEFINER` function per method, with a NOLOGIN owner,
  zero direct DML/sequence grants and ambient privileges revoked. Review removed
  an unmeasured connection-limit guess and moved access/retention/payout metadata
  after audit/outbox packages. The plan remains `IN_PROGRESS`: relation-level
  read evidence cannot justify table-wide SELECT, and exact SQL signatures,
  returns and concurrency budget are not yet proven. No SQL migration, role,
  grant, DB row or service changed. Next canonical slice: exact Relay read-method
  column matrix.
  That source/schema-hash-bound matrix now covers all 43 Relay methods containing
  `SELECT`, including predicates, joins, order/lock columns and read dependencies
  inside writers. The two reachable payment-session `SELECT *` queries and the
  payment-outbox `RETURNING o.*` now use frozen explicit schema-order column
  lists in both SQLite/PostgreSQL paths as applicable. The seven reachable
  `COUNT(*)` methods now count schema-proven non-null keys instead:
  `referrals.referred_id`, `orders.order_id`, or `support_tickets.id`; aggregate
  result semantics are unchanged while required column authority is explicit.
  Source hashes, exact read columns and all dependent E0.3 evidence are
  synchronized, with regression checks rejecting a return of `COUNT(*)` in
  those methods. Seven purpose packages now cover all 43 read methods exactly
  once. The authorization decision rejects direct column/table SELECT and
  inherited purpose roles because one Relay login would receive their union and
  could bypass repository row predicates; the target is one bounded
  `SECURITY DEFINER` read function per method, owned by NOLOGIN principals, with
  login access limited to exact EXECUTE. Caller-use analysis then reduced
  `payment_session_store.latest_active_for_order` to return only `session_token`
  and `latest_for_order` to `session_token,status`; query-only predicate/order
  keys remain explicit in the read matrix. This removes unused client IP,
  user-agent, Telegram ID, QR and provider payload from both reachable paths
  while preserving tested repository contracts. Multi-purpose callers and
  payout-detail returns remain explicit blockers, not grants. No SQL
  function, role, grant, row, service, or production configuration changed.
  The formal read-contract ledger now closes nineteen of 43 methods: the two
  minimized payment-session reads, zero-argument metadata-only runtime schema
  validation and the complete P1 public-aggregate package. The validator returns only missing relation/column names,
  grants its NOLOGIN owner only `information_schema.columns` metadata and
  explicitly forbids business-table reads. The SQLite store check and targeted
  graph/matrix/ACL/manifest/contract tests pass. Public stats are aggregate-only
  with UTC time semantics; curated reserves are explicitly not wallet balances,
  ordered and bounded to 64 rows. All five reachable support reads now have
  exact web-owner predicates and cross-user denial semantics. Runtime list and
  thread reads are bounded to 100 tickets and the latest 500 messages, with
  chronological presentation preserved; the message body is accepted as
  purpose-required only behind the verified ticket-owner predicate. Referral
  stats/profile address and customer order/swap histories now have exact
  identity bindings and closed returns. Runtime order/swap limits are clamped
  to 100, order offset to 1,000,000, and receipt-ID batches reject more than 100
  instead of constructing an unbounded query. P2 customer scope is now complete:
  both sell-history methods clamp results to 100 and bind every payout field to
  the authenticated owner. Caller-use evidence proves payout details/bank and
  legacy `sbp_phone` fallback are required to show the originally selected
  destination; pending rows additionally require the exact deposit address.
  Cross-user reads return zero rows. P4 operator reporting is also complete:
  admin block and recent-order lists clamp to 100 rows, analytics collections
  have explicit bounds (15/24/32/32/64/20), and `today_status_counts` was
  corrected from operator scope to its actual public aggregate purpose. The
  Three SQLite store scripts and 45 targeted E0.3 tests pass; JSON, compile and
  diff checks are clean. The broader `test_security_p0.py` could not collect
  in the available venv because `bcrypt` is absent, so it is not claimed as
  verified. P3 interactive order/payment is now complete: six additional
  contracts bind lookup to an authorized order or opaque session token, keep
  payment invoice returns to provider/provider_invoice_id, define receipt state
  as empty/stored/sent, justify the swap destinations required by the active
  flow, and clamp duplicate detection to 1..300 seconds. P6 provider callback is
  also complete: Montera verification types are allowlisted, and Vertu/Trocador
  callback identifiers are bounded to 256 characters and used only for local
  correlation while authoritative status is independently fetched. P5 is now
  complete: all claims retain atomic pending-to-sending transitions and
  PostgreSQL `FOR UPDATE SKIP LOCKED`; expiry is capped at 1000, Vertu polling
  at 100 rows/30 days, payment polling at 100, tokens/providers are bounded,
  and both notification claims return only five consumer-required fields. All
  43 Relay read contracts are closed. Relay connection capacity was measured
  read-only on 2026-08-15: PostgreSQL has 100 max connections, 3 superuser
  reserved, and 1 observed client backend. The single-process/single-worker
  Relay now hard-caps its default executor at 8, so at most 8 threaded plus one
  synchronous repository call can overlap; the proposed `obsidian_relay` role
  limit is 12, retaining three diagnostic/recovery slots. This is evidence-only
  and not deployed. The Relay ACL role envelope then passed a no-volume
  PostgreSQL 17 rehearsal and the container was removed: login 13 was denied by
  `CONNECTION LIMIT 12`; direct table/sequence/DDL/TEMP access was denied; five
  representative `SECURITY DEFINER` functions proved bounded owner reads,
  `SKIP LOCKED` single-winner claim, atomic single-winner payment, injected-fault
  rollback and caller rollback. The first production-equivalent body package
  also passed a separate no-volume PostgreSQL 17 rehearsal: P7 metadata now
  uses `pg_catalog` (because `information_schema.columns` would require
  forbidden business privileges), its owner has zero business-table SELECT,
  and all four P1 aggregates prove UTC semantics, exact column grants, PUBLIC
  denial and the 64-row reserve bound. All twelve P2 customer-scoped bodies also
  passed PostgreSQL 17 rehearsal: ticket/order/swap/sell collections are bounded,
  support threads return only the latest 500 in chronological presentation,
  foreign customer and payout rows are excluded, and raw/PUBLIC access remains
  denied. `receipt_order_ids` was corrected from an unenforceable array-only
  signature to accept owner identity and join `orders` inside SECURITY DEFINER.
  P3 is now fully rehearsed at 8/8 current methods. The five former order-id-
  only Relay paths were replaced with owner-or-session-token-correlated
  repository methods and six production-equivalent SQL bodies; cross-owner,
  cross-token, missing authority, provider-prefix, raw-table and PUBLIC EXECUTE
  denials passed in disposable PostgreSQL 17. The token payment page no longer
  reaches the wildcard PaymentService/session lookup hidden behind a dynamic
  import: it calls a graph-visible six-field bearer-token projection. Montera
  and RSPay notification paths no longer fetch broad provider/order data by
  order ID alone. Numeric `/pay/{order_id}` fallback uses a two-hour HMAC proof
  bound to order and user, never the Relay secret in a URL; the bot issues that
  proof only when session creation fails. The redundant standalone token-match
  read is removed from the current Relay graph (its earlier proposal-only
  rehearsal remains historical and is excluded from rollout). P6 provider
  callbacks are now rehearsed at 3/3: Montera verification is an atomic
  pending/empty-field transition, Trocador correlation is a bounded exact ID
  projection, and Vertu exact/suffix lookup is restricted to provider `vertu`.
  A newly found ambiguity hazard was removed: suffix compatibility now returns
  a row only when exactly one Vertu payout matches. Twelve concurrent Montera
  requests produced one winner and eleven conflicts; injected-fault rollback,
  raw-table/update denial and PUBLIC EXECUTE denial passed in disposable
  PostgreSQL 17. Authoritative provider status remains independently fetched in
  application code. Body coverage is 28/69: 28/43 reads and 0/26 writers; 15
  reads and 26 writers remained at that point. P4 operator reporting is now
  rehearsed at 4/4: blocked users and recent orders enforce 1..100 limits,
  admin stats are aggregate-only, and analytics returns closed JSON collections
  bounded at 15/24/32/32/64/20 plus one totals object. The daily window is UTC
  regardless of caller TimeZone, recent orders retain deterministic tie-break
  ordering, and latest payment provider correlation is bounded per order.
  Raw relation access, direct mutation and PUBLIC EXECUTE were denied in
  disposable PostgreSQL 17; the container and temporary Unix socket were
  removed. P5A then rehearsed five of the eleven background state-machine read
  bodies: lifecycle, payment-notification and sell-notification claims each
  produced twelve distinct `FOR UPDATE SKIP LOCKED` winners under twelve
  concurrent callers, atomically moving each row pending-to-sending and
  incrementing attempts once. Vertu payment and payout pollers exclude stale,
  terminal, wrong-provider/status/order rows, validate filters and cap at 100.
  Raw relation and PUBLIC EXECUTE denials passed; the disposable container and
  Unix socket were removed. Body coverage is 37/69: 37/43 reads and 0/26
  writers; 6 reads and 26 writers remain. Production was untouched. Next
  canonical slice: rehearse the six P5B embedded-writer read bodies with full
  concurrency and fault rollback.

- SUPPORTING BACKLOG / NOT ACTIVE: acquisition evidence collection has started
  with a privacy-safe KPI contract
  (`contracts/commercial/acquisition-kpi-report.v1.json`), pure aggregate builder
  and read-only CLI. Cohorts below 10 users are suppressed, customer identifiers
  are forbidden recursively, fulfilled volume is explicitly GMV rather than
  revenue, and each report is SHA-256 bound. On the 2026-08-15 production
  snapshot (2026-05-10 through 2026-08-09), it reported 854 orders, 76 fulfilled
  orders, RUB 1,835,803 fulfilled GMV, 40 fulfilled users and 13 repeat fulfilled
  users (32.5%). Revenue, gross margin, EBITDA/SDE, CAC, LTV and contribution
  margin remain unavailable; financial/traction gates are therefore not yet
  verified. A normalized `financial-component-ledger.v1` contract and pure
  fail-closed reconciler now require source-bound consideration, crypto
  acquisition cost and explicit provider/network fees for every fulfilled
  order. Incomplete orders remain visible as coverage gaps and are excluded
  rather than guessed. Gross economic spread cannot be labelled revenue or
  gross margin until principal-versus-agent accounting policy is approved.
  Twenty-one targeted commercial/KPI/financial tests pass, plus JSON, Python
  compilation and diff checks. Backlog: obtain immutable provider, acquisition and
  network-fee exports, normalize them, and measure production coverage.

- ObsidianExchange is a production non-KYC RUB↔crypto exchange exposed through
  a FastAPI site/API, aiogram Telegram bot, Mini App, payment-provider router,
  multi-chain wallets/payouts, support/monitoring, and an untracked Laravel
  admin panel. `/root` remains the canonical Git checkout; production runtime
  code is now `/opt/obsidian-exchange`, the shared DB is
  `/var/lib/obsidian-exchange/exchange.db`, and wallet data is
  `/var/lib/obsidian-exchange-wallet`. `night-dev` and `night-audit` are
  worktrees, not separate products.
- The product direction is a non-custodial wallet ecosystem: shared portfolio,
  address book/history and external wallet connectors, with any native signing
  isolated in a future secure mobile app. Do not put customer seed/private keys
  in server-delivered Mini App JavaScript.
- The immediate priority is safety and consolidation, not adding coins,
  providers, Kubernetes, or more AI infrastructure.
- KAIROS exchange onboarding is simplified for non-crypto users: visible Bybit
  diagnostics no longer mention network environments; balance results explain
  that currencies belong to the user's exchange account, not an unknown wallet;
  API-key parts, OKX regions and the no-withdrawal safety rule use plain Russian.
  The service was restarted healthy; Python/JavaScript syntax and live-copy
  checks pass, with no visible `mainnet` on the exchange page.
- Wallet market integration now has an explicit two-lane product contract.
  `private_exchange` is the existing ObsidianExchange non-KYC route;
  `verified_exchanges` means an external CEX account whose KYC and custody stay
  with that exchange. Mini App gained a `Рынок` screen explaining identity and
  custody before action; the KYC lane is truthfully `planned`, not connected to
  KAIROS or user API keys yet. `/api/wallet/service-modes` requires Telegram
  authentication. The relay was deployed/restarted healthy; route, landmine,
  portfolio, Python/JavaScript syntax and the new contract test pass.
- The wallet `Рынок` screen now shows live read-only BTC/ETH/LTC/TRX quotes
  from Bybit, OKX and KuCoin through KAIROS. KAIROS exposes a cached public-only
  `/api/market/quotes`; the relay reaches it only over loopback through a
  validating fail-soft gateway and exposes authenticated `/api/wallet/market`.
  No balances, credentials or trade actions cross this API; if KAIROS fails,
  the wallet and private exchange stay available. A runtime UI defect from the
  first market slice (wrong escaping helper name) was fixed before this deploy.
  Both services were restarted healthy; live KAIROS returned 12 quotes, the
  relay gateway returned three BTC sources, unauthenticated wallet market access
  returned 403, and syntax/route/landmine/gateway tests pass.
- P0 hardening is in progress in the uncommitted working tree: FastAPI web
  analytics now authorizes only configured Telegram IDs; Laravel Filament is
  fail-closed behind an explicit email allowlist; Trocador callbacks ignore
  claimed status, fetch it from the provider, and apply a forward-only state
  machine. The same verified transition path now protects `/swap/{token}`;
  bearer session tokens were removed from audit messages, and host resource
  metrics require signed Telegram admin authentication. The production relay
  was restarted after changing its default bind from public `0.0.0.0:5001` to
  `127.0.0.1:5001`; loopback and public HTTPS health checks both returned 200.
- Manual payout reconciliation is now fail-closed in production: bot, Mini App
  and Laravel require a network-valid TXID, require current order status
  `paid`, and atomically transition only `paid → sent`. The old fake/manual
  TXID and `pending → sent` paths were removed; relay and bot were restarted.
- TOTP setup no longer sends the seed in a QR image query string. The QR is
  generated server-side and embedded as a data URI; the seed-bearing setup page
  is `no-store`/`no-referrer`, and the old QR endpoint returns 404 in production.
- Laravel Filament authorization now uses a dedicated non-mass-assignable
  `users.is_admin` boolean instead of email. The production migration was
  applied with a false default. The user confirmed the first/only account is
  theirs; it is now the sole admin and `canAccessPanel` returns allowed.
- Laravel admin MFA is deployed using `pragmarx/google2fa` 9.0. The encrypted,
  hidden, non-mass-assignable TOTP seed is enrolled through a 5-minute
  server-side pending session after password verification; later logins require
  password + TOTP. Middleware logs out any existing admin session lacking an
  enrolled seed. The sole admin has not enrolled yet and must complete setup on
  the next login. TOTP time steps are atomically claimed in the database, so a
  code accepted by one concurrent login cannot be replayed by another.
- PHP security dependencies were updated after Composer reported 18 advisories:
  Filament 3.3.54, Guzzle 7.15.3, PSR-7 2.13.0 and CommonMark 2.9.0 (plus
  compatible transitive patches). Tests pass and `composer audit --locked`
  reports no advisories; the restarted admin login returns HTTPS 200.
- Laravel admin action auditing is deployed. Admin-originated Eloquent
  create/update/delete events and explicit `force_payout` attempt/result stages
  are written without payload values to `admin_action_audits`; network traits
  are HMAC fingerprints and entries in one HTTP request share a correlation
  UUID. SQLite triggers reject audit updates/deletes. Migration batch 5 is
  applied; 10 Laravel tests (22 assertions) pass, and both loopback and public
  `/admin-panel/login` return 200 after restart with zero service restarts.
- Filament order state-forgery/IDOR hardening is deployed. `OrderResource`
  denies create/edit/delete/deleteAny, exposes no edit/delete table/header
  actions, and refreshes the order immediately before `force_payout`, aborting
  unless it is still `paid`. Non-admin forged sessions receive 403 and admins
  without enrolled MFA are logged out. The Laravel suite now passes 13 tests
  (30 assertions); production capability checks all return false, public login
  is 200, and `admin-panel` is active with zero restarts.
- The full Filament mutation matrix is now fail-closed and deployed. A shared
  `ReadOnlyResource` denies create/edit/delete/deleteAny for Order, DCA,
  GiftVoucher, LimitOrder, PayoutQueue, RiskEvent, SellOrder and SwapSession;
  their Eloquent models are fully guarded against mass assignment. Review can
  only moderate a validated status and cannot be deleted. SupportTicket can
  only change a validated status or add a whitelisted admin reply and cannot
  be deleted. BlockedUser retains create/unblock but cannot be edited; create
  input is whitelisted. Production capability checks match this matrix,
  exchange SQLite `quick_check` is `ok`, public admin login is 200, the error
  journal is empty, and 16 Laravel tests pass with 78 assertions.
- MFA replay regression uses an in-memory migrated database and confirms the
  same time step succeeds once, fails on reuse and allows the next step. The
  production replay-guard migration is applied and admin login remains healthy.
- Local secret-file permissions were tightened: active project `.env` files,
  sensitive diagnostic dumps and retired news-bot unit backups are now `0600`.
  Git now ignores timestamped `.env` backups and `debug_info/`, preventing those
  credential-bearing artifacts from being accidentally added.
- Stale payout launch paths are fail-closed. The inactive `payout-btcpay` unit
  was removed from autostart; both payout units are now disabled/inactive while
  `exchange-bot` remains enabled and running. Legacy `start-bot.sh` launchers
  now exit with guidance to use systemd; their originals are preserved under
  `backups/stale-entrypoints-20260808/` with `0600` permissions.
- A durable `payout_intents` boundary is deployed. Every crypto order payout now
  persists one immutable intent before signing, atomically claims it, records
  the TXID on success, and sends uncertain signer outcomes to terminal `review`
  without automatic retry. Production schema is present and initially empty;
  SQLite `quick_check` is `ok` and the restarted `exchange-bot` is healthy.
- A separate payout worker is installed and enabled/active.
  `payment/payout_worker.py` consumes one pending intent atomically and
  records `succeeded` or terminal `review`; it refuses to start unless
  `PAYOUT_WORKER_ENABLED=1`. `relay/services/payout_signer.py` supports only the
  encrypted BTC/LTC and gated EVM vaults, with no legacy bitcoinlib fallback.
  The hardened unit runs as `obsidian-payout` with narrow `/var/lib` write paths
  and a root-owned `0600` signer-only env. An empty-queue smoke test ran under
  UID 997/GID 986 without errors. BTC/LTC secure vaults are configured, EVM is
  not. At the user's explicit direction the worker was enabled for normal
  consumption without an on-chain canary. Preflight showed an empty intent
  queue and healthy SQLite, so enabling it sent nothing. Post-enable it is
  active with zero restarts/errors; intents and outbox remain empty.
- Bot-side succeeded-intent reconciliation is implemented and deployed. A
  single SQLite transaction now enforces `paid → sent`, copies the worker TXID,
  applies VIP volume and any referral credit once behind a per-order ledger,
  and inserts the customer message into a transactional Telegram outbox. The
  outbox dispatcher leaves uncertain post-send crashes in `sending` for review
  rather than blindly duplicating. Targeted intent/worker/reconciliation and
  landmine tests pass; after restart `exchange-bot` is active, both new tables
  are empty, and production SQLite `quick_check` is `ok`.
- Administrative payout-intent review is deployed in the Telegram bot.
  `/payout_review` lists `processing/review`; `/payout_confirm ID TXID` closes
  only after payout discovery re-reads the chain and finds the exact final
  destination/amount/TXID; `/payout_requeue ID` works only from terminal
  `review` when the signer idempotency ledger proves the key was never claimed.
  Ambiguous, unreadable or TXID-bearing signer records block retry. Both actions
  append to `payout_intent_audit`. Targeted review/discovery tests pass; the
  deployed queue and audit are empty and the bot is healthy.
- Runtime relocation is complete. Bot, relay FastAPI, Laravel admin, support
  bot, monitor and notifier all run from `/opt/obsidian-exchange` through
  validated systemd drop-ins. Shared/support/Laravel SQLite files live under
  `/var/lib/obsidian-exchange`; wallet data is owned `obsidian-payout` under a
  `0700` separate directory; runtime env files are root-owned `0600` under
  `/etc/obsidian-exchange`; logs target `/var/log/obsidian-exchange`.
  `obsidian-payout` is a system/nologin user with DB-directory and wallet access.
  `/root/exchange.db` and `/root/wallet_data` are compatibility symlinks to the
  new canonical locations, preventing split-brain from stale scripts. The
  pre-cutover DB/wallet snapshot and original units are retained `0700/0600`
  under `/root/backups/runtime-cutover-20260808/` for rollback.
- Post-cutover verification: all six services are active with zero restarts and
  `/opt` working directories; no process holds the old DB; public API and admin
  login return 200; exchange, Laravel and support SQLite quick checks are `ok`;
  exchange DB has 837 orders, no payout intents/outbox backlog; error-only
  journal since cutover is empty.
- The isolated signer unit is `obsidian-payout-worker.service` (enabled/active),
  not the retired `exchange-payout.service` (disabled/inactive). Its production
  Telegram outbox table is `notification_outbox`. A 2026-08-08 recheck found
  SQLite `quick_check` `ok` and `payout_intents`, `notification_outbox`, and
  `payout_intent_audit` all empty; no first real payout has occurred yet.
- Signing is removed from the Telegram bot. Its order payout path only creates
  an immutable pending intent and never claims/signs it; bitcoinlib fallback,
  wallet unlock and `send_crypto` were removed. The bot systemd environment
  explicitly erases the legacy `PAYOUT_SEED` and wallet password; `/proc`
  verified both absent. `WALLET_PAYOUT_PASSWORD` now exists only in the worker
  env, not the shared bot env. Referral withdrawals are fail-closed/manual until
  they receive their own intent type, and balances use the read-only `/wallet`
  surface. Isolation and payout regression tests pass; bot and public API are
  healthy.
- Stages 3–7 were resumed on 2026-08-08. Plaintext credentials were removed
  from the disabled legacy `callback-handler.service` and the old bot override;
  callback now fail-closed requires `/etc/obsidian-exchange/callback-handler.env`
  with a newly issued token. The bot was restarted healthy and `/proc` confirms
  zero-length `PAYOUT_SEED` and `WALLET_PAYOUT_PASSWORD`. Provider-side rotation
  is still required because ignored historical `.env` copies contained exposed
  values; no old token was copied into the new unit.
- Gitleaks 8.30.0 was checksum-verified and installed (8.30.1 was avoided due
  to an upstream default-rule regression report). It found zero leaks across
  266 Git commits and zero in the staged scope. A source-only scan found 66
  redacted matches, almost entirely ignored `.env`/legacy gold copies plus one
  vendor false positive. Do not delete those copies until provider rotation is
  coordinated, but never commit or back them up again.
- Reproducibility work is in progress: admin-panel, payment worker, payout
  core/reconciliation/signer, systemd templates, security baseline/report and
  P0 tests are now staged together with all prior tracked modifications. The
  index has 171 files, no unstaged tracked changes, and passes staged gitleaks
  plus `git diff --check`; no commit or push has been made. Admin now has an npm
  lockfile. CI gained checksum-pinned full-history gitleaks, pinned Bandit and
  pip-audit, Composer audit and admin npm audit. Current audits: Python,
  Composer and npm have zero known advisories; Bandit has zero High, with 21
  Medium and 145 Low active-source findings held in an incremental baseline.
- Production dependency locks now exist for the actual bot and relay Python
  boundaries plus an OS-package manifest. Provenance filtering removed apt-only
  packages from PyPI locks. Audit found vulnerable `ecdsa 0.17.0` and old pip
  in bot venv; pip is now 26.1.2, ecdsa 0.19.2, unused `litecoin-utils` was
  removed because it forced ecdsa 0.17.0, and missing cffi was installed.
  `pip check` is clean. One unfixed P-256 timing advisory remains explicitly
  documented/ignored: ecdsa is transitive through bitcoinlib while active
  BTC/LTC use secp256k1; removal of bitcoinlib remains required.
- System Python relay audit found 47 advisories. PEP 668 correctly prevented
  in-place mutation, so relay now runs from the isolated
  `/opt/obsidian-exchange/relay-venv` with patched FastAPI, Starlette, aiohttp,
  python-multipart, Pillow, idna and aiogram. Hidden runtime dependencies
  bcrypt 4.3.0 and Jinja2 3.1.6 are pinned. Route, P0 and landmine tests passed;
  a shadow instance returned 200 for `/` and `/api/stats/public`. Production
  was switched on 2026-08-08: it is active with zero restarts, clean startup
  logs, healthy providers and a successful public HTTPS API check. `pip check`
  passes and the audit is clean except the documented transitive ecdsa advisory.
- Updated bot dependencies passed BTC wallet, address, payout intent, worker,
  reconciliation, review and signer-isolation tests. `exchange-bot` and
  `obsidian-payout-worker` were restarted and are active with zero restarts;
  error journal is empty, SQLite is `ok`, and payout intents remain empty.
- The active security report is `/root/security_best_practices_report.md`.
  Referral withdrawals now use their own durable `referral_payout_intents`
  debt type; no fake/negative order IDs are used. A request atomically reserves
  the current BTC bonus behind one active immutable intent, the isolated worker
  signs it with a distinct idempotency key, and succeeded reconciliation debits
  referral rows exactly once and creates a customer outbox message. Repeated
  requests return the existing intent. Targeted order/referral worker,
  reconciliation, isolation and landmine tests pass. Production bot/worker are
  active with zero restarts; both payout queues are empty, SQLite is `ok`, the
  error journal is empty and the public API is healthy. Referral `review`
  handling is now deployed: `/payout_review` includes `REF#` debts,
  `/refpayout_confirm` requires an exact final transfer from a trusted payout
  source, and `/refpayout_requeue` requires signer-ledger proof that broadcast
  never began; both actions are audited. Fault-injection covers crashes after
  claim, during reconciliation and after outbox claim. It exposed and fixed an
  early SQLite commit caused by schema preparation inside referral ledger
  mutation; schema work now precedes all debits, and rollback/retry is atomic.
  Production had no referral intents before the fix. Post-deploy queues/audit
  remain empty, SQLite is `ok`, both services have zero restarts/errors.
- PostgreSQL migration rehearsal began without changing production. An official
  PostgreSQL 17 Alpine container was temporarily bound only to
  `127.0.0.1:55432`; `deploy/postgres/001_payout_core.sql` created numeric
  payout/referral/audit/outbox tables and atomic `FOR UPDATE SKIP LOCKED` claim
  functions. The transactional rehearsal passed active-referral uniqueness,
  review/requeue identity and rollback; two parallel sessions claimed distinct
  order debts (201 and 202). The container was stopped/auto-removed; its image
  remains cached. Production still uses SQLite.
- `relay/core/db_runtime.py` is the first explicit DB runtime boundary. The
  deployed payout worker now uses it for SQLite with foreign keys and a bounded
  busy timeout, and fails closed if a PostgreSQL URL is set before the PG store
  exists. Targeted DB/payout/fault tests pass; the restarted worker is active
  with zero restarts/errors and empty queues. Inventory found 41 Python files
  still opening SQLite directly plus dialect-specific SQL; these must migrate
  behind repositories before any production database cutover. The ordered plan
  is documented in `docs/database-migration.md`.
- Two DB-boundary passes are deployed. Telegram bot, FastAPI relay/auth, payout
  queue/discovery, notifier, monitor, alert throttle and conversion/dispute
  watchers now open the exchange SQLite through `core/db_runtime.py`; direct
  SQLite-opening files in active Python scope fell from 41 to 31. Related
  compile, route, P0, landmine, alert, receipt and payout fault tests pass.
  Bot, relay, worker, notifier and monitor are active with zero restarts; error
  journals are empty, public API/Mini App respond, SQLite is `ok`, and both
  payout queues remain empty. Support bot intentionally has a separate support
  database and needs a two-database contract before its connections change.
- The third DB-boundary pass moved address book, chain reconciliation, client
  trust, receipts, shadow payout, wallet linking and wallet-send intent storage
  behind `db_runtime`. A fresh-database test exposed `smart_router` altering
  `provider_health` before creating it; the base table is now created
  idempotently first. Tests pass and deployed bot/relay report zero restarts,
  clean journals, four healthy providers, SQLite `ok`, and empty payout queues.
- Support bot now has an explicit two-database contract: exchange/operator
  reads use the main runtime boundary, while its own support state uses
  `auxiliary_sqlite_connect` and intentionally ignores a future exchange
  `DATABASE_URL`. The deployed support bot is active with zero restarts/errors;
  exchange and support SQLite quick checks are `ok`. Direct SQLite-opening
  files in the scoped Python runtime fell from 31 to 23 (including the one
  intentional implementation inside `db_runtime` itself).
- The fourth DB-boundary pass moved active sell guard/payout, Montera/RSPay,
  offerings, payment service, payout circuit/guard, polling, smart router and
  conversion/evidence analytics behind `db_runtime`. Sell/provider/offerings,
  trust, payout fault, analytics, route and landmine tests pass. Production
  bot/relay are active with zero restarts/errors; four providers and public
  rates/offerings are healthy, SQLite is `ok`, payout/referral queues are empty.
  Two pre-existing sell orders remain pending/received/paying and were not
  modified or executed by this work.
- Tracked active Python source now has zero direct `sqlite3.connect` calls.
  `tests/test_db_boundary_inventory.py` enforces this against Git-tracked files;
  the only allowlisted source occurrences are `db_runtime` itself and two
  inactive legacy/one-shot files. Untracked venv/gold/compatibility copies are
  deliberately outside release inventory. Production remains SQLite until the
  SQL dialect/repository stages are complete; this boundary work alone does
  not authorize a PostgreSQL cutover.
- Payout worker persistence is now behind `repositories/payout_store.py`; the
  worker no longer imports payout tables or SQLite SQL. Deployed production
  uses `SQLitePayoutStore`. `PostgresPayoutStore` uses the rehearsed PostgreSQL
  claim functions and was verified with psycopg 3.3.4 against a temporary
  PostgreSQL 17 container: order claim/succeed stored its TXID, referral
  claim/review stored only the error class, and no debt re-claimed. The
  container was removed. PostgreSQL selection is double-gated by
  `DATABASE_URL` plus `PAYOUT_POSTGRES_ENABLED`; production has not enabled it.
  Worker is active with zero restarts/errors, SQLite is `ok`, and both queues
  are empty. psycopg 3.3.4 is pinned in bot/relay locks; it is installed only in
  the isolated relay rehearsal venv until a separately approved cutover.
- Order/referral succeeded reconciliation and the Telegram notification outbox
  are now behind `repositories/reconciliation_store.py`. SQLite contract tests
  pass. The PostgreSQL implementation was verified against PostgreSQL 17 for
  idempotent order reconciliation, referral debit, and outbox claim/retry/sent.
  PostgreSQL selection requires both `PAYOUT_POSTGRES_ENABLED` and
  `RECONCILIATION_POSTGRES_ENABLED`; neither production cutover nor dual-write
  is authorized. The SQLite implementation is deployed; `exchange-bot` is
  active with zero restarts/errors, production SQLite is `ok`, and payout,
  referral and notification-outbox queues are empty. The one-off rehearsal
  database was removed; the pre-existing rehearsal container was left running.
- FastAPI dashboard identity/session persistence is now behind
  `repositories/web_auth_store.py`: registration and lookup, session lifecycle,
  password/TOTP changes, Telegram linking and expired-session cleanup no longer
  contain SQLite SQL in the adapter. SQLite/P0/route tests pass. PostgreSQL 17
  rehearsal passed duplicate-identity, mutation and session-expiry contracts.
  PostgreSQL selection is separately gated by `WEB_AUTH_POSTGRES_ENABLED`;
  production remains SQLite. The SQLite repository is deployed: relay is
  active with zero restarts/errors, public API and login return successfully,
  SQLite `quick_check` is `ok`, and the existing 28 users/18 sessions were
  preserved. The one-off PostgreSQL database was removed. Order/payment writers
  are intentionally next and must be extracted as complete transactions rather
  than partial dual writes.
- Ordinary website and Mini App buy-order creation now share
  `repositories/order_creation_store.py`. It preserves the invariant that the
  agreed rate/crypto amount and pending order are one INSERT, and preserves the
  Mini App 90-second duplicate lookup including active payment-session token.
  SQLite, route and P0 tests pass; equivalent PostgreSQL SQL passed against a
  temporary PG17 fixture. PostgreSQL activation is gated by
  `ORDER_POSTGRES_ENABLED` and must remain disabled until a canonical complete
  orders/payment schema exists. Bot rate-lock/gift/DCA/limit creation and all
  payment status transitions remain separate transactional work. The SQLite
  implementation is deployed; relay is active with zero restarts/errors,
  public API and root Mini App page respond, SQLite is `ok` with 841 orders,
  and the one-off PostgreSQL fixture database was removed.
- Verified incoming-payment confirmation is now centralized in
  `repositories/payment_transition_store.py`. All active FastAPI provider
  callbacks/polls and the bot TRC-20 watcher use one atomic `pending → paid`
  transition that also closes the matching active payment session, appends
  bounded provider/evidence metadata and creates a unique customer outbox item.
  Repeated callbacks are idempotent; expired/closed orders cannot move backward.
  Fault injection proves an outbox failure rolls back the order and audit.
  Telegram delivery explicitly checks HTTP success; definite failures retry,
  while a crash after send leaves `sending` for review. The TRC-20 watcher no
  longer writes `sent` directly and only creates an immutable payout intent;
  missing intent creation escalates to workers. SQLite, PostgreSQL 17, receipt,
  landmine, P0, routes, signer-isolation and reconciliation tests pass.
  Montera video/PDF requests and all PDF receipt/dispute routing, including
  Vertu, remain intact. Vertu has no provider-originated requested_type signal.
  The SQLite implementation is deployed: relay and bot are active with zero
  restarts/errors, public API/root respond, SQLite `quick_check` is `ok`, and
  payment audit/outbox plus both payout queues are empty. The one-off PG test
  database was removed; production PostgreSQL flags remain disabled.
- The primary Telegram buy-order/rate-lock workflow is behind
  `repositories/bot_order_store.py`. Creating an order and consuming a live
  lock are one transaction with user/currency/expiry checks; a stale or raced
  lock writes the ordinary fallback quote instead of granting the locked quote
  twice. Replacing an active lock is also atomic. SQLite fault/race tests and a
  PostgreSQL 17 contract test pass, along with landmine, signer-isolation,
  payout and route/P0 regressions. PostgreSQL activation is gated by
  `BOT_ORDER_POSTGRES_ENABLED`; production remains SQLite. Promo usage is still
  a separate post-order transaction and is the next atomicity boundary. The
  SQLite repository is deployed: bot is active with zero restarts/errors,
  SQLite is `ok` with 841 orders, no active rate locks, and empty payment/payout
  queues. The one-off PostgreSQL database was removed.
- Promo claiming is now inside the same bot order transaction. The repository
  conditionally increments `promo_codes.uses_count`, inserts the unique
  `promo_uses` ledger and selects the correct quote for lock/no-lock and
  promo-won/promo-lost outcomes. A request losing the last promo use receives
  the precomputed no-promo quote, never an unledgered discount. This also fixes
  ordinary bot orders previously omitting VIP/promo from their quote because
  `get_rate_with_markup` was called without the user identity. SQLite limit/race
  and PostgreSQL 17 contracts pass with quote/pricing, landmine, P0, routes,
  payout fault/reconciliation and DB-boundary regressions. The SQLite update is
  deployed: bot is active with zero restarts/errors, SQLite is `ok` with 841
  orders, 93 active promo-code rows and 7 usage-ledger rows preserved, and
  payout/payment queues are empty. The one-off PostgreSQL DB was removed.

- Gift voucher issue/redemption is now behind `repositories/gift_store.py`.
  Issuing atomically creates the pending sender order and unique voucher;
  redemption atomically claims only `paid` vouchers and creates one paid
  recipient order. Payment confirmation now promotes its linked voucher from
  `pending` to `paid` inside the payment transaction, fixing the missing state
  bridge. SQLite issue/duplicate/redeem and payment-transition tests pass with
  landmine/reconciliation regressions. The four historical pending vouchers
  all belong to expired orders, so none were promoted retroactively. The
  SQLite implementation is deployed: relay/bot are active with zero
  restarts/errors, SQLite is `ok`, historical gift states are unchanged, and
  payout/payment queues are empty. The PostgreSQL 17 contract now passes issue,
  duplicate-code rollback, own-gift refusal and single redemption. Activation
  remains separately gated by `GIFT_POSTGRES_ENABLED`.

- DCA creation, cancellation and due execution now use
  `repositories/dca_store.py`. A due row carries its `next_run` as a CAS token;
  one transaction rechecks active/due state, creates the quoted pending order
  and advances `runs_total/next_run`, so concurrent runners cannot duplicate a
  scheduled purchase. Invalid destinations cancel only active schedules.
  SQLite single-winner and regression tests pass. Production currently has no
  DCA rows, making SQLite deployment state-neutral. The SQLite repository is
  deployed: bot is active with zero restarts/errors, SQLite is `ok`, and payout
  queue is empty. `PostgresDcaStore` and `006_scheduled_orders.sql` now pass a
  PostgreSQL 17 create/due/CAS single-winner contract. Activation is separately
  gated by `DCA_POSTGRES_ENABLED`; production remains SQLite.

- Limit-order creation, cancellation, expiry and trigger now use
  `repositories/limit_order_store.py`. Triggering rechecks `active`, expiry and
  the expected expiry CAS token inside the same transaction that creates the
  quoted order and stores `triggered/order_id`, preventing duplicate orders
  from parallel watchers. SQLite single-winner/landmine/DB-boundary tests pass.
  Production currently has no limit-order rows. The SQLite repository is
  deployed: bot is active with zero restarts/errors, SQLite is `ok`, and payout
  queue is empty. `PostgresLimitOrderStore` and `006_scheduled_orders.sql` now
  pass a PostgreSQL 17 create/active/trigger CAS single-winner contract.
  Activation is gated by `LIMIT_ORDER_POSTGRES_ENABLED`; production is SQLite.

- Payment-session creation, lookup, ordinary state transitions and polling
  expiry are now behind `repositories/payment_session_store.py`. Invoice data
  is inserted in one transaction instead of insert-then-update, state changes
  lock/recheck the current state, and expiry only claims active sessions. Both
  SQLite and PostgreSQL 17 contracts pass with route, landmine, payment and
  order regressions. `007_payment_sessions.sql` is the canonical rehearsal
  table; PostgreSQL selection is gated by `PAYMENT_SESSION_POSTGRES_ENABLED`.
  The SQLite implementation is deployed: `relay-fastapi` is active with zero
  restarts/errors and the public stats endpoint responds. Production flags
  remain disabled.

- Support ticket/message writes are now behind `repositories/support_store.py`
  for both FastAPI and Telegram. Ticket plus first message is one transaction;
  user replies lock/check the web or Telegram owner before appending and
  reopening, and admin reply plus `answered` is atomic. SQLite and PostgreSQL
  17 contracts pass, including foreign-owner refusal. `008_support.sql` is
  gated by `SUPPORT_POSTGRES_ENABLED`. The SQLite implementation is deployed;
  relay/bot are active with zero restarts/errors, SQLite is `ok`, and the five
  existing tickets/messages were preserved.

- Swap creation and status writes are now behind `repositories/swap_store.py`
  for FastAPI and Telegram. All page, verified Trocador callback and bot watcher
  status changes use compare-and-set on the observed old status, so competing
  pollers cannot overwrite a newer result or duplicate a completion event.
  SQLite and PostgreSQL 17 contracts pass; `009_swap_sessions.sql` is gated by
  `SWAP_POSTGRES_ENABLED`. The SQLite implementation is deployed; relay/bot are
  active with zero restarts/errors, SQLite is `ok`, and all 10 existing swaps
  were preserved.

- The complete sell-order write lifecycle is now behind
  `repositories/sell_order_store.py`: web/bot creation, single-winner payout
  claim, provider reference/status recording, safe release, terminal settle,
  provider rejection back to the real debt queue, manual unclaim only without
  a provider reference, and staff rejection. Provider network calls remain
  outside DB transactions; all monetary state changes use compare-and-set and
  `paid` is terminal. SQLite, PostgreSQL 17, sell payout, TON marker,
  wallet-send, route, landmine and signer-isolation regressions pass.
  `010_sell_orders.sql` is gated by `SELL_ORDER_POSTGRES_ENABLED`. The SQLite
  implementation is deployed; relay/bot are active with zero restarts/errors,
  SQLite is `ok`, and the existing two paid/two pending sells were unchanged.

- Bot user registration, immutable referral attribution and referral payout
  address writes are now behind `repositories/user_profile_store.py` for bot
  and web. SQLite uses `BEGIN IMMEDIATE` to make the first referrer win even
  though the legacy table lacks a unique `referred_id`; PostgreSQL enforces
  that invariant with a unique constraint. User metadata upserts and referral
  address replacement are dialect-neutral. SQLite and PostgreSQL 17 contracts
  pass; `011_user_profiles.sql` is gated by `USER_PROFILE_POSTGRES_ENABLED`.
  The SQLite implementation is deployed: relay/bot are active with zero
  restarts/errors, SQLite is `ok`, and 1222 users/6 referrals/0 addresses were
  preserved.

- Administrative staff/access/config writes are behind
  `repositories/admin_config_store.py`: worker/operator activation and
  deactivation, user/address blocks and curated reserves. Role-derived table
  selection is allowlisted; address unblock accepts normalized aliases as one
  operation. SQLite and PostgreSQL 17 contracts pass; `012_admin_config.sql`
  is gated by `ADMIN_CONFIG_POSTGRES_ENABLED`. The SQLite implementation is
  deployed with relay/bot healthy; 2 workers, 2 operators, 3 blocked users,
  0 blocked addresses and 6 reserves were preserved. The only direct address
  write left is an intentional one-time SQLite normalization inside `init_db`.

- Manual and win-back promo creation are behind
  `repositories/promo_admin_store.py`. Win-back promo creation and its unique
  `sent_notifications` claim are one transaction, preventing duplicate promo
  issuance. The obsolete, unused non-atomic `apply_promo_use` bypass was
  removed; actual claiming remains atomic in `bot_order_store`. SQLite,
  PostgreSQL 17 and bot-order regressions pass; `013_promos.sql` is gated by
  `PROMO_ADMIN_POSTGRES_ENABLED`. The SQLite implementation is deployed; bot
  is active with zero restarts/errors, SQLite is `ok`, and 93 promos/7 uses
  were preserved.

- Verified wallet links and pre-sign wallet-send intents are behind
  `repositories/wallet_store.py`. Cryptographic ownership verification remains
  outside the store; only proven addresses are persisted. Send intent is still
  written before wallet signing, and `mark_signed` does not change any payment
  or sell status. Read methods no longer attempt schema writes on read-only
  databases. SQLite, PostgreSQL 17, wallet-link, wallet-send and landmine tests
  pass; `014_wallet_store.sql` is gated by `WALLET_STORE_POSTGRES_ENABLED`.
  The SQLite implementation is deployed: relay/bot are active with zero
  restarts/errors, SQLite is `ok`, and production has 0 links/0 intents.

- Receipt/evidence metadata, delivery markers and dispute claiming are behind
  `repositories/receipt_store.py`. Files remain root-protected on disk; the
  store owns path/filename/content type/SHA-256, idempotent `receipt_sent_at`,
  duplicate-hash lookup and dispute candidates. A watcher now compare-and-set
  claims `dispute_opened_at` immediately before any external dispute/manual
  action, preventing two instances from opening or reporting the same dispute;
  unknown provider status remains unclaimed for later retry. SQLite,
  PostgreSQL 17, receipt routing/fraud, route and landmine tests pass, including
  PDF/video and Vertu/Montera/XPay chat routes. `015_receipts.sql` is gated by
  `RECEIPT_POSTGRES_ENABLED`. The SQLite implementation is deployed: relay/bot
  are active with zero restarts/errors, SQLite is `ok`, and 89 receipts/65
  previously marked disputes were preserved.

- Durable payout circuit flags and FastAPI application audit writes are behind
  `repositories/ops_store.py`. Freeze/unfreeze now update the flag and bounded
  reason together in one transaction instead of two independent commits;
  audit remains append-only at the adapter boundary. SQLite, PostgreSQL 17,
  route, landmine and runtime-path tests pass; `016_ops.sql` is gated by
  `OPS_POSTGRES_ENABLED`. The SQLite implementation is deployed: relay/bot are
  active with zero restarts/errors, SQLite is `ok`, payout freeze remains `0`,
  and 3004 existing audit events were preserved.

- Durable alert throttles and monotonic high-water marks are behind
  `repositories/alert_store.py`. SQLite and PostgreSQL use atomic conditional
  updates so concurrent healthy processes cannot send the same alert or raise
  the same watermark twice; database failure remains deliberately fail-open so
  customer-money alerts are duplicated rather than suppressed. SQLite,
  PostgreSQL 17, 17 alert-throttle checks and landmine tests pass;
  `017_alerts.sql` is gated by `ALERT_POSTGRES_ENABLED`. The SQLite
  implementation is deployed: relay/bot are active with zero restarts/errors,
  SQLite is `ok`, and 51 throttle fingerprints/1 watermark were preserved.

- Client address-book notes/history and payout-guard shadow decisions are now
  behind `address_book_store.py` and `shadow_payout_store.py`. PostgreSQL is
  separately fail-closed behind `ADDRESS_BOOK_POSTGRES_ENABLED` and
  `SHADOW_PAYOUT_POSTGRES_ENABLED`; SQLite and PostgreSQL 17 contracts pass,
  including address ownership/hidden-note behavior and shadow outcome updates.
  A fresh production snapshot matched all 49 PostgreSQL tables by count and
  canonical SHA-256 (841 orders, 0 address notes, 48 shadow decisions). The
  SQLite path is deployed; bot/relay are active with zero restarts, SQLite is
  `ok`, and the loopback public-stats endpoint returns 200. The temporary
  snapshot was removed and PostgreSQL production flags remain off.
- Legacy operational reads are now PostgreSQL-capable. The monitor's physical
  `payout_queue` check uses `legacy_runtime_store.py`, gated by
  `LEGACY_RUNTIME_POSTGRES_ENABLED`; the same store contracts `risk_events`.
  Laravel's read-only exchange models can select PostgreSQL through
  `EXCHANGE_DB_CONNECTION`/`EXCHANGE_DATABASE_URL` while defaulting to SQLite.
  SQLite and isolated PostgreSQL 17 contracts pass, all 16 Laravel tests pass,
  and deployed monitor/admin services are active with zero restarts/warnings;
  admin login is 200, SQLite is `ok`, the stuck legacy queue is empty, and 50
  historical risk events are preserved. PostgreSQL production flags stay off.
- The explicit PostgreSQL cutover/rollback runbook is
  `docs/postgresql-cutover-runbook.md`. It defines the writer freeze, immutable
  SQLite snapshot, 49-table count/hash gate, service start order, last safe
  rollback point, and forbids simple SQLite rollback after the first PG write.
  `deploy/postgres/cutover_preflight.py` is deployed in `/opt` and fail-closed:
  migrations 001–020 are contiguous, but it reports `NO-GO` because 21 active
  runtime modules still call SQLite outside repositories. A clean PostgreSQL
  17 rehearsal loaded the current 841-order snapshot and matched 49/49 tables;
  temporary rehearsal data was removed. Production was not switched and no
  PostgreSQL flags were enabled.
- The first post-runbook blocker reduction is deployed. Monitor stuck-order,
  conversion and daily aggregates now use the existing `reporting_store`; the
  legacy paid/sent notifier ledger and atomic gift-voucher promotion use the
  new `status_notification_store.py`, fail-closed behind
  `STATUS_NOTIFICATION_POSTGRES_ENABLED`. SQLite and PostgreSQL 17 contracts,
  syntax, boundary, runtime-path and landmine tests pass. Monitor/notifier are
  active with zero restarts/warnings, SQLite is `ok`, and notifier backlog is
  empty. The deployed cutover guard fell from 21 to 19 blockers; PG flags stay
  off and the temporary contract database was removed.
- Receipt/dispute and payout-safety residual reads are now repository-backed.
  `receipt_store` owns payment-session lookup, payout guard fields and receipt
  fraud profiles; `ops_store` owns rolling payout totals and destination rows;
  the unused direct dispute-watch connection was removed. SQLite/PostgreSQL 17
  contracts and receipt, payout, fault, P0, boundary and landmine regressions
  pass. Bot/relay are active with zero restarts/warnings, public stats return
  200, SQLite is `ok`, payout freeze remains off, and the deployed cutover
  guard fell from 19 to 15 blockers. PostgreSQL flags remain off.
- Operational read models are deployed behind
  `OPERATIONAL_READ_POSTGRES_ENABLED`: conversion and receipt watches,
  payout/review queue, client trust counts, and curated offering reserves now
  use `operational_read_store.py`. Old/new production SQLite outputs matched
  exactly (including 10 stuck payouts, 11 unresolved receipts and 69 review
  debts). SQLite/PostgreSQL 17 contracts plus trust, queue, receipt, offerings,
  boundary and landmine tests pass. Bot/relay are active with zero restarts or
  warnings, public stats return 200 and SQLite is `ok`. The deployed cutover
  guard fell from 15 to 11 blockers; PostgreSQL flags remain off.
- RSPay integration resumed. Two complete cabinet credential pairs are kept
  only in root-owned `0600` runtime env files; never copy their values into Git,
  logs or this memory. Methods are classic `card`/`sbp` without mandatory
  receipt, `qr → sberbank_qr_vnm`, and direct `deeplink`; `RSPAY_RECEIPT=0`.
  On 2026-08-09 both credential pairs passed signed read-only balance checks.
  Runtime/code now route `card`/`sbp` through the BT pair and QR/deeplink through
  the first pair; transaction IDs carry the profile so status, cancellation and
  receipt upload reuse the correct cabinet. The webhook accepts either cabinet
  signature. A 2,000 RUB QR live canary returned a payment link and was cancelled
  successfully; card and SBP authenticated but had no free requisites. Mock tests,
  syntax and deployment checks pass. On 2026-08-09 the user explicitly approved
  production activation, so `rspay` was removed from `DISABLED_PROVIDERS` while
  preserving all other kill switches. The router reports RSPay enabled with all
  four credentials present; bot/relay are active with zero restarts, public stats
  return 200, and an unsigned webhook is rejected with 401. Keep RSPay after the
  established channels until live BT requisites/conversion establish its quality.
  The transaction-list endpoint still returns 401 and needs separate investigation.
  Cutover guard remains at 10.
- On 2026-08-09 the provider enabled test requisites for the RSPay BT cabinet.
  A live 2,000 RUB canary succeeded for both `card` (card/bank/recipient) and
  `sbp` (phone/bank/recipient). Both began `awaiting_payment`, were immediately
  cancelled through the signed API, and then read back as `cancelled`; no money
  was paid and no crypto payout was triggered. The RSPay contract suite passes;
  relay and bot are active with zero restarts and no warning journal entries.
- On 2026-08-09 a fresh 2,000 RUB BT/card invoice was intentionally left
  pending for the user to inspect in the RSPay cabinet: merchant order
  `lkcanary178626836523be6d`, local invoice
  `obsidian_lkcanary178626836523be6d_19fe5e434481a9ec295e_bt`, RSPay internal
  id `1855213`; status was `pending`/`awaiting_payment` at creation.
- On 2026-08-09 the bot gained explicit QR and deeplink payment buttons for
  the RSPay QR/deeplink cabinet, shown to users as `Оплата по QR-коду` and
  `Оплата по ссылке` (no provider branding). Smart routing priority is now
  `Vertu → RSPay → XPay → Montera ...`; RSPay was added to the RU tier and
  escalation chain. Runtime files were deployed, `exchange-bot` restarted
  once, remains active with zero restarts, and the order/landmine tests pass.
- PostgreSQL residual-boundary work on 2026-08-09 reduced the deployed cutover
  guard from 10 blockers to 2. Montera rating and support-operator access now
  use existing PostgreSQL-capable stores. Chain reconciliation and payout
  discovery use `operational_read_store`, preserving fail-closed used-TXID
  behavior and SQLite/PostgreSQL time-window parity. Sell guard/payout and
  wallet-send reads use the expanded `sell_order_store`; deposit TXID claiming
  is an atomic single-winner CAS in both databases, and dead wallet SQLite DDL
  helpers were removed. SQLite/domain/landmine/boundary tests and isolated
  PostgreSQL 17 contracts pass. Relay, bot and support bot were deployed and
  restarted active with zero restarts/warnings; SQLite is `ok`, payout/referral
  queues and notification outbox are empty, and loopback/current public API
  checks pass. The old `obmen-obscure.ru` name did not resolve; the configured
  `obsidian-exchange.org` endpoint returned 200. PostgreSQL flags remain off.
- The next 2026-08-09 residual pass moved seven bot staff/provider accesses,
  five bot DCA/limit/gift/swap reads, four FastAPI support reads and five
  FastAPI swap/sell reads behind existing PostgreSQL-capable repositories.
  Direct `db_conn` sites fell from 115 to 103 in the bot and 39 to 33 in
  FastAPI. Ownership and pending-only sell invariants remain explicit at the
  adapter/store boundary. The payout store gained SQLite/PostgreSQL order
  intent create/read/review/admin-confirm/requeue contracts with audit in the
  same transaction; bot integration is still pending. A PostgreSQL concurrency
  stress test exposed a conflict that could surface on the idempotency-key
  unique constraint instead of `order_id`; using untargeted `ON CONFLICT DO
  NOTHING` fixed it and 20 concurrent contract runs passed. The preflight now
  has a canonical AST guard, so deleting connection wrappers cannot produce a
  false `GO`; deployed output remains `NO-GO` with 266 raw authoritative-DB
  findings across the two god-files and three payout core SQL modules. SQLite,
  isolated PostgreSQL 17, route/P0/landmine and worker tests pass. Bot, relay
  and payout worker were deployed/restarted active with zero restarts/warnings;
  SQLite is `ok`, money/outbox queues are empty and loopback/public APIs pass.
  PostgreSQL production flags remain off.

## Important decisions

- 2026-08-16 the owner chose to preserve and execute the full canonical E0–E5
  programme thoroughly rather than cut it down to a short MVP. Relevant agents,
  plugins, maintained frameworks, external prior art, advisory/RAG/MCP and
  multi-agent tooling, orchestration, and multi-cloud deployment may be used
  aggressively when they provide measurable value and pass the charter's
  security, provenance, licensing, isolation, rollback, and operational gates.
  This is not a mandate to add every technology: the active route remains the
  first unmet gate, E0/E0.3 bot ACL adapter wiring and rollout rehearsal.

- 2026-08-11 the owner reiterated that work must follow the complete canonical
  E0–E5 roadmap and preserve the original unified-ecosystem direction, rather
  than narrowing progress reports or implementation decisions to the current
  E3 slice. Local E3 contract completion is only a dependency: E4 unified money
  UX and E5 native non-custodial wallet gates remain explicit future work.

- 2026-08-10 the owner confirmed the unified ecosystem as the strict product
  route for the foreseeable future: one user experience around the
  non-custodial wallet, ObsidianExchange as the private non-KYC RUB↔crypto
  lane, external verified/KYC exchanges through KAIROS, and LUMI as an
  advisory/risk layer rather than a money executor. Aurevia was later removed
  from product scope by the owner on 2026-08-15.
  Prefer professional, layered, secure and practical trading, engineering,
  scanning and monitoring tools across backend/frontend/UI/UX. Select and
  introduce tools per bounded need with provenance, signature/checksum,
  license, maintenance and sandbox review; never bulk-install an unvetted tool
  catalog or execute forum/Tor code directly in production. New components
  must preserve least privilege, fail-closed money paths, auditable intents,
  isolated signing and the non-custodial key boundary.
- 2026-08-10 `docs/ecosystem-master-roadmap.md` is the canonical product route
  from the current PostgreSQL/isolated-signer production baseline. It assigns
  ObsidianExchange, Wallet, KAIROS, LUMI and the future native wallet explicit
  trust roles; defines
  the private non-KYC and external-CEX/KYC lanes, ten non-crossing security
  boundaries, stages E0–E5 and measurable gates. The immediate package is a
  current API/trust-boundary contract and read-only Wallet/KAIROS/LUMI runtime
  inventory, followed by a `PortfolioSource`/`CustodyDomain` model and a
  read-only CEX connection/permission design. It explicitly authorizes no live
  trading, production user CEX keys or payout changes.
- 2026-08-10 `docs/ecosystem-contracts.md` records the first E0 runtime/trust
  inventory. Wallet currently reaches KAIROS only through the authenticated,
  loopback-only, validating, fail-soft public quote gateway; this is the only
  approved Wallet→KAIROS contract. KAIROS and LUMI are loopback-bound and
  healthy but both run as root without systemd sandboxing. KAIROS has no HTTP
  auth, uses CORS `*`, colocates market reads with start/stop/trade/credential
  mutation routes, and `/api/trade` ignores its body and calls `trade_now()`.
  A mistaken empty diagnostic POST timed out, but immediate status/runtime/log
  verification proved live disabled, no connected CEX, no capital/submit,
  zero operations and zero ledger entries. Do not probe that endpoint again.
  KAIROS raw JSON mode `0644` contains two active AI keys (no active CEX keys),
  so migrate/rotate them without exposing values. LUMI has bearer/vault code
  but is currently not configured and in compatibility mode, making protected
  routes effectively unauthenticated; it also contains scanner/sandbox/apply
  capabilities that must be outside the trading trust domain. Before E1,
  harden/split the KAIROS control plane, enable a narrow authenticated LUMI
  advisory contract, move both to least-privilege users/vaults, and add tests.
- 2026-08-10 the first KAIROS/LUMI P0 hardening slice is deployed. KAIROS now
  denies all operator/control/UI APIs without a constant-time Bearer token;
  only exact health/version/public-quotes GET and static UI assets are public.
  Wildcard CORS and production docs are removed. The operator UI prompts on
  each load and keeps its token only in tab memory. Direct `/api/trade` accepts
  a strict future intent envelope but returns 409, and the final engine submit
  boundary always HOLDs until persisted trade intents/reconciliation exist.
  LUMI production compatibility is locked; a separate service token permits
  KAIROS only the exact conflict-resolution and host-registration POST routes,
  not scanner/sandbox/real-apply. Two active AI keys were atomically migrated
  without display from plaintext `0644` JSON into an AES-256-GCM vault; config
  now contains two refs, while key/vault/security env/config are root `0600`
  and legacy CEX secret lines are absent. No active CEX credentials exist.
  Both units have NoNewPrivileges, PrivateTmp and UMask 0077; 28 targeted tests,
  compile, preflight and unit verification pass. Services are active with zero
  restarts/warnings; unauthenticated KAIROS/LUMI protected routes return 401,
  authenticated KAIROS returns 200, three public quote sources and Exchange API
  are healthy, and live/capital/submit/operations remain zero. They still run
  as root because runtime/venvs remain under `/root`; next relocate both to
  `/opt`, assign separate non-login users and narrow filesystem/egress. Rotate
  the two provider AI keys externally after the new vault path is accepted.
- Target architecture: thin site/bot/Mini App adapters around one exchange
  core, formal payment/payout state machine, evidence records, persisted
  idempotent payout intents, append-only audit/outbox, separate least-privilege
  payout signer, then SQLite→PostgreSQL after contract tests.
- Treat `/var/lib/obsidian-exchange/exchange.db` as the production database.
  `/root/exchange.db` is only a compatibility symlink. Other physical
  DBs and legacy code must be inventoried against real systemd/cron entrypoints
  before recoverable quarantine; never assume copies are live.
- Keep the wallet ecosystem non-custodial. Finish existing surfaces and safety
  boundaries before expanding asset/provider scope.

## Audit results

- 2026-08-08 read-only audit identified P0 risks: admin authorization by email
  substring in FastAPI; Laravel panel access allowed to any authenticated user;
  unauthenticated/unverified Trocador status webhook; secrets and production
  artifacts mixed with source; multiple direct SQLite writers; hot-wallet
  signing reachable from application/bot processes.
- Other material risks: webhook/session/PII logging, missing login/TOTP attempt
  throttles, TOTP secret in a query string, public server stats, fragmented and
  unlocked Python dependencies, large god-files and legacy duplicates.
- Positive findings: active SQL is predominantly parameterized; no confirmed
  active SQL injection, command injection, or SSRF; most primary webhooks and
  current payout guards are fail-closed.
- All 43 standalone test suites passed with `/root/bot/venv/bin/python`.
  System Python lacks `eth_account`, demonstrating environment drift rather
  than a code failure.
- Installed official Codex skills: security-best-practices,
  security-threat-model, security-ownership-map, playwright, and sentry. They
  become available on the next user turn.
- Production unit inventory found parallel definitions for `relay-fastapi` and
  legacy `relay`, plus duplicate payout workers (`exchange-payout` and
  `payout-btcpay`); all inspected application units run as root. Runtime audit:
  `relay-fastapi`, exchange bot/notifier, admin panel and support bot are active;
  legacy relay, polling worker, callback handler and both payout units are
  inactive. `payout-btcpay` is enabled but cannot currently satisfy its required
  inactive `docker.target`; do not start either payout unit without reconciling
  the intended payout path and idempotency controls.
- The systemd payout definitions are stale: both target the missing
  `/root/payout/auto_payout.py`. Actual signing is embedded in the active
  `exchange-bot`; startup logs confirm its secure BTC/LTC vaults are unlocked.
  `start-bot.sh` is also stale and still references the missing payout path.
- A Telegram credential is embedded in the world-readable
  `callback-handler.service`; treat it as exposed, rotate it, and move the
  replacement to a root-readable environment file. Never record its value.
- The active `exchange-bot` systemd override also contains an inline plaintext
  payout seed. Its value must never be displayed or recorded; moving/rotating
  it is part of the credential work explicitly deferred by the user.
- 2026-08-08: all standalone `tests/test_*.py` suites passed under
  `/root/bot/venv/bin/python`, including the new P0 security regression test.
- 2026-08-08: after extending P0 hardening, `test_security_p0.py`,
  `test_routes.py` (89 routes), `test_landmines.py`, Python compilation and
  `git diff --check` all passed.
- 2026-08-08: payout reconciliation hardening passed P0, TXID, route and
  landmine tests, Python/PHP syntax checks, Laravel tests and `diff --check`;
  post-deploy relay/bot health and HTTPS checks passed.
- Runtime role check found two configured Telegram admin IDs but no linked web
  accounts, and an empty Laravel admin email allowlist. Both web admin surfaces
  are therefore currently fail-closed/inaccessible. Establish immutable admin
  identities deliberately before enforcing admin MFA; do not reopen the old
  email-substring or any-authenticated-user paths. Laravel no longer uses its
  email allowlist at all; its immutable database role is deployed.

## Next concrete steps

- 2026-08-12 the owner selected the harder competitive native-wallet stack:
  Swift/SwiftUI and Kotlin/Compose shells around a Rust/UniFFI core, Bitcoin
  Signet first, Bitcoin Core libsecp256k1 family later, hardware-backed wrapping
  plus server-verified App Attest/Play Integrity risk signals. ADR-0001 records
  the decision. E5 key boundary v2 corrects the earlier impossible claim:
  platform hardware protects a non-exportable wrapping/authentication key, not
  the Bitcoin secp256k1 key; wallet-secret ciphertext is at rest and plaintext
  may exist only briefly in bounded native-process memory after local auth, with
  mandatory zeroization and no server access. The pure technology-selection
  contract keeps mainnet, keys, derivation/signing and extra chains disabled.
- 2026-08-12 the native Rust scaffold under `native-wallet/` now pins
  rust-bitcoin 0.32.102 with default features disabled. `wallet-core` fully
  parses address checksums, requires Bitcoin Signet, rejects non-canonical text
  and returns the exact destination scriptPubKey through UniFFI. Mainnet, key,
  signing, storage, network and broadcast APIs remain absent; every preview is
  non-signable. All 158 E5 tests, 3 Rust tests, locked build, strict Clippy,
  formatting and scoped diff checks pass. RustSec remains an explicit incomplete
  gate because `cargo-audit` is not installed; no clean dependency audit is
  claimed. The following slice now binds one to sixteen validated outputs in
  strict scriptPubKey order, rejects duplicate destination scripts and
  overflow/zero values, accepts a bounded total input and derives the fee only
  as inputs minus outputs. The UniFFI surface carries the validated output set;
  no caller-supplied fee remains. All 158 E5/landmine tests, 4 Rust tests,
  locked build, strict Clippy, formatting and scoped diff checks pass. The next
  slice now binds transaction version two, lock time and 1–64 canonical unique
  input outpoints/sequences/amounts. A non-zero lock time requires a non-final
  sequence. The core builds the exact empty-scriptSig/witness consensus
  serialization and requires its SHA-256 to match the displayed payload digest;
  input amounts remain explicitly unauthenticated UTXO metadata. UniFFI exposes
  the validated structure without any key/sign/network method. All 158
  E5/landmine tests, 5 Rust tests, locked build, strict Clippy, formatting and
  scoped diff checks pass. Each input now also requires fresh
  `native-signet-utxo-evidence.v1` from the exact allowlisted Bitcoin Core
  Signet snapshot contract. Its canonical digest binds block height/hash/time,
  outpoint, amount, sequence and previous scriptPubKey; unknown sources,
  malformed/non-canonical fields, drift and evidence older than ten minutes
  fail closed. A bounded consensus `MerkleBlock` is now locally decoded: its
  header hash must match the observed block, its partial tree must match the
  header Merkle root and it must yield exactly the previous TXID. The result is
  `TX_INCLUSION_VERIFIED_CHAIN_AND_UTXO_STATE_NOT_VERIFIED`: inclusion is true,
  while trusted-chain and current-unspent state remain false; no network API
  was added. All 158 E5/landmine tests, 6 Rust tests, locked build, strict
  Clippy, formatting and scoped diff checks pass. Pinned cargo-audit 0.22.2 is
  now installed and scanned the locked 92-crate graph against 1,211 RustSec
  advisories with `--deny warnings` cleanly. Evidence now also contains 1–144
  canonical headers from an explicitly unreviewed external checkpoint. The core
  validates exact height arithmetic, first-link/pairwise continuity and that
  the final header is the Merkle-proof block. It emits
  `LINKED_TO_UNREVIEWED_CHECKPOINT_NOT_CONSENSUS_VERIFIED` with linkage true,
  checkpoint trust false and chain verification false. Signet challenge,
  difficulty schedule, accumulated work and checkpoint provenance remain
  deliberately unimplemented. `native-signet-checkpoint-review.v1` now binds
  the exact Signet checkpoint to two distinct sorted source digests, two
  distinct sorted opaque reviewer IDs and review time. This validates only the
  structural integrity of review claims: source/reviewer authenticity is not
  proven, so `independent_review_claims_bound=true` still leaves checkpoint and
  chain trust false. The explicit capability is
  `HEADER_LINKAGE_ONLY_NO_SIGNET_CHALLENGE_OR_DIFFICULTY`. Next slice: design an
  offline threshold-signature checkpoint approval allowlist; do not embed real
  trust keys or approve a checkpoint without a separately authorized key
  ceremony and independent source verification. The offline
  `native-signet-checkpoint-approval-proposal.v1` now freezes a strict 2-of-3
  shape: three sorted opaque signer IDs, two distinct signature-byte digests,
  exact review-artifact binding and at most ten-minute expiry. It validates
  proposal content only; `approval_signatures_verified=false`, checkpoint trust
  and chain trust remain false. Next slice: freeze trust-key ceremony,
  rotation/revocation and algorithm-selection contracts before any real keys or
  verifier dependency are introduced. The initial
  `native-checkpoint-trust-key-ceremony.v1` now binds epoch one to three sorted
  key slots/key-material commitments, three distinct participants and two
  transcript digests; approval signers must exactly equal the ceremony slots.
  Algorithm remains `UNDECIDED`, predecessor/revocation fields are empty and
  keys/algorithm installation flags remain false. Next slice: epoch-two rotation
  and emergency-revocation proposals bound to the predecessor ceremony digest.
  Those lifecycle contracts now exist separately from preview: rotation requires
  epoch 1→2, three wholly new slots/commitments, disjoint participants, two
  transcripts and activation within 24 hours; emergency revocation accepts only
  predecessor slots, bounded reasons, two observers/evidence digests and a
  ten-minute expiry. UniFFI exposes the pure review, while execution, key change
  and algorithm selection remain false. Next slice: freeze an algorithm-
  selection ADR/contract with dependency provenance and test vectors before any
  real key bytes, installation or lifecycle execution.

- 2026-08-12 the read-only E5 readiness proof is frozen.
  `native-wallet-e5-readiness-proof.v1` derives seven foundation checks by
  canonically validating the full E5 contract/synthetic-rehearsal chain and
  accepts exactly eight independent operational booleans: reviewed mobile
  stack and formal recovery protocol, reproducible-build provenance, real
  platform attestation, on-device hardware backing, backup/restore E2E,
  recovery abuse/fault tests and explicit owner production-release approval.
  The truthful current set leaves all eight false, yielding
  `DESIGN_AND_SYNTHETIC_FOUNDATION_COMPLETE/NO_GO`. Even synthetic all-true
  permits only native-implementation review; selected stack/network remain
  `UNDECIDED`, and production release, recovery execution, authority install,
  signing, runtime enable and action remain false. The complete E5 suite passes
  142 tests; compilation and `git diff --check` pass. No probe, runner, SDK,
  key/share, endpoint, service or production state changed. Further real E5
  work requires an explicit technology-selection task; do not choose a mobile
  or cryptographic stack or fabricate operational evidence implicitly.

- 2026-08-12 the E5 synthetic recovery-rehearsal result boundary is frozen.
  `native-wallet-recovery-rehearsal-consumption.v1`, observation and result
  contracts bind one in-window invocation to the exact authorization nonce,
  disposable target and mobile build. Ten ordered observations cover target
  isolation/teardown, build match, exactly-once consumption, synthetic-only
  wallet/key use, no production network/broadcast and no authority/revocation
  effect. The result also requires a consumed-ID ledger snapshot containing the
  authorization ID exactly once; missing, duplicate, time-invalid or drifted
  evidence fails closed. The final attestor must differ from runner/observers.
  Complete evidence yields only `PASS/isolatedRehearsalPassed`; on-device
  security, production readiness, recovery, authority install, revocation,
  signing and action remain false. The complete E5 suite passes 128 tests;
  compilation and `git diff --check` pass. No runner, I/O, SDK, key/share,
  endpoint, service or production state changed. Next safe E5 slice: a
  read-only readiness proof combining all E5 design contracts and this
  synthetic result, remaining `NO_GO` until a selected reviewed mobile stack,
  reproducible-build provenance, real platform-attestation verification,
  on-device backup/restore tests and explicit owner approval exist.

- 2026-08-12 the E5 completion-review and isolated-rehearsal authorization
  boundary is frozen. `native-wallet-recovery-completion-review.v1` binds the
  canonical proposal to eight ordered checks and emits only
  `REHEARSAL_REVIEW_READY` or explicit `NO_GO`; the reviewer must differ from
  both devices and both evidence verifiers, and review must remain inside the
  attempt lifetime. `native-wallet-recovery-rehearsal-authorization.v1` binds
  one current positive review to exact disposable-target, mobile-build and
  nonce digests for at most ten minutes and one invocation; validation rejects
  an ID already present in the supplied consumed-ID snapshot. Production
  network/wallet/credentials, real keys, authority installation, old-device
  revocation, broadcast, retry, signing and action remain false with
  `executionEffect=NONE`. The complete E5 suite passes 112 tests; compilation
  and `git diff --check` pass. No I/O, SDK, key/share, endpoint, service or
  production state changed. Next safe E5 slice: a pure rehearsal
  result/attestation contract binding this authorization to synthetic observed
  steps and reporting PASS/FAIL without claiming on-device security.

- 2026-08-12 the E5 offline recovery-completion proposal is frozen.
  `native-wallet-recovery-completion-proposal.v1` accepts only an exact
  `ELIGIBLE_OFFLINE` attempt plus fresh, content-hashed new-device and
  prior-device-revocation evidence. Both records bind the same wallet, attempt,
  target device and exactly-next epoch; their verifier identities must differ
  from each other and from both device identities. Output is limited to
  `COMPLETION_REVIEW_READY_OFFLINE`: recovery, revocation, authority install,
  signing, production permission and action remain false. The complete E5 suite
  passes 97 tests; compilation and `git diff --check` pass. No SDK, key/share,
  storage, network, endpoint, service or production state changed. Next safe E5
  slice: a pure completion-review decision and single-use authorization envelope
  limited to a future isolated mobile rehearsal, still unable to install
  authority or enable production recovery.

- 2026-08-12 E5 has a pure, design-only native-wallet key and consent boundary.
  `native-wallet-key-boundary.v1` separates the user-device app,
  hardware-backed non-exportable keystore, locally authorized signing bridge
  and remote server; the server cannot receive key/recovery/authenticator
  material or authorize a signature alone. `native-signing-display-request.v1`
  binds one synthetic unsigned-payload SHA-256 to the exact visible network,
  destination, canonical amount and fee for at most two minutes.
  `native-signing-consent-receipt.v1` requires a distinct second interaction,
  at least 750 ms deliberation and exact unexpired request/display binding;
  interaction IDs are stored only as hashes. It is explicitly not authenticator
  evidence: signature, signing permission, production network/action and
  execution remain false. Thirty-eight E5/E4/Wallet/portfolio/landmine tests
  pass; compilation and scoped diff checks pass. No mobile code, SDK, key
  material, endpoint, runtime, service or production state changed. Next safe
  E5 slice: a pure hardware-backed local-authenticator evidence contract with
  freshness, anti-replay and device-key identity binding to the exact consent,
  still emitting no transaction signature. Recovery and a formal E5 threat
  model remain separate prerequisites; the threat model requires an explicit
  owner request before selecting a real mobile crypto stack.

- 2026-08-11 E4 rehearsal-runner authorization is frozen without creating a
  real approval. `e4-rehearsal-runner-precondition-evidence.v1` binds each of
  eight checks to the exact plan, opaque disposable target reference/fingerprint
  and encrypted snapshot digest; evidence is secret/connection-free, at most ten
  minutes old with one-second future skew. A separate owner approval binds the
  same tuple for at most fifteen minutes and one invocation while forbidding
  production DB/network contact, credentials, proposal application, persistence,
  retry, promotion and money action. The authorization receipt requires one
  unique current PASS for every check plus that exact current approval; content
  hashing and output validation prevent eligibility/scope/effect tamper. Complete
  synthetic inputs yield only `ELIGIBLE` for the frozen isolated rehearsal and
  still have `executionEffect=NONE`. Eighty-one E4, Wallet, DB-boundary and
  landmine tests pass; compilation and root/nested diff checks pass. No real
  approval, snapshot, target, DB connection, command, service, migration, route
  or production state changed. Operational execution remains blocked until the
  owner separately names and approves an exact disposable target and snapshot
  digest. Continue another safe E0-E5 offline slice meanwhile.

- 2026-08-11 the E4 disposable full-snapshot rehearsal runner design is frozen
  and non-executing. `e4-full-snapshot-rehearsal-runner-plan.v1` binds the exact
  evidence-manifest digest, one isolated disposable PostgreSQL invocation and a
  pre-existing encrypted immutable snapshot copy. Eight preconditions require
  separate owner approval, target identity/absence, no production route or
  credentials, verified snapshot/manifest digests and teardown target. Only
  disposable target creation/snapshot load are bounded fixture mutations;
  post-load write capability is revoked before read-only snapshot/table/ACL/
  route/gate/migration measurements. Applying `025`, retries, persistence,
  production contact and promotion/action are forbidden. Mandatory teardown
  destroys target and staged snapshot and ends with absence verification.
  Seventy-three E4, Wallet, DB-boundary and landmine tests pass; compilation and
  root/nested diff checks pass. No snapshot, target, DB connection, command,
  migration, service, route or production state changed. Next safe slice:
  target-bound precondition evidence plus a short-lived single-invocation owner
  approval/authorization receipt. General continuation is not that approval.

- 2026-08-11 the next E4 promotion-evidence boundary is frozen and remains
  offline. `e4-full-snapshot-rehearsal-manifest.v1` content-binds the dormant
  `025` migration/ACL proposals and rollback runbook, fixes the target class to
  disposable isolated PostgreSQL, and forbids production networking,
  credentials and writes. The pure `e4-rehearsal-evidence-collection.v1`
  normalizer accepts only strict secret-free measurements, records exact
  snapshot/table/ACL/target digests without accepting a DSN, and rejects
  artifact drift. Production contact, a write, connection material, a
  non-isolated target, non-false E4 gates, a present confirm route or active
  migration all emit NO-GO. Complete synthetic evidence yields only
  `PROMOTION_REVIEW_READY_OFFLINE`; no rehearsal/database probe, migration,
  route, flag or production state changed. Fifty-seven E4, Wallet, DB-boundary
  and landmine tests pass; compilation and root/nested diff checks pass. Next
  safe slice: design a separately authorized disposable rehearsal runner that
  loads a fresh snapshot, performs read-only post-load measurement and proves
  teardown. Do not point it at production or promote/apply `025`.

- 2026-08-11 the E4 promotion preflight contract is frozen but remains offline.
  `e4-promotion-preflight.v1` content-binds fresh (at most 24-hour) snapshot,
  table/ACL inventory, rollback-plan and exact proposal digests. Ten independent
  checks require the full rehearsal/inventories/rollback boundary, both E4 gates
  explicitly false, route and active migration absent, and both proposal files
  present. Complete synthetic evidence yields only
  `PROMOTION_REVIEW_READY_OFFLINE`; migration promotion/application, ACL
  application, route connection, feature-gate mutation and money action remain
  false with no execution effect. Every missing check plus stale/future evidence
  and document tamper fails closed. All 102 E4, Wallet, DB-boundary, landmine and
  route tests pass; compilation/diff checks pass; runtime inventory still shows
  no active `025`, E4 flag or confirm route. No production evidence, service or
  DB state changed. Next E4 slice: a read-only evidence collector and frozen
  manifest for an isolated full-snapshot PostgreSQL rehearsal, with exact
  proposal/table/ACL/rollback digests and connection-material redaction. It must
  emit NO-GO unless route/gates remain absent/false; do not promote/apply yet.
  E2, real E3 rehearsal and E5 remain open.

- 2026-08-11 atomic E4 reservation→BUY/SELL order handoff is implemented and
  remains test-only. Review exposed and fixed two missing bindings before SQL:
  every server-check evidence/assessment now carries the same positive internal
  actor user ID (preventing principal/order IDOR), and the draft now embeds
  canonical preview amounts plus quote expiry. The combined store revalidates
  exact draft/assessment/reservation, actor, amounts and raw-destination
  fingerprint before opening a transaction; then it inserts reservation,
  creates one canonical pending `orders` BUY or `sell_orders` SELL row, records
  immutable result kind/id and commits once. Exact retry returns the same order;
  incomplete/drifting reservation conflicts. SQLite parallel handoff produced
  one order/one replay, while faults after order INSERT and before commit rolled
  back both tables. A disposable PostgreSQL 17 loopback-only/no-volume fixture
  passed parallel BUY, exact BUY/SELL replay and injected post-order rollback,
  then was stopped/auto-removed. Sixty-one E4/Wallet/DB-boundary/landmine tests
  pass; compilation and root/nested diff checks pass. No production migration,
  route, flag, runtime import, service or DB state changed. Next safe E4 slice:
  a test-only invocation adapter that revalidates the complete preview→ack→draft
  →assessment→reservation chain, calls this store and returns only bounded result
  metadata without raw destination/payout details. Keep HTTP/UI and production
  persistence disconnected until adapter authorization/fault tests pass. E2,
  real E3 rehearsal and E5 remain open.

- 2026-08-11 E4 exact-draft idempotency reservation is implemented and remains
  dormant. The confirmation draft now content-binds quote expiry; reservation
  lifetime is at most five minutes and never exceeds that quote. The immutable
  request binds exact draft/assessment, principal, hashed idempotency key,
  workflow mapping and payload hash with no raw destination/secret.
  SQLite/PostgreSQL stores uniquely reserve both `draft_id` and
  `(principal_ref,idempotency_key_sha256)`: exact retry replays the same row;
  assessment/payload/workflow/expiry drift conflicts, and expiry never frees the
  key for silent reuse. SQLite `BEGIN IMMEDIATE` concurrency produced one
  insert/one replay; injected post-insert failure rolled back fully. A disposable
  PostgreSQL 17 loopback-only/no-volume fixture passed parallel single-winner,
  exact retry and drift conflict, then was stopped/auto-removed. Fifty-four E4,
  Wallet, DB-boundary and landmine tests pass; compilation and root/nested diff
  checks pass. The schema remains test-only: no production migration, flag,
  route, runtime import, workflow invocation or DB state changed. Next E4
  boundary must atomically bind a reservation to its resulting buy/sell order
  (or terminal explicit failure); never implement `reserve` followed by an
  unrelated workflow call, which could strand or duplicate money actions.
  Require concurrency and fault rollback around the combined handoff before any
  HTTP/UI wiring. E2, real E3 rehearsal and E5 remain open.

- 2026-08-11 the dormant E4 private server-authorization adapter is frozen.
  `private-action-server-check-evidence.v1` binds one result to the exact draft
  and server-derived principal for each of six checks: authentication, quote
  freshness, destination validity, principal authorization for the destination,
  provider availability and risk policy. Evidence contains no raw destination/
  secret and is bounded to 30 seconds plus 1-second future skew.
  `private-action-server-assessment.v1` requires one unique fresh PASS for every
  check and maps BUY/SELL only to the names of existing order-creation workflows.
  Positive output is still offline: route disconnected, unpersisted and unable
  to create a money intent/action. Stale/future/mixed-principal/duplicate/failure
  cases fail closed. All 49 E4, Wallet mode and unified portfolio/UI tests pass;
  compilation and diff checks pass. No route, DB, service, UI runtime or money
  state changed. Next E4 boundary is a real repository-level idempotency
  reservation for exact draft+assessment with concurrency and rollback/fault
  contracts. Do not wire HTTP/UI or invoke the existing money workflows until
  reservation and authorization are atomic. E2, real E3 rehearsal and E5 remain
  open roadmap work.

- 2026-08-11 E4 unified money-action UX foundation has started while real E3
  rehearsal remains separately approval-blocked. `wallet-action-preview.v1`
  content-binds private/external-CEX lane, BUY/SELL, executor, custody before/
  during/after, KYC responsibility, canonical spend/receive amounts, every fee
  plus derived total, bounded quote lifetime, risks and irreversibility. The
  external-CEX lane remains PLANNED and every preview is non-confirming.
  `wallet-action-acknowledgement-challenge/receipt.v1` requires five ordered
  acknowledgements, at least 750 ms deliberation and a distinct second
  interaction before quote/challenge expiry; planned CEX cannot be acknowledged
  into availability. `wallet-action-confirmation-draft.v1` then binds only an
  eligible private receipt, hashed idempotency key and minimized wallet/bank
  destination fingerprint. It accepts no raw address/bank detail and remains
  DRAFT_ONLY, unpersisted, unauthenticated and non-executing. Forty relevant E4,
  wallet-mode and unified-portfolio/UI tests pass; compilation and diff checks
  pass. No route, database, service, UI runtime, money intent or production state
  changed. Next safe E4 slice: a dormant server adapter contract that maps only
  a validated private draft toward the existing workflow after independent
  authentication, quote freshness, destination validation/ownership and provider
  availability checks; do not wire a route or persistence until its authorization
  and fault contracts pass. E2, real E3 rehearsal and E5 remain open.

- 2026-08-11 the verifier operational rehearsal design and bounded authorization
  contracts are frozen without execution. `independent-verifier-rehearsal-plan.v1`
  permits only a disposable isolated non-production host, requires explicit
  owner approval, no production data/credentials/network, verified manifest and
  rollback target, and fixes eleven non-retrying steps ending in complete
  removal and absence verification. It has no command/execution surface.
  Content-addressed precondition evidence and a separate exact plan/target owner
  approval (maximum 15 minutes, one invocation) feed
  `verifier-rehearsal-authorization-receipt.v1`; every one of six checks must be
  unique PASS and current. Even `ELIGIBLE` forbids production, credentials,
  network, persistence and readiness and does not execute anything. All 294 E3
  tests and 7 runtime-isolation tests pass; compilation and root/nested diff
  checks pass. No real approval/receipt/target exists and no host/service/state
  changed. Execution is now intentionally blocked until the owner separately
  identifies and approves one disposable isolated target; do not reinterpret a
  general continuation as that approval. Continue other safe E0–E5 design work
  meanwhile; E2 independent storage, E4 UX and E5 native-wallet gates remain
  open.

- 2026-08-11 independent artifact measurement, result attestation and the full
  offline verifier acceptance chain are frozen. The pure artifact contract
  compares an independently supplied content-addressed measurement against the
  manifest and emits only SERVICE_IDENTITY, LEAST_PRIVILEGE, SECRET_ABSENCE and
  ARTIFACT_PROVENANCE observations. Even a perfect artifact remains deployment
  NO_GO with `RESULT_FRESHNESS_MISSING`. The result-attestation contract emits
  that fifth observation only for the exact validated result digest and same
  deployment identity; capability-blocked evidence may be fresh but still fails
  capability binding. `independent-verifier-acceptance-bundle.v1` jointly
  revalidates manifest, measurement, artifact acceptance, request, result,
  attestation, deployment acceptance and binding. A complete chain is only
  `EVIDENCE_CHAIN_VALIDATED_OFFLINE`; production proof, readiness, runtime and
  actions remain false. All 277 E3 tests and 7 runtime-isolation tests pass;
  compilation and root/nested diff checks pass. No real measurement, install,
  user, directory, invocation, service, network, secret, persistence or flag
  change occurred. Next is an operational acceptance design for a separately
  authorized real deployment rehearsal. Do not install or invoke the verifier
  without explicit owner approval; ordinary continuation does not fabricate
  host evidence or satisfy the readiness probe. E2 independent storage, E4 UX
  and E5 native-wallet gates remain open.

- 2026-08-11 the independent verifier now has a deployable but deliberately
  inactive artifact specification. The bounded offline CLI consumes exactly one
  existing secret-free evidence bundle, invokes the hermetic adapter once and
  emits deterministic JSON; malformed/oversized input is bounded NO_GO without
  echo. It has no network/provider SDK/environment-secret/action surface. The
  systemd oneshot template uses a dedicated `kairos-verifier` identity, private
  network, AF_UNIX only, empty capabilities, strict filesystem/home/device/
  kernel sandbox, no environment file or writable path, and intentionally no
  `WantedBy`. A manifest content-binds the exact CLI and unit SHA-256 while
  setting installation/runtime authorization false. Systemd verification has
  no warning for this unit; 251 E3 tests and 7 runtime-isolation tests pass,
  compilation and root/nested diff checks pass. Nothing was installed, no user/
  directory/input was created, and no service/config/network/secret/persistence/
  flag state changed. Next safe E3 slice: a pure artifact-acceptance contract
  that transforms independently measured file digests, service identity and
  sandbox evidence into deployment observations without treating repository
  templates as proof of production deployment. E2 independent storage, E4 UX
  and E5 native-wallet gates remain open roadmap work.

- 2026-08-11 independent verifier/result binding and readiness integration are
  frozen. `independent-verifier-capability-binding.v1` jointly validates one
  accepted deployment, exact verifier request and exact capability result. The
  deployment/request assessment time must match, and the deployment's
  `RESULT_FRESHNESS` SHA-256 must bind the validated result. Deployment failure,
  digest drift or non-verified capabilities are NO_GO. Positive evidence is
  only `BOUND_OFFLINE`; restricted-testnet readiness/runtime/actions stay false.
  `e3-readiness-proof.v2` now has six offline and nine operational checks, with
  `INDEPENDENT_VERIFIER_BINDING_ACCEPTED` independently required and currently
  false. All 245 E3 tests and 7 runtime-isolation tests pass; compilation and
  root/nested diff checks pass. No runtime, service, config, network, secret,
  persistence or feature flag changed. Next safe E3 step is a deployable but
  inactive independent-verifier artifact/service specification whose identity,
  least privilege, secret absence and immutable provenance can be assessed
  without fabricating real deployment evidence. Keep E2's independent-storage
  gate unresolved, and retain E4 unified UX plus E5 native non-custodial wallet
  as explicit roadmap work rather than treating E3 progress as product finish.

- 2026-08-11 the pure independent-verifier deployment acceptance contract is
  frozen. `independent-verifier-deployment-observation.v1` covers exactly five
  secret-free content-addressed evidence classes: service identity, least
  privilege, secret absence, immutable artifact provenance and result
  freshness. Evidence shares one opaque deployment identity, permits no active
  probe and is bounded to 15 minutes plus 1-second future skew.
  `independent-verifier-deployment-acceptance.v1` requires one fresh PASS for
  every class; missing, duplicated, mixed, stale/future, failed, unavailable or
  tampered evidence fails closed. Perfect evidence yields only
  `ACCEPTED_OFFLINE`: readiness, runtime enablement and actions stay false. All
  235 E3 tests and 7 runtime-isolation tests pass; compilation and both diff
  checks pass. No service was installed/started/configured and no runtime,
  network, secret, persistence or flag state changed. Next safe slice: a pure
  binding between accepted independent-deployment evidence and one validated
  capability-verifier result, preserving identity/freshness while restricted-
  testnet readiness remains false.

- 2026-08-11 the hermetic restricted-testnet capability verifier adapter is
  frozen. `testnet-capability-verifier-request.v1` requests only the three
  existing secret-free observation types, fixed to `TESTNET/SPOT_PAPER`,
  `FETCH_EXISTING_EVIDENCE` and `activeProbeAllowed:false`. The injected source
  adapter contains no network, SDK, secret, clock or active withdrawal/transfer
  action. `testnet-capability-verifier-result.v1` embeds a fully validated
  assessment; permissive evidence becomes `CAPABILITY_BLOCKED`, while timeout,
  source error and malformed/secret-bearing responses become NO_GO without
  exception text. Exact replay returns prior validated evidence without calling
  the source. Even `VERIFIED_OFFLINE` fixes independent deployment and readiness
  false. All 221 E3 tests and 2 runtime-isolation tests pass; compilation and
  both diff checks pass. No observation, runtime, network, config, persistence,
  flag or service state changed. Next safe slice: pure independent-verifier
  deployment acceptance evidence for identity, least privilege, secret absence,
  artifact provenance and freshness; do not install or start a service.

- 2026-08-11 the pure secret-free restricted testnet capability contract is
  frozen. `testnet-capability-observation.v1` records one permission inventory
  or withdrawal/transfer denial for `TESTNET/SPOT_PAPER`, bounded to 15 minutes
  plus 1-second future skew, with only a lowercase evidence SHA-256 and no key
  or credential identifier. `restricted-testnet-account-evidence.v1` requires
  exactly one inventory and both denials for the same provider/account; it
  requires market/balance reads and spot create/cancel, forbids margin,
  derivatives, withdrawal and all transfer grants, and requires explicit
  denial of forbidden scopes/actions. Missing, mixed, stale/future, unavailable
  or permissive evidence is NO_GO or invalid. Perfect evidence is only
  `OFFLINE_ELIGIBLE`: `runtimeVerified` and `readinessCheckSatisfied` remain
  false. All 208 E3 tests and 2 runtime-isolation tests pass; compilation and
  both diff checks pass. No observation was performed and no runtime, secret,
  network, config, persistence, flag or service changed. Next safe slice: a
  hermetic capability-verifier request/response adapter with injected evidence
  source, no actions/secrets, and fail-closed timeout/malformed semantics.

- 2026-08-11 isolated append-only PostgreSQL rehearsal for E3 engine evidence
  is complete. `paper-engine-evidence-bundle.v1` jointly validates canonical
  READY intent, submission, attempt, optional receipt/resolution and optional
  filled intent/projection. It explicitly supports received, unresolved UNKNOWN,
  manual UNKNOWN and recovered-receipt shapes while rejecting partial fills,
  smuggled receipts and ineligible fill evidence. Sequence and previous bundle
  hash are content-bound. Dormant `024_e3_paper_evidence.sql` and the repository
  now accept `ENGINE_EVIDENCE`; the repository requires bundle continuity to
  equal the database argument before connecting. A disposable PostgreSQL 17
  container with no port/volume verified first append, exact retry/no-op, next
  append, gap/drift/mutation rejection and the correct head, then was removed.
  All 195 E3 tests and 2 runtime-isolation tests pass; compilation and both diff
  checks pass. Production PostgreSQL was neither queried nor migrated, and no
  runtime/config/service state changed; `PRODUCTION_PERSISTENCE_READY` and
  `ENGINE_ADAPTER_READY` remain false. Next safe slice: pure secret-free
  restricted-testnet-account capability evidence with explicit withdrawal and
  transfer denial, without changing readiness until runtime verification exists.

- 2026-08-11 the pure E3 UNKNOWN-attempt resolution contract is frozen.
  `paper-engine-attempt-resolution.v1` accepts only a validated immutable
  `UNKNOWN` attempt and exactly one branch: an independently recovered exact
  receipt or bounded manual disposition (`AMBIGUOUS`, `ENGINE_UNAVAILABLE`,
  `NOT_FOUND`, `OPERATOR_ESCALATED`). Resolution binds lowercase SHA-256
  evidence, cannot predate the attempt, never rewrites it and always keeps
  retry/automatic resubmit false. Only a recovered accepted receipt is fill
  eligible; recovered rejection and every manual outcome are not. The
  UNKNOWN-specific fill entry point revalidates resolution and receipt; exact
  replay is unchanged and drift fails closed. All 181 E3 tests and 2 runtime
  isolation tests pass; compilation and both repository diff checks pass. No
  runtime query, persistence, endpoint, SDK, credential, network, flag or
  service state changed; readiness remains false. Next safe slice: isolated
  append-only PostgreSQL rehearsal for submission/receipt/attempt/resolution/
  fill-projection evidence, leaving production and readiness unchanged.

- 2026-08-11 immutable one-shot E3 engine-attempt semantics are frozen.
  `paper-engine-attempt.v1` records a valid response as terminal `RECEIVED`
  bound to its exact receipt; timeout, transport failure or malformed response
  becomes terminal `UNKNOWN/manualReviewRequired` without retaining exception
  text or inventing a rejection. Every attempt fixes `retryAllowed:false` and
  `automaticResubmitAllowed:false`, so uncertain outcomes cannot enter the
  receipt-gated fill path or be automatically submitted again. Exact replay
  revalidates and returns prior evidence without calling transport; drift fails
  before transport. Explicit times bind a received receipt inside the attempt
  interval. All 164 E3 tests and 2 runtime-isolation tests pass; compilation and
  both repository diff checks pass. No runtime, persistence, endpoint, SDK,
  credential, network, flag or service state changed; `ENGINE_ADAPTER_READY`
  remains false. Next safe slice: a pure resolution contract for `UNKNOWN`
  attempts accepting only an independently recovered exact receipt or bounded
  manual disposition, never rewriting the attempt or authorizing resubmit.

- 2026-08-11 the receipt-gated E3 engine fill projection is frozen.
  `paper-engine-fill-projection.v1` permits the engine path `READY → FILLED`
  only with the exact validated `ACCEPTED/NONE` receipt for the canonical
  submission of that ready-state. Time is monotonic (`READY ≤ receipt ≤
  FILLED`), the receipt ID is hash-chain evidence in the fill event, and the
  projection content-binds ready/filled state plus expected ledger hash.
  Rejected, cross-state, future and tampered receipts fail closed; the existing
  ledger reconciliation remains unchanged. All 155 E3 tests and 2 runtime
  isolation tests pass; compilation and both root/nested-repository diff checks
  pass. No runtime, persistence, endpoint, SDK, credential, network, flag or
  service state changed; `ENGINE_ADAPTER_READY` remains false. Next safe slice:
  freeze timeout/unknown-outcome and exact-retry semantics so uncertain submit
  is never filled or automatically resubmitted.

- 2026-08-11 the hermetic E3 paper-engine adapter boundary is frozen.
  `paper-engine-submission.v1` accepts only a validated `READY` intent and
  content-binds state/account/ledger/snapshot/policy/trade/idempotency fields.
  `paper-engine-receipt.v1` binds the exact submission and permits only explicit
  accepted or bounded rejected outcomes. The injected transport is treated as
  untrusted: extra fields, binding/mode drift, malformed identifiers and time,
  and inconsistent outcome/reason pairs fail closed. The adapter imports no
  CEX SDK, network or runtime configuration and mutates no intent/ledger. All
  artifacts remain `PAPER_SIMULATION`, `executionEffect:NONE` and
  `actionAllowed:false`; `ENGINE_ADAPTER_READY` remains false. All 151 E3 tests
  and the runtime-isolation regression pass; compilation and diff checks pass.
  Next safe slice: require an exact accepted receipt for a pure
  `READY → FILLED` projection while preserving reconciliation, with no runtime
  transport, persistence migration, credential, SDK, network or service change.

- 2026-08-11 owner explicitly deferred the E2 independent-backup prerequisite
  so other roadmap work can continue. Keep it as a mandatory unresolved gate:
  production has only `/dev/sda1`, readiness is `NO_GO` with the four runtime
  flags disabled plus `INDEPENDENT_BACKUP_UNAVAILABLE`. Do not fabricate
  evidence or enable E2 transport; return after two genuinely independent
  writable storage paths are supplied.
- 2026-08-11 E3 keyless/offline work began with frozen
  `market-depth-snapshot.v1` and pure `slippage-estimate.v1`. The Decimal-based
  contracts strictly validate bounded sorted non-crossed depth, content-address
  snapshots, walk BUY/SELL liquidity, apply explicit fee bps and report
  midpoint slippage. Insufficient depth and malformed/tampered data fail
  closed. Every result remains projection-only/non-executing; no endpoint,
  credential, network, persistence, flag or runtime integration was added.
  50 focused E1/E2/isolation/E3 tests pass plus P0, compilation and diff checks.
  Next safe slice: freeze offline freshness, source-quality and multi-source
  comparison rules over validated snapshots without wiring runtime execution.

- 2026-08-09 user-approved cutover prioritization: payout balances are
  intentionally empty and referral bonuses have never accrued, so do not spend
  additional migration cycles preserving hypothetical payout/referral race
  behavior. These paths may fail closed during the PostgreSQL transition. The
  non-negotiable data invariants are per-user successful completed-order counts
  and exact VIP progression. Current production baseline: 76 successful
  (`sent`/`completed`) orders across 41 users; `user_vip_volume` has 8 users and
  totals 41,382.83 RUB; `referral_bonuses` has 0 rows/0 value. Preserve and
  reconcile both the order-derived per-user counts and the VIP table exactly;
  do not recompute VIP from orders during cutover.
- 2026-08-09: `reconcile_snapshot.py --critical-invariants` now makes those
  priorities executable: per-user `sent`/`completed` counts and exact
  `user_vip_volume` user/amount rows are blocking, while referral zero-state
  and `paid`/`pending` counts are reported but non-blocking. Static preflight
  requires the flag in the runbook. PostgreSQL intentional-drift, preflight,
  legacy snapshot reconciliation, compilation and diff checks pass. This slice
  was not deployed and no PostgreSQL production flag was enabled.

1. Credential rotation is resumed. Inline systemd copies are removed. Reissue
   the exposed callback-handler Telegram token and provider credentials in
   their external consoles, update only `/etc/obsidian-exchange/*.env` (`0600`),
   restart/verify one consumer at a time, then remove obsolete `.env` copies.
2. Succeeded reconciliation, outbox, review administration, runtime relocation,
   isolated worker installation and bot signer removal are deployed. The worker
   is enabled for normal BTC/LTC consumption; the user explicitly chose to skip
   the on-chain canary. Monitor the first real intent through `pending →
   processing → succeeded → sent` and outbox delivery, treating any
   `processing/review` as manual reconciliation rather than retry. Monitor
   `obsidian-payout-worker.service` and `notification_outbox`; do not confuse
   the retired `exchange-payout.service` with the live worker or re-enable
   either legacy payout unit.
3. Have the sole Laravel admin complete TOTP enrollment on next login. Action
   audit, TOTP replay, forged-session, state-forgery, mass-assignment and the
   complete Filament resource permission matrix are covered and deployed.
4. Scan the worktree and Git history more deeply without exposing values,
   rotate credentials present in old dumps/backups, centralize runtime secrets
   and redact logs. Initial local file permissions and ignore rules are fixed.
5. Introduce formal state transitions, idempotency, evidence/outbox and a
   separate payout worker/signer before database migration.
6. Make admin/payment code tracked and reproducible; lock dependencies, add
   dependency/secret/SAST scans and E2E payment-state tests.
7. Continue PostgreSQL preparation. All identified operational writers now
   have SQLite/PostgreSQL repository contracts, including provider health and
   its rolling attempt journal (deployed 2026-08-09; SQLite and PostgreSQL
   contracts passed, relay and bot healthy with zero restarts). Read-only
   reporting/admin aggregates are also contracted and deployed: conversion,
   evidence, public statistics, reserves and admin totals passed SQLite and
   PostgreSQL 17 parity tests; the public endpoints respond successfully and
   relay has zero restarts/errors. Canonical PostgreSQL `orders` schema is now
   defined in `019_orders.sql` and passed PostgreSQL 17 create/dedup contracts.
   A read-only snapshot reconciler compares row counts and transformation-aware
   canonical SHA-256 values and detects intentional data drift in its PG test.
   Full PostgreSQL 17 rehearsal completed 2026-08-09: all migrations applied,
   a consistent production SQLite snapshot loaded, and all migrated tables
   matched counts and hashes. Rehearsal exposed and fixed nullable
   legacy staff attribution, nine old receipts without SHA-256, and float to
   NUMERIC precision handling. Temporary production snapshot was deleted and
   the container stopped. A follow-up inventory found ten omitted tables; the
   compatible `020_legacy_runtime.sql` now covers them and the expanded full
   rehearsal matches 49/49 tables by count and hash. Eight remain active through
   bot/relay paths (admin/reviews/rates/referrals/VIP/address notes/shadow data),
   while `risk_events` and the physical legacy payout queue are read by admin or
   monitoring; empty `worker_ids` is superseded by `workers` and should be
   retired after cutover. Next move these remaining active accesses behind
   PostgreSQL-capable repositories, then write the cutover/rollback runbook.
   PostgreSQL feature flags remain off; do not cut production over yet.
   The first residual-access block is complete and deployed: staff audit,
   reviews, VIP volume, referral-bonus reporting and rate subscriptions now use
   `engagement_store.py`, separately gated by `ENGAGEMENT_POSTGRES_ENABLED`.
   SQLite/PostgreSQL contracts and route/P0/promise/boundary regressions pass;
   bot and notifier are active with zero restarts/errors and existing 52
   reviews, 4 subscriptions and 8 VIP rows were preserved. The next residual
   block is also complete: `client_address_notes` and `payout_shadow` have
   PostgreSQL-capable repositories, are deployed on SQLite, and the repeated
   rehearsal matches 49/49 tables. Physical legacy `payout_queue` monitoring
   and `risk_events` access now also have PostgreSQL-compatible boundaries and
   are deployed on SQLite. The cutover/rollback runbook and automatic preflight
   are written, deployed and rehearsal-tested, but the guard correctly reports
   `NO-GO`; monitor/notifier repository work reduced the active SQLite-only
   runtime modules from 21 to 19; receipt/payout-safety cleanup reduced them
   again to 15, the operational-read block reduced them to 11, and RSPay's
   residual read reduced them to 10. The 2026-08-09 residual repository pass
   reduced the legacy wrapper guard to 2. The stronger AST guard initially
   found 266 authoritative-DB findings in two adapters plus three payout core
   modules. The payout core modules are now SQL-free and deployed. The
   2026-08-09 workflow/lifecycle/read/reporting/settlement/reminder deployments
   reduced the current deployed guard to 93 findings only in
   `bot/main_bot.py` (82) and `relay-fastapi/main.py` (11). Continue these two
   god-files by bounded
   transaction/route groups. Do not replace them with a generic
   PostgreSQL connection shim. Require repository contracts,
   concurrency/fault regressions and a fresh full snapshot rehearsal before the
   guard may report `GO`. Production PostgreSQL flags remain off.

- A shared read-only buy-order boundary now exists in
  `repositories/order_read_store.py`, gated by `ORDER_READ_POSTGRES_ENABLED`.
  FastAPI customer/dashboard history, the initial `/api/order` snapshot and
  `/api/admin/orders` use it; authorization, receipt/session composition and
  payment polling/transitions remain unchanged. SQLite and PostgreSQL 17
  contracts, routes 90/90, P0, landmines and gate inventory pass.
- The payout intent, referral intent and reconciliation core modules are now
  SQL-free compatibility facades. SQLite and PostgreSQL implementations fully
  own immutable intent creation, worker claim/result, referral reservation,
  admin confirm/requeue audit, order/referral reconciliation, VIP/referral
  ledgers and notification outbox. Bot order/referral review and withdrawal
  paths use `payout_store`; exact trusted-chain discovery and signer-ledger
  absence guards are preserved. Reconciliation fault injection proves a final
  outbox failure rolls back order status, VIP and ledger changes. FastAPI also
  moved safe payment-session reads to its repository; bot support/promo reads
  are repository-backed. This bundle was deployed on SQLite on 2026-08-09;
  bot, relay and payout worker are active with zero restarts/warnings, SQLite
  is `ok`, money/outbox queues are empty, and loopback/public API checks pass.
  The stronger deployed preflight remains correctly `NO-GO` with 194 findings
  only in the two adapters. No PostgreSQL production flag was enabled.
- A buy-order workflow boundary is deployed in
  `repositories/order_workflow_store.py`, gated by
  `ORDER_WORKFLOW_POSTGRES_ENABLED`. It provides fixed CAS operations for
  owner cancellation, review reopen/reject, validated paid-to-sent closure,
  verification request/clear, owner retry amount and Montera invoice metadata;
  it has no generic SQL/status escape hatch. SQLite fault rollback and
  SQLite/PostgreSQL 17 concurrency contracts pass. Bot and FastAPI cancellation,
  review, force-payout and verification paths use this boundary.
- An order lifecycle boundary is deployed in
  `repositories/order_lifecycle_store.py`, gated by
  `ORDER_LIFECYCLE_POSTGRES_ENABLED`. Guarded expiry and dead-session failure
  atomically persist exact notification/provider-cancel jobs in
  `order_lifecycle_work`; workers claim them without rediscovering recently
  updated rows by a time window, and uncertain sends remain `sending` until an
  explicit safe retry. FastAPI cleanup/dead-session paths now use this boundary;
  runtime receipt DDL and 15-minute rediscovery were removed, while exact
  Telegram/admin text and Brabus cancellation remain external durable jobs.
  Migration `021_order_lifecycle.sql` raises snapshot inventory to 50 tables.
  SQLite/PostgreSQL concurrency, injected-fault rollback, adapter, route, P0
  and landmine contracts pass. A fresh consistent production snapshot loaded
  into PostgreSQL 17 and reconciled all 50/50 tables by count and canonical
  hash after migration 021. The production SQLite table was created empty;
  bot and relay restarted active with zero restarts/warnings, SQLite is `ok`,
  money/outbox queues are empty, and loopback/public API checks pass. PostgreSQL
  flags remain off; migration 021 has not been applied to production PostgreSQL.
- A deployed Vertu sell settlement boundary now exists in
  `repositories/sell_settlement_store.py`, gated by
  `SELL_SETTLEMENT_POSTGRES_ENABLED`. It atomically validates a matching
  `paying` sell row with `payout_provider=vertu`, exact payout ref and terminal
  paid evidence, then closes the sell, writes an immutable settlement ledger,
  credits VIP volume once and creates a customer outbox item. Migration
  `022_sell_settlement.sql` raises snapshot inventory to 52 tables. SQLite and
  PostgreSQL concurrency plus final-outbox fault rollback contracts pass.
  FastAPI settled handling now uses this atomic boundary and a durable
  notification dispatcher while preserving the existing customer text and
  audit; the split paid/VIP SQL path is removed. Adapter, route, P0 and
  landmine contracts pass. A fresh production snapshot matched PostgreSQL 17
  across all 52/52 tables by count and canonical hash. Production settlement
  and lifecycle queues are empty; bot and relay are active with zero
  restarts/warnings. PostgreSQL flags remain off.
- A deployed durable reminder boundary now exists in
  `repositories/bot_notification_store.py`, gated by
  `BOT_NOTIFICATION_POSTGRES_ENABLED`. It provides atomic one-shot jobs for
  inactive-user recall, separate Montera customer/admin reminders, abandoned
  orders, payout-delay notices and winback promo delivery; winback promo,
  marker and job commit together. Migration `023_bot_notification_jobs.sql`
  was initially reported as raising snapshot inventory to 53 tables; the
  corrected inventory is 54 because `web_sessions` from migration 002 had
  been omitted from the loader/reconciler allowlist. The bot now uses fixed repository
  selectors for all five flows and a durable exact-text dispatcher: explicit
  proven non-delivery retries, while ambiguous sends stay `sending`; a failed
  Montera customer send cannot suppress the separate admin job. SQLite and
  PostgreSQL selection/claim concurrency, final-job rollback, exact recipient/
  text adapter, landmine, P0, promise and preflight contracts pass. Current
  preflight is still correctly `NO-GO`, reduced from 113 to 93 authoritative
  findings in the two god-files (bot 82, FastAPI 11). A fresh consistent
  production snapshot matched PostgreSQL 17 across all 53/53 tables by count
  and canonical hash. Production reminder/lifecycle/settlement and payout
  queues are empty; bot and relay are active with zero restarts/warnings and
  loopback/public APIs are healthy. PostgreSQL feature flags remain off.
- 2026-08-10 FastAPI authoritative-DB cleanup is deployed:
  `relay-fastapi/main.py` has zero preflight findings and no runtime
  SQL/SQLite wrapper. Startup DDL was replaced by read-only SQLite/PostgreSQL
  schema validation; audit retention, admin analytics and Vertu payout reads
  now use ops/reporting/sell repositories. SQLite and PostgreSQL contracts,
  routes 90/90, P0, landmines and preflight tests pass.
- 2026-08-10 the bot authoritative-DB cleanup is deployed: preflight
  is `GO` with zero runtime blockers/residuals in both adapters. Bot startup no
  longer has `db_conn`, `init_db` or runtime DDL; it read-only validates an exact
  bot schema profile before starting any background task. Empty/incomplete
  SQLite fails closed without creating schema, current production SQLite passes,
  and the profile matches all canonical PostgreSQL migrations in an isolated
  schema. Payment/operator reads, Montera metadata, sent CAS, payout markers and
  referral credits use fixed PostgreSQL-capable repositories; payout
  reconciliation remains the sole atomic closer preserving successful-order
  counts and VIP progression. SQLite/PostgreSQL schema contracts, P0, landmine,
  promise, routes, boundary, runtime-path and preflight checks pass.
- 2026-08-10 production PostgreSQL service assets are deployed:
  Compose pins PostgreSQL 17.10 to immutable digest
  `sha256:742f40ea20b9ff2ff31db5458d127452988a2164df9e17441e191f3b72252193`,
  binds only `127.0.0.1:5432`, persists `obsidian-postgres-data`, reads the
  bootstrap password through a root-owned secret file and never pulls during
  service start. The systemd template keeps Compose attached, waits for health
  and never removes the volume. Compose rendering, systemd verification and the
  static deployment contract pass.
- 2026-08-10 least-privilege PostgreSQL roles and ACLs are deployed:
  fixed non-elevated migrator/app/read-only/payout roles, guarded database
  ownership preparation, explicit ACLs and a machine verifier. The app has
  ordinary DML on all 54 tables but no DDL/claim execution; Laravel has SELECT
  on all 54 authoritative tables for Laravel/monitor/support while remaining
  transaction-read-only; the payout worker can read only two intent tables,
  update only seven claim/result columns and execute only two claim functions.
  An isolated PostgreSQL 17 contract passed positive/denial checks for 54
  tables, 29 sequences and two functions. A custom-format pg_dump/pg_restore
  smoke also matched SHA-256 table content, schema, constraints, indexes,
  sequence state, functions and ACLs and removed its scratch database.
- 2026-08-10 the guarded production snapshot loader completed successfully.
  It accepts only the exact `obsidian_exchange` database through the migrator
  role on loopback:5432 and the exact root-owned `0600` frozen snapshot under
  `/var/lib/obsidian-exchange/cutover`; it requires an explicit initial-empty
  flag/token, all seven writer units inactive and no holder of the authoritative
  SQLite file. All 54 source/target tables are required, every target table is
  locked and rechecked empty in the load transaction, and there is no truncate
  or overwrite mode. Freeze state and snapshot SHA-256 are rechecked before
  commit. Isolated PostgreSQL 17 tests prove rollback on a lost freeze and
  refusal of non-empty or incomplete targets while preserving orders, VIP and
  `web_sessions`. Static preflight requires this loader contract and the
  runbook invocation.
- 2026-08-10 PostgreSQL cutover is complete. The frozen SQLite source gained
  the previously absent but empty `wallet_send_intents` compatibility table,
  then loaded 7,940 rows across all 54 tables. Reconciliation matched 54/54
  counts and hashes, 76 successful orders across 41 users, all 8 VIP rows and
  exactly 41,382.83 RUB VIP volume; referrals and all payout/outbox queues were
  empty, while 10 paid and 52 pending orders were preserved. PostgreSQL 17
  backup/restore smoke, retained custom dump/SHA-256 and ACL verification pass.
  A systemd drop-in ordering defect was caught before data drift: the existing
  `runtime-paths.conf` reset earlier EnvironmentFiles. PostgreSQL env drop-ins
  are now deliberately named `zz-postgres.conf`; a full SQLite↔PostgreSQL check
  proved no differences before restart. All exchange services now expose the
  expected PostgreSQL key names, no process holds `exchange.db`, all eight
  services are active with zero restarts/errors, public/API/admin health passes,
  and deployed preflight is `GO` with zero blockers/residuals. SQLite and its
  frozen snapshot are retained read-only for recovery; do not use simple SQLite
  rollback after this boundary. Monitor PostgreSQL and the first real payout.
- 2026-08-10 post-cutover monitoring remains clean: PostgreSQL and all seven
  application services are active with zero restarts, the warning/error journal
  is empty, the container is healthy, and the relay public-stats endpoint
  responds. Deployed preflight remains `GO` with 23 contiguous migrations and
  zero SQLite blockers/residuals. PostgreSQL still has the cutover-critical 76
  successful orders across 41 users and 8 VIP rows totaling exactly 41,382.83
  RUB; 10 paid and 52 pending orders are unchanged. Payout/referral intents,
  notification/lifecycle/reminder/settlement outboxes and all
  `processing`/`review` payout states are empty. No first real payout has
  occurred yet; continue monitoring rather than generating a synthetic one.
- 2026-08-10 unified-ecosystem P0 hardening is complete for KAIROS/LUMI.
  Both services now run root-owned code/venvs from `/opt` under distinct
  non-login users (`kairos-svc`, `lumi-svc`), with private `0700` state in
  `/var/lib`, `ProtectSystem=strict`, `ProtectHome`, no capabilities and narrow
  write paths. LUMI egress is loopback-only. KAIROS operator API and non-public
  LUMI routes are deny-by-default Bearer; KAIROS→LUMI uses a separate exact-route
  service token, live trading remains HOLD, and no CEX credentials are present.
  A diagnostic command briefly exposed local service-token values in process
  output; both tokens were immediately rotated and services restarted cleanly.
  Never store their values. Targeted KAIROS/runtime (14) and LUMI (16) tests,
  compilation, systemd verification and production API checks pass; services
  are active with zero restarts and empty warning/error journals. Two AI keys
  are encrypted locally but still require provider-side rotation. Next: define
  `PortfolioSource`/`CustodyDomain` and a read-only CEX connection contract.
- 2026-08-10 E1 read-only contract foundation is deployed in KAIROS. A frozen
  `PortfolioSource` model enforces exact source-kind/custody pairing; balance
  observations preserve decimal strings and cannot represent unknown/error as
  zero. The pure permission verifier requires fresh exact-account evidence with
  read=true and explicit trade/withdraw/internal-transfer=false; unknown,
  stale, future or mismatched evidence is BLOCKED. The operator contract API is
  live, while legacy global `/api/exchanges/save|test` now return 409 because
  balance access was not permission proof and those paths fed credentials into
  process-wide trading state. A pure Bybit `/v5/user/query-api` parser rejects
  read-write, dangerous, unknown and malformed permissions without retaining
  the returned API key/UID. No CEX credential was added. 30 targeted tests,
  compilation, systemd verification and production checks pass; KAIROS is
  active with zero restarts. Official API comparison selected Bybit as the
  first adapter because authenticated key self-inspection exposes `readOnly`,
  detailed permissions and IP binding. Next: implement the owner-isolated
  connector store, targeted vault deletion and drift checks before accepting
  even a testnet key.
- 2026-08-10 the internal E1 connector lifecycle is deployed without HTTP
  credential ingress or CEX keys. Random source IDs, source-scoped vault refs,
  owner-filtered access and indistinguishable foreign/missing lookup form the
  isolation boundary; public projections omit owner and vault refs. Connector
  store and AES-GCM vault now use process locks, unique same-directory temp
  files, mode 0600, file/directory fsync and atomic replace; corruption fails
  closed. Permission updates use revision CAS, and a credential ref is usable
  for balance reads only while READ_ONLY_VERIFIED with proof age <=15 minutes.
  Drift blocks immediately. Disconnect persists REVOKING before targeted vault
  deletion and converges idempotently to REVOKED; deletion faults remain
  terminally blocked and retry safely. 40 targeted tests including real
  multiprocessing races, cross-owner access, stale proof, delayed evidence,
  fault/retry and secret non-disclosure pass. Production KAIROS is active with
  zero restarts and clean journal; status/contract/health and Exchange API pass.
  Do not expose connector endpoints or accept ownerRef from a request until
  Wallet/Relay supplies a server-derived authenticated principal. Next: design
  that scoped Relay→KAIROS identity contract, then internal credential ingress
  and periodic Bybit testnet drift/balance transport.
- 2026-08-10 the scoped Relay→KAIROS identity boundary is deployed. Relay owns
  an Ed25519 private signing key and separate principal-derivation key; KAIROS
  has only the allowlisted public key. Canonical requests bind exact method,
  path/query, body hash, content type, key id, timestamp, nonce, opaque
  server-derived web-user principal, scope and `kairos` audience. KAIROS allows
  ±30s and persistently consumes nonce+keyId in a locked/atomic 0600 replay
  store, so restart does not reopen replay. Internal connector listing accepts
  only `connectors:read`; unsigned requests and KAIROS operator Bearer both get
  401. Relay exposes a read-only `/api/wallet/cex-sources` facade and never
  accepts ownerRef. Telegram access requires initData <=5m and an existing
  linked web user; generic initData now rejects missing/zero/malformed/stale or
  >30s-future auth_date. 48 targeted tests plus 91-route, Wallet, market and
  landmine suites pass. Production signed smoke returns `connector-list.v1`;
  both services are active/0 restarts with clean journals. No CEX key exists.
- 2026-08-10 Relay least-privilege cutover is complete. Production now runs as
  the non-login `relay-svc` user with strict systemd filesystem/home/device/
  kernel isolation, no capabilities and only the receipt directory writable;
  it cannot read the payout wallet vault or frozen SQLite database. Relay's
  Ed25519/principal keys moved to the dedicated root:`relay-svc` 0750
  `/etc/obsidian-relay` boundary with 0640 files, without weakening the broad
  `/etc/obsidian-exchange` secret directory. All 89 PostgreSQL receipt paths
  were transactionally moved from `/root/receipts` to the checksummed
  relay-owned runtime copy. A background-task-disabled shadow on port 15001
  proved public reads, PostgreSQL access and signed KAIROS listing before
  cutover. Production loopback/public stats and Relay→KAIROS signing pass;
  forbidden reads fail, no forbidden file descriptors exist, Relay is active
  with zero restarts/errors, and the shadow is inactive. No CEX key exists.
  Next: implement the internal idempotent connect/disconnect orchestration and
  test only with a tightly restricted Bybit testnet read-only credential;
  provider-side rotation of the two previously exposed AI keys remains open.
- 2026-08-10 internal Relay→KAIROS connector mutation orchestration is deployed
  without accepting a real CEX credential. Exact signed POST connect and DELETE
  disconnect routes require `connectors:write`; list remains `connectors:read`.
  Connect accepts only a strict Bybit schema and one <=4 KiB canonical JSON
  body, creates PENDING_PROOF first, binds a source-scoped versioned credential
  envelope, and stores it only in AES-GCM vault. A retry recovers a crash between
  binding and vault write and never overwrites an existing secret. Any write
  fault enters the disconnect saga; disconnect blocks use before targeted
  deletion and is owner-scoped/idempotent. Public responses expose neither
  secrets nor vault refs; PENDING_PROOF cannot read balances. Body-byte/scope
  mutation, oversized input, cross-owner 404, crash recovery, cleanup and
  idempotency tests pass (targeted suite 28 tests); compilation/diff checks pass.
  Production signed list remains empty, unsigned mutation is 401, KAIROS and
  Relay are active with zero restarts/errors. Next: add a Bybit testnet-only
  permission-proof transport and periodic drift worker; do not enter a key until
  its read-only/trade-off/withdraw-off/transfer-off permissions are confirmed.
- 2026-08-10 the Bybit permission-proof transport and callable drift verifier
  are deployed but not scheduled and have never received a real key. Transport
  is pinned to the official testnet origin and exact `/v5/user/query-api` GET,
  uses the documented HMAC/timestamp/recvWindow headers, fixed timeouts and no
  redirects, and returns bounded generic errors without provider payloads.
  The worker decrypts one versioned envelope just-in-time, constant-time binds
  the echoed API key, validates provider time and account identity, stores only
  a vault-keyed account fingerprint, and applies revision-CAS permission proof.
  Permission or account drift becomes BLOCKED; raw API key, UID, KYC fields and
  response are not persisted. Transport HMAC/origin/error, first proof, refresh,
  permission drift and account drift tests pass within the expanded targeted
  suite; KAIROS restarted active. Scheduling remains intentionally off until
  transient network/rate-limit failures have an explicit DEGRADED transition
  distinct from BLOCKED. No Bybit request was sent and connector list is empty.
- 2026-08-10 transient connector handling and periodic drift scheduling are
  deployed. Network failures, rate limits, 5xx and malformed provider replies
  move an eligible connector to fail-closed `DEGRADED`; explicit HTTP auth
  rejection and proven permission/account drift remain `BLOCKED`. A later
  successful exact proof recovers `DEGRADED` to `READ_ONLY_VERIFIED`; neither
  degraded nor blocked credentials can read balances. KAIROS refreshes eligible
  connectors every 300 seconds, isolates per-connector faults and never exposes
  owner refs through HTTP. The targeted 18-test suite, production-Python
  compilation and diff checks pass. KAIROS is active with zero restarts and a
  clean journal; the connector store is empty, so no Bybit request was sent.
  Next: provision one tightly restricted Bybit testnet key through the protected
  Relay flow only after independently confirming read-only/trade-off/
  withdraw-off/transfer-off permissions, then observe first proof, refresh and
  balance-read behavior without enabling trading.
- 2026-08-10 the user deferred all real CEX keys. A hermetic rehearsal script
  `kairos/scripts/rehearse_bybit_connector.py` now exercises a synthetic key and
  mocked Bybit evidence in a disposable encrypted vault, with zero network and
  no production mutation. It proved `PENDING_PROOF → READ_ONLY_VERIFIED →
  DEGRADED → READ_ONLY_VERIFIED → BLOCKED`, verified degraded balance access is
  denied and confirmed no key/secret appears in public results. Production
  connector count remains zero. Continue with keyless connector/portfolio work;
  do not provision a real Bybit credential until the user explicitly resumes it.
- 2026-08-10 the keyless bounded Bybit balance slice is deployed. Only after a
  successful fresh permission proof, the scheduler may call the fixed testnet
  unified-wallet balance endpoint. Responses are capped at 256 KiB/256 assets;
  asset IDs and exact decimal strings are validated without float conversion and
  committed owner/source/revision atomically. Transient or malformed results keep
  the last snapshot as `STALE` and move the connector to `DEGRADED`; permission
  drift stales it before `BLOCKED`; no failure invents zero. Disconnect purges
  financial snapshots with the credential. The existing signed owner-scoped
  Relay facade carries the safe projection without owner/vault/secret refs. The
  expanded 20-test suite, production compilation and diff checks pass. KAIROS is
  active with zero restarts, clean journal and zero connectors, so no Bybit call
  occurred. Next keyless E1 slice: build the normalized three-custody portfolio
  aggregator and prove consistent freshness/error semantics across Wallet,
  ObsidianExchange history and mocked CEX observations.
- 2026-08-10 the normalized three-custody portfolio aggregator is deployed at
  authenticated `GET /api/wallet/portfolio`. `unified-portfolio.v1` keeps
  verified wallets (`SELF_CUSTODY`), ObsidianExchange activity
  (`OBSIDIAN_OPERATIONAL`) and owner-scoped KAIROS snapshots (`CEX_CUSTODY`) in
  separate lanes. ObsidianExchange exposes order activity but no fictitious
  custodial balance. Each backend fails independently to `UNAVAILABLE`; empty is
  distinct from error, wallet unknown remains null/error and CEX stale retains
  exact decimal strings while making the aggregate incomplete. Wallet addresses,
  owner refs, vault refs and secrets are absent. Ten route/P0/landmine/portfolio
  regressions, production compilation and diff checks pass. Relay is active with
  zero restarts and a clean journal; unauthenticated portfolio access is 403;
  loopback and public stats are healthy. No real CEX key or Bybit call occurred.
  Next keyless E1 slice: render this normalized contract in the Mini App with
  explicit custody badges and honest EMPTY/STALE/UNAVAILABLE copy, while keeping
  all existing wallet and market actions unchanged.
- 2026-08-10 the normalized portfolio is rendered in the production Mini App.
  The block sits above legacy wallet empty/main views, so ObsidianExchange and
  CEX lanes remain visible without an on-chain wallet. Explicit badges say keys
  stay with the user, ObsidianExchange does not custody portfolio funds, and KYC/
  custody stay with the external exchange. EMPTY, DEGRADED, UNAVAILABLE, STALE,
  pending and blocked states have distinct copy; missing totals render as
  unavailable, never zero. Existing wallet summary and send/receive/buy/Market
  actions remain wired. Seven UI/portfolio/route/P0 regressions, inline JavaScript
  syntax and diff checks pass. Production `/webapp` contains all custody markers;
  Relay is active with zero restarts/clean journal, unauthenticated portfolio is
  403 and KAIROS is active. No real CEX key or provider call occurred. Next
  keyless E1 slice: add a deterministic E2E fixture exercising connect/list/
  portfolio/disconnect across Relay→KAIROS and prove disconnect removes the CEX
  lane's financial snapshot while leaving Wallet and Obsidian lanes intact.
- 2026-08-10 the keyless Relay→KAIROS connector/portfolio E2E fixture is
  complete. It uses the production Relay Ed25519 signer, KAIROS canonical
  request/scope/replay verifier, encrypted connector vault and lifecycle stores
  with an in-process dispatcher and synthetic provider evidence; it performs
  zero network calls and no production mutation. The fixture proves connect,
  permission proof, exact-decimal balance, owner-scoped list, normalized
  three-lane portfolio and disconnect. Disconnect purges the CEX financial
  snapshot while Wallet balance and ObsidianExchange order activity remain
  byte-for-byte unchanged; public material contains no API secret or vault ref.
  The ownership landmine now recognizes the authenticated
  `_connector_web_user` helper while verifying that the helper itself retains
  web-session and Telegram-initData checks. The E2E, four portfolio semantics,
  92-route, P0, landmine, compilation and diff checks pass. No real CEX key or
  provider request occurred. Next keyless E1 slice: define a read-only CEX
  connection management projection/UI (connect remains disabled without an
  explicitly resumed real-key flow), including state/freshness explanations and
  an owner-confirmed disconnect action that cannot affect other custody lanes.
- 2026-08-10 the keyless CEX connection-management projection is deployed in
  the Mini App. It lists owner-scoped sources with explicit permission state and
  last-check time; new connection is visibly disabled and states that keys are
  not accepted through chat/forms. Disconnect requires browser confirmation and
  the exact server-side `DISCONNECT` confirmation, derives the principal only
  from the authenticated web user, calls KAIROS with `connectors:write`, and
  succeeds only after KAIROS reports `REVOKED`; it then refreshes only CEX and
  portfolio views. Unauthenticated list/delete return 403. Three management UI,
  three portfolio UI, 93-route, P0, landmine, runtime-isolation, compilation,
  inline-JavaScript and diff checks pass. Relay is active with zero restarts,
  clean warning journal and healthy loopback/public stats. No connector exists,
  no CEX key/provider call occurred, and connect remains disabled.
- The deployment check exposed a pre-existing RSPay webhook 500 after Relay's
  least-privilege cutover: legacy `runtime.env` overrode the provider logger path
  with a location blocked by `ProtectSystem=strict`. A dedicated
  `RELAY_PROVIDER_LOG_DIR=/var/log/obsidian-relay` now takes precedence and is
  covered by the runtime-isolation test. An unsigned RSPay webhook now correctly
  returns 401 instead of 500. Next keyless E1 slice: add a sanitized connector
  event/audit projection for user-visible lifecycle history without owner,
  account, credential or vault identifiers; keep real-key ingress deferred.
- 2026-08-10 the sanitized CEX lifecycle history is deployed. Connector events
  are appended atomically in the same locked/atomic store write as create,
  permission proof/block, balance refresh/degrade and disconnect transitions;
  legacy stores without `events` read as an empty history. The store keeps a
  bounded 1,000-event tail. The owner-scoped public projection contains only
  provider, event type, resulting state, timestamp and a broad safe category;
  it omits owner/source/account/credential/vault identifiers and raw provider
  errors. Relay exposes authenticated `/api/wallet/cex-events`; the Mini App
  renders safe Russian lifecycle copy and refreshes it after disconnect.
  Synthetic E2E proves the full five-event connect/proof/balance/disconnect
  sequence and secret/identifier non-disclosure; owner isolation and legacy
  compatibility tests pass. Four management UI, 94-route, P0, landmine,
  compilation, inline-JavaScript, scope and diff checks pass. KAIROS/Relay are
  active with zero restarts and clean warning journals; unauthenticated event
  routes return 401/403 and loopback/public APIs are healthy. The production
  connector store is still absent (zero connectors/events), so no provider call
  or production state mutation occurred. Next keyless E1 slice: define and
  enforce event-retention/privacy semantics (age plus bounded count) and expose
  an honest history-expiry notice before treating the E1 read-only surface as
  complete; real-key ingress remains deferred.
- 2026-08-10 connector-event privacy retention is deployed. KAIROS enforces a
  90-day inclusive window plus a global 1,000-event cap; invalid timestamps are
  discarded. Pruning runs both during lifecycle writes and owner history reads,
  and physically rewrites the store under the same process lock/fsync/atomic-
  replace boundary, so expired data is removed from disk rather than merely
  hidden. Empty/absent and legacy stores remain compatible and are not created
  by deployment. KAIROS publishes the exact retention contract; Relay fails
  closed unless it is exactly 90 days/1,000 events. Mini App states that events
  are retained up to 90 days and automatically deleted, and shows an honest
  unavailable notice if the policy cannot be confirmed. Four age/count/disk-
  pruning tests, connector E2E, four management UI, 94-route, P0, landmine,
  compilation, inline-JavaScript and diff checks pass. KAIROS/Relay are active
  with zero restarts and clean warning journals; event endpoints remain 401/403
  without authentication and public APIs are healthy. Production still has no
  connector store, real CEX key, event or provider request. Next keyless E1
  closure slice: freeze/document the public connector/portfolio/event schemas,
  add compatibility fixtures and an operational readiness gate, then mark the
  read-only surface complete while real-key ingress remains explicitly deferred.
- 2026-08-11 the keyless E1 read-only surface is frozen and deployed. Canonical
  compatibility fixtures define exact `connector-list.v1`,
  `connector-events.v1` and `unified-portfolio.v1` fields, enums, ordered custody
  lanes and retention. Relay now also fails closed on connector-list version or
  type drift. `deploy/check_e1_readonly_readiness.py` validates fixtures, source
  agreement, disabled Mini App credential ingress, retention and optional
  production state without network access or store creation; mutation tests
  prove extra private fields and any connector/credential produce `NO-GO`.
  Documentation states that schema-breaking changes require a new version.
  The deployed `/opt` production gate reports `E1 READ-ONLY: GO` with three
  schemas, connect disabled, credentials absent and retention 90d/1,000.
  Relay/KAIROS are active with zero restarts and clean warning journals;
  loopback/public APIs are healthy and unauthenticated CEX surfaces return 403.
  This completes the keyless E1 surface only: the roadmap's full E1 gate remains
  intentionally open until the owner explicitly resumes one restricted testnet
  read-only credential and real permission/balance/drift acceptance. Next safe
  work is keyless E2 foundation: a versioned minimal EvidenceRecord and decision
  envelope plus hermetic proof that LUMI can tighten but never expand hard
  permissions; no real CEX data, trading or credential ingress.
- 2026-08-11 the first keyless E2 contract foundation is deployed but remains
  deliberately disconnected from runtime decisions. Frozen
  `evidence-record.v1` creates a deterministic opaque SHA-256 content reference
  from an aware timestamp, bounded subject/signal/source/freshness and at most
  32 scalar facts; fact classes implying owner/account/credential/key/address/
  wallet/balance/amount/PII/KYC and raw provider payloads are rejected.
  `decision-envelope.v1` freezes policy `e2-monotonic-hard-gate.v1` and the
  strict order `ALLOW < HOLD < MANUAL < FREEZE`; combined verdict is always the
  stricter hard/advisory value, `actionAllowed` is true only for combined ALLOW,
  and forged non-monotonic envelopes fail validation. Unknown, timeout, error
  and malformed advisory results normalize to HOLD and cannot soften MANUAL or
  FREEZE. Two frozen fixtures, five privacy rejections, the complete 16-pair
  verdict matrix, three failure modes and forgery rejection pass with P0,
  landmine, compilation and diff checks. The deployed module passed a hermetic
  timeout smoke; KAIROS/LUMI stayed active with zero restarts and clean warning
  journals. No service route, network request, CEX data, key, trade or money
  action was added. Next keyless E2 slice: add an append-only hash-chained shadow
  decision journal and deterministic replay verifier before any narrow LUMI
  risk endpoint or runtime bridge consumes these envelopes.
- 2026-08-11 the keyless E2 shadow journal is implemented and verified, still
  disconnected from all runtime decisions. `shadow-decision-record.v1` is an
  append-only JSONL chain with deterministic record IDs, sequence and previous
  hashes, full pre-append replay, exact rehashed EvidenceRecord references,
  monotonic DecisionEnvelope validation, exclusive locking, fsync, 0600 mode,
  symlink refusal and bounded file/line sizes. Duplicate cores are idempotent;
  tamper, partial tails, malformed records, capacity overflow and unsafe locks
  fail closed. Targeted contract/journal tests (33), P0 and landmine regressions
  pass. The module/documentation are deployed without a service restart; a
  hermetic deployed replay smoke passed, and KAIROS/LUMI remain active with zero
  restarts and no warning journal entries. No production journal, route, CEX
  call, credential, trade or money action was created. Next safe E2 slice:
  define a dedicated service-owned journal path,
  retention/checkpoint/backup policy and read-only operator verification signal
  before introducing any authenticated shadow-only producer or LUMI endpoint.
- 2026-08-11 the E2 journal operational boundary is deployed without enabling a
  producer. Its sole path is the `kairos-svc`-owned `0700`
  `/var/lib/kairos/e2-shadow/decisions.jsonl`; code/lock files remain `0600`.
  Policy keeps complete archived generations for 400 days and permits deletion
  only after two hash-verified backups plus a full replay restore rehearsal; no
  deletion/rotation is automated yet. A hardened daily systemd oneshot emits
  `shadow-operator-signal.v1` using a genuinely read-only shared-lock replay.
  Its first production run returned `GO`, `journalPresent:false`, zero records
  and the genesis hash without creating a journal or lock. The timer is active;
  KAIROS stayed active with zero restarts. Contract/journal/operations/landmine
  tests pass (37), P0 passes, production compilation and diff checks pass. Next
  safe E2 slice: implement generation rotation, two-destination hash-verified
  backup and destructive-target-guarded restore rehearsal, then prove chain
  continuity across generations; do not add a producer or LUMI endpoint yet.
- 2026-08-11 E2 generation rotation and backup/restore tooling is implemented
  and deployed, still with no producer. Rotation copies/fsyncs an immutable
  generation, appends a hash-chained checkpoint, then atomically replaces the
  active file; global sequence and previous hash continue across generations.
  The operator CLI requires exactly two distinct external backup destinations;
  every copied file and manifest is SHA-256 checked and both bundles must replay
  to the source head. Restore rehearsal accepts only an existing non-root
  scratch directory, creates an exact guarded temporary target, replays the
  complete chain and removes only that target. There is deliberately no
  retention-deletion command. Contract/journal/rotation/backup/restore/tamper/
  landmine tests pass (42), P0 passes, production compilation, systemd verify
  and both diff checks pass. The deployed daily probe now validates
  `shadow-generations-replay.v1` and returned `GO` with zero generations,
  records and files plus the genesis hash. KAIROS/LUMI remain active with zero
  restarts. Next safe E2 slice: define two actual backup storage boundaries and
  a first-record-triggered schedule/readiness alarm, then run an off-production
  synthetic backup/restore drill under the service UID; keep the producer and
  LUMI endpoint disabled.
- 2026-08-11 the scheduled E2 backup boundary is deployed. A first-record
  systemd path unit and persistent daily timer run a hardened `kairos-svc`
  oneshot with journal state read-only and writes limited to two `0700` backup
  zones plus a guarded restore scratch. Empty production returned
  `ARMED_NO_RECORDS`, created no journal/bundle/lock and left all zones empty.
  A fully synthetic drill under UID 995 produced two records across one
  rotation, two verified bundles and a matching restored head, then removed its
  guarded scratch tree. The first unit start exposed a `PrivateTmp` namespace
  conflict with `/var/tmp`; scratch was moved to
  `/var/lib/kairos-e2-shadow-restore`, the unit then succeeded, and the empty
  obsolete directory was removed. Both local backup zones share `/dev/sda1`, so
  readiness truthfully reports `independentFailureDomains:false` and
  `producerReady:false`; they cannot authorize deletion or producer enablement.
  Tests pass (45 total; 16 targeted after the namespace fix), plus P0,
  production compilation, systemd validation and diff checks. KAIROS/LUMI are
  active with zero restarts. Next safe E2 step requires an independently mounted
  second backup destination (or explicit external backup integration); until
  available, continue keyless with a narrow authenticated shadow-only producer
  design/fixture but do not enable it or add a LUMI runtime endpoint.
- 2026-08-11 the narrow shadow-only Relay→KAIROS boundary is implemented and
  deployed but doubly disabled. KAIROS accepts only authenticated/replay-guarded
  `POST /internal/v1/shadow-decisions` with exact `shadow:write` scope and the
  frozen privacy-minimized submission; it never persists the Relay principal.
  Append additionally requires `KAIROS_E2_SHADOW_INGRESS_ENABLED=1` and backup
  destinations on different filesystem device IDs. Production has flag 0 and
  one `/dev/sda1`, so a signed attempt would still fail 503 without state. The
  Relay producer has no route/task integration and flag 0; disabled tests prove
  it reads no signing key and makes no network request. Its exact JSON wire
  fixture validates against KAIROS, private fact classes fail, and even a
  synthetic ALLOW response has `actionAllowed:false`. Targeted contract,
  ingress, producer, identity, backup and landmine tests pass (65), P0 passes,
  production compilation and diff checks pass. KAIROS and Relay were restarted
  only to apply disabled flags; KAIROS/Relay/LUMI are active with zero restarts,
  clean warning journals, healthy actual loopback/public surfaces and an empty
  E2 state directory. No LUMI call, provider call, CEX key, trade or money action
  occurred. Next keyless E2 slice: freeze a shadow observation trigger catalog
  and deterministic sampling/idempotency contract plus metrics projection in a
  hermetic fixture; keep both producer flags 0 until independent backup exists.
- 2026-08-11 the E2 observation/sampling and metrics contracts are frozen and
  deployed without runtime production. `shadow-trigger-catalog.v1` permits only
  permission drift, connector degraded, provider rate limit, stale market data
  and advisory unavailable, each with exact fact keys and 1/60/300-second UTC
  buckets. `shadow-observation-plan.v1` hashes catalog/trigger/bucket/submission,
  so same-bucket retries are identical while changed facts/buckets differ;
  unknown triggers or fact drift fail. `shadow-metrics.v1` has fixed zero-filled
  counters by signal/freshness/combined verdict plus hard/advisory disagreement
  and tightening counts; it exposes no facts, IDs, principal or timestamps and
  rejects unknown signals. The daily read-only verifier now replays archived +
  active generations before projecting metrics. Production returned `GO` with
  every metric zero and still created no journal/lock. Tests pass (73), P0,
  production compilation and diff checks pass; hermetic modules pass under both
  service UIDs. No service restart was needed for this slice; Relay/KAIROS/LUMI
  remain active with zero restarts and clean warning journals, both producer
  flags remain 0. Next keyless E2 slice: freeze a divergence/latency/staleness
  alert policy and operator alarm projection with deterministic thresholds and
  recovery semantics; do not wire producer or LUMI runtime while independent
  backup remains unavailable.
- 2026-08-11 the pure E2 operator alarm policy is frozen and deployed without
  runtime wiring. `shadow-alert-policy.v1` uses aligned 300-second windows;
  permission drift is immediately CRITICAL, stale/provider/slow advisory use
  exact count thresholds, and hard/advisory divergence requires both count and
  basis-point rate. Escalation is immediate; recovery needs two consecutive
  healthy windows. `shadow-alarm-state.v1` carries `lastWindowEnd`, so gaps and
  replay fail closed, while reactivation resets recovery. The projection has a
  fixed alarm set, no facts/IDs/principal, and always `actionAllowed:false` even
  at CRITICAL. Threshold, boundary, malformed input, escalation, recovery,
  gap/replay and privacy tests pass; the full targeted suite is 90 plus P0,
  production compilation and diff checks. A deployed service-UID fixture
  returned `CRITICAL_NON_EXECUTING`. No service restart or state file was
  needed; Relay/KAIROS/LUMI remain active with zero restarts and clean warning
  journals, producer flags remain 0. Next keyless E2 slice: freeze deterministic
  extraction of aligned alert windows from verified journal timestamps,
  including bounded advisory latency buckets, then prove replay produces the
  same alarm sequence; keep it hermetic and non-persistent until independent
  backup exists.
- 2026-08-11 deterministic E2 alert-window extraction and replay are frozen and
  deployed, still hermetic/non-persistent. Verified contiguous records are
  assigned by aware `recordedAt` to aligned 300-second UTC windows; empty gaps
  become explicit zero windows, while out-of-range records, sequence gaps,
  naive/unaligned bounds and ranges over seven days fail. Longer history can be
  replayed in consecutive chunks using exact prior state; tests prove whole and
  chunked results have identical projections/final state. Trigger fact values
  are now bounded too: latency, age and retry use frozen enums, numeric counts
  are 0..1000 and booleans must be real booleans. Slow latency counts once per
  submission for `S1_3/OVER_3S/TIMEOUT`, never exposes raw latency. Frozen
  `shadow-alarm-replay.v1` output contains no facts/evidence/record/principal and
  always has `actionAllowed:false`. The targeted suite passes 100 tests plus P0,
  production compilation/diff checks and service-UID frozen-fixture smoke pass.
  No restart or state mutation occurred; Relay/KAIROS/LUMI are active with zero
  restarts and clean warning journals, producer flags remain 0. Next keyless E2
  slice: add a read-only offline operator replay CLI with explicit bounded UTC
  range and stdout-only output, plus tamper/failure exit semantics; do not add a
  route, persistence, producer scheduling or LUMI runtime endpoint.
- 2026-08-11 the read-only offline E2 operator replay CLI is implemented and
  deployed without a unit/timer/route. It requires explicit aware aligned UTC
  start/end, verifies the complete archived + active chain before filtering,
  and then emits `shadow-operator-replay.v1`; tamper outside the selected range
  still fails. Success is one stdout JSON with exit 0, domain/replay failure is
  stdout `NO_GO` exit 1, and argument errors are stdout `NO_GO` exit 2. There is
  no output path, network import or state write. Absent-journal tests and the
  production service-UID smoke returned honest genesis/CLEAR with zero selected
  records and `actionAllowed:false` without creating a directory/journal/lock.
  Critical, tamper-outside-range, stdout/stderr, argument, privacy and source
  landmine tests pass; targeted suite is 106 plus P0, production compilation
  and diff checks. No services restarted; Relay/KAIROS/LUMI remain active with
  zero restarts and clean warning journals, producer flags remain 0. Next
  keyless E2 slice: freeze the minimal LUMI advisory request/response wire and a
  hermetic client/dispatcher fixture proving timeout/error/malformed normalize
  to HOLD and never soften hard verdicts; do not expose a runtime endpoint or
  make production network calls until independent backup exists.
- 2026-08-11 the minimal E2 LUMI advisory wire and hermetic KAIROS dispatcher
  are frozen and deployed without runtime transport. The request carries only
  policy, aware time, hard verdict and up to eight validated minimized evidence
  records; its `ar_` ID hashes the canonical full body. The response is bound to
  that ID and only permits advisory verdict, safe reason codes, evaluated time
  and bounded model version. The pure module imports no HTTP/env/token/endpoint
  and uses an injected transport with exact 750 ms deadline. Wrong ID, field/
  enum/reason/time drift is MALFORMED; timeout/error/malformed all normalize to
  HOLD. The complete 4x4 matrix proves advisory can never soften hard verdict;
  every dispatch, including ALLOW/ALLOW, is `executionEffect:NONE` and
  `actionAllowed:false`. A first test run correctly exposed UTC `Z` vs `+00:00`
  request-hash canonicalization drift; wire times are now canonical `Z` and all
  tests pass. Targeted suite is 133 plus P0, frozen request/response fixtures,
  compilation/diff checks and service-UID timeout smoke pass. No network call,
  restart or state mutation occurred; Relay/KAIROS/LUMI remain active with zero
  restarts and clean warning journals, producer flags remain 0. Next keyless E2
  slice: implement a pure LUMI-side request validator/advisory adapter against
  the frozen fixtures and prove cross-package request→response→KAIROS dispatch,
  still with no route, token handling, model call or production transport.
- 2026-08-11 the pure LUMI-side E2 advisory adapter is implemented and deployed
  without runtime wiring. It independently validates exact request/evidence
  fields and hashes plus the frozen five-signal fact catalog; unknown signals,
  missing/extra facts, coerced booleans/integers, out-of-range counts and raw
  latency values fail closed. Deterministic rules only tighten the hard verdict
  and use no route, token, environment, network, provider/model call or state.
  Frozen fixtures now use catalog signal `CONNECTOR_DEGRADED`; cross-package
  request→LUMI response→KAIROS dispatch succeeds under `kairos-svc` and remains
  `executionEffect:NONE/actionAllowed:false`. The targeted suite passes 150
  tests plus P0; both production interpreters compile and all diff checks pass.
  Pure files match `/opt`; no service restarted or state was created. KAIROS,
  LUMI and Relay remain active with zero restarts and clean warning journals;
  ingress/producer flags remain 0. Next safe E2 slice: build a fully offline
  replay fixture from frozen observation through advisory dispatch to journal
  projection, without append, route, scheduler, endpoint or network transport.
- 2026-08-11 the full offline E2 observation→advisory→journal projection is
  frozen and deployed without runtime wiring. `shadow-offline-replay.v1`
  revalidates the Relay observation identity and JSON submission, calls the
  pure LUMI rules through injected local transport, applies the KAIROS monotonic
  dispatcher, and projects the exact genesis journal record only in memory.
  A first test exposed that strict `ShadowSubmission.model_validate` rejects
  Relay's JSON enum strings; replay now correctly validates the actual wire via
  `model_validate_json`. Journal `project_record` is pure and shared by real
  append; a temporary-journal test proves projected and appended records are
  byte-equivalent. The exact frozen fixture and service-UID smoke produce
  MANUAL while remaining `projectionOnly:true`, `executionEffect:NONE` and
  `actionAllowed:false`. The complete targeted suite passes 157 tests plus P0,
  compilation and diff checks. Deployed files match `/opt`; no restart or E2
  state occurred. KAIROS/LUMI/Relay are active with zero restarts and clean
  warning journals; both runtime flags remain 0. Next safe E2 slice: add pure
  multi-record/head-aware projection proving sequence/hash continuity and
  duplicate idempotency across all five frozen triggers, still without append,
  route, scheduler, endpoint or network.
- 2026-08-11 head-aware multi-record offline E2 projection is frozen and
  deployed without runtime wiring. `shadow-offline-batch.v1` accepts 1..64
  items over an explicit validated `baseSequence/baseHash`; each unique
  observation advances the hash chain, exact duplicate retry is reported but
  does not advance sequence/head, and the same observation ID with changed
  request/advisory/decision inputs fails closed. One chain covers all five
  frozen triggers from non-genesis sequence 40 through 45 with expected
  FREEZE/MANUAL/HOLD outcomes. A temporary journal using the same base proves
  every projected record equals real append output and verifies to the same
  head. Source landmines also forbid even `.append` syntax in the pure replay.
  The frozen duplicate fixture and `kairos-svc` smoke match exactly and remain
  projection-only/non-executing. The targeted suite passes 165 tests plus P0,
  compilation and diff checks. `/opt` files match; no restart or E2 state was
  created. KAIROS/LUMI/Relay are active with zero restarts and clean warnings;
  both flags remain 0. Next safe E2 slice: add a pure strict verifier for frozen
  batch output plus chunk/resume equivalence and tamper/failure cases, without
  append, route, scheduler, endpoint or network.
- 2026-08-11 the strict pure offline batch verifier is frozen and deployed with
  no runtime wiring. `shadow-offline-batch-verification.v1` independently
  checks exact outer/nested fields, cardinalities, projection-only flags,
  duplicate identities, advisory response and dispatch bindings to the journal
  decision, evidence/decision validity, sequence/previous-hash continuity and
  record/head hashes. Journal now exposes the same pure in-memory chain verifier
  used internally; its errors normalize to the public fail-closed `ValueError`.
  Tamper tests cover head, counts, action flag, duplicate ID, combined verdict,
  sequence, record hash and extra fields. Whole five-trigger replay and resumed
  chunks `2 + 3` yield identical records, last sequence and head. The frozen
  verification fixture matches under `kairos-svc`; targeted suite passes 175
  tests plus P0, compilation and diff checks. `/opt` matches, production E2
  state remains empty, both flags remain 0, and KAIROS/LUMI/Relay are active
  with zero restarts and clean warnings. Next safe E2 slice: freeze a hermetic
  signed service-identity/replay-protection envelope for a future shadow-only
  KAIROS→LUMI transport, without endpoint, network call, token/key provisioning
  or runtime enablement; independent backup remains required before producer.
- 2026-08-11 a hermetic signed identity envelope for a future KAIROS→LUMI E2
  advisory transport is frozen and deployed without a route or runtime wiring.
  `shadow-service-envelope.v1` binds Ed25519 to exact POST/path/empty query,
  canonical advisory body SHA-256, JSON content type, key ID, epoch, nonce,
  issuer `kairos-shadow`, exact `shadow:advisory` scope and `lumi-shadow`
  audience with ±30-second skew. Signer, verifier and nonce consumer are
  injected, so the module reads no env/key/file, stores no state and performs
  no network/model call. Nonce consumption occurs only after fields/body/time/
  signature pass; replay and 17 field/body/signature/clock/extra tamper cases
  fail closed without premature consumption. The verified body is independently
  accepted by the LUMI advisory validator. Frozen envelope/verification fixtures
  match under UID `lumi-svc` using a synthetic key. The full targeted suite
  passes 194 tests plus P0, compilation and diff checks. Production LUMI venv
  lacks `cryptography`; no dependency or key was installed, so this is an
  explicit blocker for runtime verification. `/opt` matches, E2 state is empty,
  flags remain 0, and KAIROS/LUMI/Relay are active with zero restarts/warnings.
  Next safe E2 slice: freeze a bounded pure replay-ledger snapshot/transition
  contract proving expiry, capacity and restart continuity, without filesystem
  persistence, endpoint, key provisioning or runtime enablement.
- 2026-08-11 the bounded pure replay-ledger snapshot/transition contract is
  frozen and deployed without persistence or runtime wiring.
  `shadow-replay-ledger.v1` stores only SHA-256 of `keyId NUL nonce` plus expiry,
  never raw identity values. Capacity is explicit and bounded 1..10,000;
  expiry is constrained to `now..now+60s`. The immutable transition validates
  the complete snapshot, keeps entries through inclusive expiry, deterministically
  prunes expired entries, rejects active replay/full capacity and returns a
  sorted next snapshot without mutating input. JSON round-trip simulates restart
  and preserves replay rejection; expiry recovery, capacity recovery, ordering,
  privacy and malformed snapshot/clock tests pass. Signed envelope integration
  consumes this ledger and rejects replay after JSON restore. The full E2 suite
  passes 213 tests plus P0, compilation and diff checks. Frozen transition and
  `lumi-svc` smoke match; `/opt` matches, no production state/restart occurred,
  flags remain 0, and services have zero restarts/warnings. Next safe E2 slice:
  implement an atomic file-backed adapter around the frozen ledger with temp-dir
  concurrency, crash/fault and restart tests, but deploy no state path/unit and
  do not add endpoint, key provisioning or runtime enablement.
- 2026-08-11 the atomic file-backed adapter for the frozen LUMI shadow replay
  ledger is implemented, tested and deployed as dormant code only.
  `AtomicReplayStore` uses an exclusive `flock`, rejects symlink/non-regular,
  permissive, corrupt/partial and >1 MiB state, and writes canonical snapshots
  via a `0600` temporary file, file fsync, atomic replace and directory fsync;
  lock/state are `0600`. Fault after temp fsync preserves the previous snapshot
  and cleans temp; fault after replace leaves a valid uncertain commit whose
  retry is rejected. Eight concurrent unique consumes have no lost updates;
  six processes racing one nonce yield exactly one acceptance and five replay
  failures. Restart, capacity and expiry behavior remain frozen-ledger exact.
  The full E2 suite passes 224 tests plus P0, compilation and diff checks. An
  ephemeral `lumi-svc` smoke reopened one `0600` snapshot and cleaned itself.
  `/opt` matches; no `/var/lib/lumi` shadow state/path, unit, caller, endpoint,
  key or restart was created. Flags remain 0 and services have zero restarts/
  warnings. LUMI venv still lacks `cryptography`. Next safe E2 slice: freeze a
  strict public-key allowlist/rotation contract with overlap/revocation and
  permission/tamper tests in temporary directories, without provisioning real
  keys, endpoint, configured replay path or runtime enablement.
- 2026-08-11 the strict LUMI shadow public-key allowlist/rotation contract is
  frozen and deployed as dormant code with synthetic fixtures only.
  `shadow-public-keyring.v1` content-hashes an audience-bound, sorted, unique
  allowlist of at most eight 32-byte Ed25519 public keys with ≤1-year validity
  and ACTIVE/RETIRING/REVOKED states; at most one key may be ACTIVE. Immutable
  rotation makes the new key ACTIVE and limits the old key to an explicit
  inclusive 0..300-second overlap. At the frozen 60-second boundary both keys
  resolve; one second later the old key fails. Revocation is immediate and can
  intentionally leave zero ACTIVE keys. Envelope verification through resolved
  synthetic public bytes passes. The read-only loader accepts safe `0644`
  public data but rejects group/world-writable, symlink and corrupt files;
  content/key/time/status/hash tamper fails closed. The full E2 suite passes 242
  tests plus P0, compilation and diff checks; `lumi-svc` fixture smoke passes.
  `/opt` matches, no keyring/replay state exists under `/etc/lumi` or
  `/var/lib/lumi`, no key/dependency/endpoint/unit/restart was added, flags are
  0 and services have zero restarts/warnings. Next safe E2 slice: implement a
  read-only fail-closed transport readiness gate that reports NO_GO until the
  Ed25519 dependency, safe keyring, replay path, feature flags and independent
  backup prerequisites are explicitly satisfied; do not provision or enable
  any of them in that slice.
- 2026-08-11 the read-only fail-closed KAIROS→LUMI shadow transport readiness
  gate is frozen and deployed without runtime wiring. It validates twelve exact
  and internally consistent boolean prerequisites: Ed25519 dependency;
  configured/valid keyring and active key; configured replay path, safe writable
  parent and valid existing snapshot; KAIROS transport, LUMI endpoint, KAIROS
  ingress and Relay producer flags; and backup directories on distinct devices.
  Missing checks produce ordered blockers and `NO_GO`; even all-true synthetic
  GO remains `executionEffect:NONE/actionAllowed:false`. The standalone CLI is
  stdout-only with exit 0/1, reads only existing state/device metadata and never
  creates replay state/lock. Safe configured temp fixtures satisfy file probes
  without byte changes. The full E2 suite passes 264 tests plus P0, compilation
  and diff checks. Production `/opt` matches; `lumi-svc` returns the exact frozen
  12-blocker NO_GO (exit 1): dependency/keyring/replay config missing, all four
  flags disabled, independent backup unavailable. No `/etc/lumi` or
  `/var/lib/lumi` provisioning/state, unit, timer, endpoint or restart was added;
  services remain active with zero restarts/warnings. Before runtime enablement,
  external independent storage and explicit dependency/key authority are still
  required. Next safe keyless E2 slice: freeze a signed LUMI response receipt
  binding request ID, response body hash, service identity and non-executing
  semantics, without private keys, endpoint, network or runtime enablement.
- 2026-08-11 the reverse signed LUMI→KAIROS response receipt is frozen and
  deployed as dormant code with synthetic fixtures only.
  `shadow-response-receipt.v1` binds Ed25519 to the exact advisory request ID,
  canonical request/response SHA-256 values, JSON content type, key ID, epoch,
  nonce, issuer `lumi-shadow`, scope `shadow:advisory-response`, audience
  `kairos-shadow`, and literal `executionEffect:NONE/actionAllowed:false`.
  Its `rr_` ID hashes the canonical unsigned receipt and is included in the
  signature. KAIROS independently validates both request/response wire bodies
  and shared request ID before signature verification; exact replay and 21
  field/body/signature/clock/extra tamper cases fail before nonce consumption.
  A verified response then passes KAIROS dispatch as OK/HOLD while remaining
  non-executing. The full E2 suite passes 286 tests plus P0, compilation and
  diff checks; frozen receipt/verification match under `kairos-svc`. `/opt`
  matches, no key/replay state, endpoint, unit, network, dependency or restart
  was added; flags remain 0 and services have zero restarts/warnings. Next safe
  keyless E2 slice: freeze one hermetic mutual-auth round-trip transcript that
  composes signed request verification, LUMI advisory evaluation, signed
  response receipt verification and KAIROS dispatch with shared IDs/hashes and
  replay/tamper failure semantics, still without network or runtime wiring.
- 2026-08-11 the hermetic KAIROS↔LUMI mutual-auth round-trip transcript is
  frozen. `shadow-mutual-auth-transcript.v1` composes verified signed request →
  independently validated LUMI evaluation → signed response receipt → verified
  KAIROS dispatch, content-hashes the full proof as `rt_…`, and binds the shared
  request ID, exact request/response hashes and receipt ID across every stage.
  Request replay stops before evaluation; response replay stops before dispatch;
  signature, binding and ten transcript tamper cases fail closed. Every nested
  stage and the transcript retain `executionEffect:NONE/actionAllowed:false`.
  The full E2 regression passes 302 tests plus P0, compilation and diff checks.
  No endpoint, network, key, state, dependency, flag or runtime wiring was
  added. Next safe E2 slice: freeze a read-only preflight proof that combines
  the production readiness result with this hermetic self-test and remains
  ineligible while readiness is NO_GO, without enabling any blocker.
- 2026-08-11 the read-only shadow transport preflight proof is frozen and
  deployed as dormant pure code. `shadow-preflight-proof.v1` content-hashes the
  exact ordered readiness checks/blockers and validated mutual-auth transcript
  summary as `pf_…`. Only complete readiness GO plus a valid self-test yields
  `ELIGIBLE`, while every result remains `executionEffect:NONE` and
  `actionAllowed:false`. Invalid self-test, inconsistent readiness and nine
  proof tamper cases fail closed. The frozen production-equivalent proof is
  `INELIGIBLE`: the self-test passes but readiness blockers remain.
  The full E2 regression passes 327 tests plus P0, compilation and diff checks.
  No environment, filesystem, network, key, endpoint, state, flag or restart
  was added. Next safe blocker-reduction slice: add and verify the pinned
  Ed25519 dependency in the isolated LUMI runtime without provisioning keys,
  endpoint, replay state or enabling any feature flag.
- 2026-08-11 the first production E2 readiness blocker was removed without
  enabling transport. `cryptography==49.0.0` is pinned in LUMI requirements and
  installed only in its isolated runtime venv with `cffi==2.1.1` and
  `pycparser==3.0`; `pip check` passes. A real Ed25519 sign/verify smoke under
  UID `lumi-svc` succeeds. The read-only production probe changed exactly one
  check, `ED25519_DEPENDENCY=false→true`, remains `NO_GO`, and blockers fell
  from 12 to 11. The frozen preflight proof was updated to that exact state and
  remains `INELIGIBLE/actionAllowed:false`. No key, keyring, replay state,
  endpoint, flag, network call or service restart was added. Next safe slice:
  freeze and test a two-direction service-key provisioning/ownership runbook
  and fail-closed permission contract before generating any production key.
- 2026-08-11 the two-direction shadow service-key ownership/provisioning
  contract is frozen and dormant. `shadow-service-key-plan.v1` assigns the
  KAIROS request private key only to `kairos-svc`, the LUMI response private key
  only to `lumi-svc`, and exposes only the opposite audience-bound public
  keyring to each verifier. Paths, groups, issuer/audience/scope, key IDs and
  one-year validity are content-hashed as `kp_…`. The provisioner uses
  `O_EXCL|O_NOFOLLOW`, `0640` files, exact `0750` leaf directories, fsync and no
  secret output. Existing/partial/symlink targets fail without overwrite;
  injected faults after each of four writes roll back every new key/keyring.
  Public keyring validation now supports explicit `kairos-shadow` audience
  while retaining default `lumi-shadow` behavior. The full E2 regression passes
  345 tests plus P0, compilation and diff checks. No production key was created.
  Current `/etc/lumi` is intentionally identified as an unsafe ancestor for
  service access (`0700 root:root`). Next safe slice: prepare exact root-owned,
  service-group-traversable key directories, verify access isolation under both
  UIDs, then run the tested one-shot provisioner without enabling endpoints or
  flags.
- 2026-08-11 the production shadow service-key ownership plan was applied
  without enabling transport. `/etc/kairos` and `/etc/lumi` plus their
  `shadow-private`/`shadow-trust` leaves are exact `0750 root:<service-group>`;
  the tested one-shot provisioner created two `0640` Ed25519 private keys and
  two opposite-audience public keyrings. UID-level checks prove each service
  reads only its own private key/trust ring, and root-only local verification
  confirmed both private/public bindings without displaying material. 83 key,
  keyring, readiness and preflight tests pass. KAIROS/LUMI remain active with
  zero restarts/warnings. Readiness remains the exact 11-blocker `NO_GO` because
  keyring/replay paths are not configured, all four feature flags are disabled
  and independent backup is unavailable. No endpoint, network, replay state,
  flag or restart was added. Next safe slice: configure and validate only the
  LUMI request-verification keyring path, keeping replay/endpoint/transport/
  ingress/producer flags disabled; freeze the resulting NO_GO proof before any
  replay-state provisioning.
- 2026-08-11 only the public KAIROS request-verification keyring path was
  configured for LUMI through `e2-shadow-keyring.conf`; source/runtime searches
  confirm this variable is consumed solely by the standalone read-only
  readiness CLI, not an HTTP route or transport. The production keyring is
  readable and valid under `lumi-svc`; its planned `notBefore` was 49 seconds
  ahead of the first probe, which correctly returned `ACTIVE_KEY_UNAVAILABLE`,
  then became active without mutation once that boundary passed. The frozen
  production fixture and preflight proof now contain exactly eight blockers and
  remain `NO_GO`/`INELIGIBLE`, `executionEffect:NONE`, `actionAllowed:false`.
  All replay and four feature flags remain unset/disabled; independent backup
  is unavailable. LUMI/KAIROS were not restarted and remain active with zero
  restarts/warnings. 84 targeted key/readiness/preflight tests and 256 shadow
  regression tests pass; diff and unit verification pass except an unrelated
  existing xray `nobody` warning. Next safe slice: freeze an atomic replay-state
  provisioning/ownership plan for `/var/lib/lumi` and test fresh, existing,
  partial, symlink and crash rollback cases before creating production state;
  do not enable endpoint/transport/ingress/producer flags.
- 2026-08-11 the replay-state provisioning boundary is frozen and applied
  without enabling runtime transport. `shadow-replay-provisioning-plan.v1`
  fixes `/var/lib/lumi/e2-shadow/replay-ledger.json`, adjacent lock,
  `lumi-svc:lumi-svc`, `0700` directory, `0600` files and capacity 10,000.
  Exclusive creation, exact ancestor ownership, existing/partial/symlink
  refusal and rollback after directory/state/lock fault injection are tested.
  Audit found only the top `/var/lib/lumi` inode retained obsolete
  `nobody:nogroup`; all nested live data already belonged to `lumi-svc`. The
  top inode alone was corrected to `0700 lumi-svc:lumi-svc`, preserving the
  existing SQLite data and UID access. The one-shot provisioner then created a
  validated empty ledger and lock; the read-only replay path was added to the
  LUMI drop-in with daemon-reload but no restart. Readiness and frozen preflight
  now have exactly five blockers and remain `NO_GO`/`INELIGIBLE`: all four
  runtime flags are disabled and independent backup is unavailable. 132
  focused and 274 full shadow tests pass; compile/diff/unit checks pass aside
  from the unrelated existing xray `nobody` warning. KAIROS/LUMI remain active
  with zero restarts/warnings. Next safe slice: define and test an independent
  backup/restore evidence contract that rejects same-device paths; do not claim
  readiness or enable any feature flag until genuinely separate storage is
  provided and a restore smoke test passes.
- 2026-08-11 the strict independent backup/restore evidence contract is frozen
  and deployed as dormant pure code. `shadow-backup-restore-evidence.v1`
  requires source, primary and secondary on three distinct device IDs, both
  copies verified, a rehearsed restore, and identical source/copy/restore
  SHA-256 values. Same-device paths or any hash mismatch remain `NO_GO`; probe
  inconsistencies fail validation. Synthetic READY and no-storage NO_GO
  fixtures plus malformed/shared-device/hash tests pass. Production inspection
  confirms the existing primary, secondary and restore directories are all on
  `/dev/sda1` (`st_dev=2049`), so no independent storage exists and none was
  fabricated. The validator is not wired to readiness; no mount, backup,
  evidence file, unit, flag or restart was added. 93 focused and 290 full
  shadow tests pass; production contract smoke under `lumi-svc` returns NO_GO.
  Next safe slice: harden `check_shadow_transport_readiness.py` so
  `INDEPENDENT_BACKUP` can become true only from a narrow root-owned validated
  evidence file, never from directory existence/device comparison alone. With
  no evidence file production must remain the same five-blocker NO_GO.
- 2026-08-11 readiness backup gating is hardened and deployed. The old
  primary/secondary directory-existence and `st_dev` comparison was removed;
  legacy `KAIROS_E2_BACKUP_*` paths cannot satisfy LUMI readiness. Only
  `LUMI_E2_SHADOW_BACKUP_EVIDENCE` can do so, and its loader requires a
  root-owned, LUMI-group, exact `0640`, non-symlink regular file under 16 KiB,
  uses `O_NOFOLLOW` plus inode/device/size TOCTOU checks, fully validates the
  evidence result and accepts only READY. Missing, NO_GO, corrupt, permissive
  and symlink files remain blocked. Production config deliberately has no
  evidence path/file; a live probe including the obsolete directory variables
  still returns the exact five-blocker NO_GO. No unit, flag, backup, mount or
  restart was added. 92 focused and 300 full shadow tests pass; KAIROS/LUMI are
  active with zero restarts/warnings. Next safe code slice is a guarded,
  atomic evidence producer that performs actual copy/hash/restore and refuses
  fewer than three devices. Production execution is blocked until genuinely
  separate storage paths are supplied; never fabricate READY evidence from the
  current single `/dev/sda1` layout.
- 2026-08-11 a guarded atomic backup-evidence producer was added but not run in
  production. It refuses before copying unless the journal source and two
  backup destinations occupy three device IDs, refuses an empty journal,
  delegates to the existing hash-verified two-copy and restore-rehearsal
  operations, and writes only validated READY evidence atomically at `0640`.
  Same-device and atomic-mode tests pass. Production remains unchanged: no
  journal/evidence/bundle exists, all four runtime flags are disabled and live
  readiness retains the same five blockers. The next external prerequisite is
  genuinely independent mounted storage; do not simulate it.
- 2026-08-11 continuation rechecked the external prerequisite read-only. The
  host still has no qualifying independent writable mounts: application state,
  `/root` and `/tmp` remain on `/dev/sda1`; boot, tmpfs and read-only snap loop
  mounts are not backup targets. The live LUMI readiness probe under `lumi-svc`
  remains `NO_GO` with exactly the four disabled runtime flags plus
  `INDEPENDENT_BACKUP_UNAVAILABLE`, `executionEffect:NONE` and
  `actionAllowed:false`. KAIROS and LUMI are active with zero restarts. No
  evidence, bundle, mount, endpoint, flag or service state was changed. Resume
  only after two genuinely independent writable storage paths are supplied.
- 2026-08-11 the owner explicitly deferred the independent E2 storage
  prerequisite; it must remain fail-closed but does not block unrelated roadmap
  work. The next independent E3 offline slice is complete:
  `market-source-comparison.v1` compares 2–8 unique same-market books with
  explicit 5-second freshness, 1-second future-skew and 100-bps divergence
  rules. Stale/future data is never zero-filled; insufficient fresh sources and
  divergence are explicit non-executing statuses. The projection is canonical,
  content-addressed and always `actionAllowed:false`. All 24 E3 contract tests,
  compilation and diff checks pass. No endpoint, credential, network, state,
  flag or service change was made. Next safe E3 slice: a deterministic offline
  paper-trade ledger transition over validated snapshots/estimates.
- 2026-08-11 the deterministic offline E3 paper ledger is frozen.
  `paper-trade-ledger.v1` has content-addressed synthetic genesis balances and
  hash-chained entries; each pure transition recomputes depth fill, applies fee,
  debits/credits both existing assets and returns a new state. Account-bound
  hashed idempotency gives unchanged exact retry and rejects request drift.
  Strict validation replays balances, fees and request bindings from genesis,
  detecting tamper even after consistent re-hashing; JSON restart preserves the
  chain. All 38 E3 tests, compilation and diff checks pass. The contract remains
  `simulationOnly:true/actionAllowed:false`; no I/O, runtime, endpoint, key,
  network, flag or service change exists. Next safe E3 slice: an offline
  risk/limit policy and decision gate for paper intents.
- 2026-08-11 the offline E3 paper risk/limit gate is frozen.
  `paper-risk-policy.v1` content-binds one synthetic account, market allowlist,
  inclusive order/day quote notional, daily count and drawdown limits plus
  5-second market freshness/1-second future skew. `paper-risk-decision.v1`
  binds ledger, snapshot, policy and hashed idempotency; ordered hard checks
  yield `HOLD` on any failure or only `PAPER_ALLOW` when all pass. BUY uses
  quote input and SELL projected gross quote output for notional. All 59 E3
  tests, compilation and diff checks pass. Both verdicts remain
  `paperOnly:true/actionAllowed:false`; no runtime, persistence, endpoint,
  engine, credential, network, flag or service change exists. Next safe E3
  slice: a persisted-intent-shaped offline state machine and reconciliation
  contract with no storage or engine adapter.
- 2026-08-11 the offline E3 paper intent lifecycle/reconciliation contract is
  frozen. `paper-intent-state.v1` content-binds the risk decision, pre-fill
  ledger, snapshot, policy, side, amount, fee and hashed idempotency through a
  hash-chained `READY/HOLD → FILLED → RECONCILED|REVIEW` state machine. Fill
  projects an expected validated ledger; reconciliation independently validates
  the observation, closes exact agreement as `RECONCILED` and mismatch as
  terminal `REVIEW` without auto-retry. Same terminal observation is idempotent;
  drift, wrong key/snapshot/ledger and event/state tamper fail closed across JSON
  restart. All 68 E3 tests, compilation and diff checks pass. No persistence,
  engine adapter, endpoint, credential, network, flag or service change exists;
  every state is `simulationOnly:true/actionAllowed:false`. Next safe E3 slice:
  derive an immutable UTC-day usage ledger only from `RECONCILED` intents so
  risk counters are no longer caller-trusted, then add offline emergency stop.
- 2026-08-11 the derived E3 UTC-day paper usage ledger is frozen.
  `paper-daily-usage.v1` is content-addressed per synthetic account/day and
  hash-chains only validated `RECONCILED` intent evidence with exact
  decision/account/day bindings. `HOLD/FILLED/REVIEW`, wrong scope and tamper
  cannot increment it; exact duplicate is unchanged and evidence drift fails.
  Validation replays count/notional from entries. A risk wrapper now sources
  those two values only from the validated usage ledger instead of caller
  arguments; drawdown remains explicit pending valuation. All 78 E3 tests,
  compilation and diff checks pass. Everything remains pure,
  `paperOnly:true/actionAllowed:false`; no persistence, engine, endpoint,
  credential, network, flag or service change exists. Next safe E3 slice:
  offline emergency-stop/circuit-breaker admission before new READY intents.
- 2026-08-11 the offline E3 emergency-stop/circuit admission boundary is
  frozen. `paper-admission-control.v1` has account-bound `OPEN` and terminal
  `STOPPED/TRIPPED`; exact terminal evidence replay is idempotent, while
  reason/evidence drift and automatic reopen fail closed. Frozen stop reasons
  and circuit signals cover operator/incident/maintenance and reconciliation,
  divergence, permission, rate-limit or unknown-state faults.
  `paper-admission-decision.v1` monotonically composes risk with control: only
  `PAPER_ALLOW + OPEN` yields `ADMIT_PAPER`; all other combinations yield HOLD.
  This admission binding is now mandatory for `open_paper_intent`, so risk alone
  cannot produce READY. All 90 E3 tests, compilation and diff checks pass. No
  persistence, engine, endpoint, credential, network, flag or service change
  exists; all outcomes remain `paperOnly:true/actionAllowed:false`. Next safe
  E3 slice: deterministic equity/drawdown valuation from paper ledger plus
  validated market observations, eliminating the last caller-trusted risk input.
- 2026-08-11 deterministic E3 paper equity/drawdown valuation is frozen.
  `paper-equity-valuation.v1` values every validated ledger asset in one quote:
  cash is 1 and each non-quote asset requires exactly one matching snapshot
  within the 5-second/1-second future window; missing, duplicate, extra, stale
  or future evidence fails. `paper-equity-baseline.v1` content-binds initial
  ledger/equity; `paper-drawdown.v1` derives quote and bps loss for the same
  account/quote and floors gains at zero. The derived risk wrapper now sources
  daily count/notional from usage and drawdown from valuation, eliminating all
  three caller-trusted risk metrics. All 103 E3 tests, compilation and diff
  checks pass. Everything remains pure, `paperOnly:true/actionAllowed:false`;
  no persistence, engine, endpoint, credential, network, flag or service change
  exists. Next safe E3 slice: deterministic P&L/fee reconciliation across
  RECONCILED intents and equity snapshots.
- 2026-08-11 deterministic E3 execution P&L/fee reconciliation is frozen after
  parallel contract and test-matrix reviews. `paper-pnl-reconciliation.v1`
  accepts only exact RECONCILED evidence, requires one appended ledger entry,
  replays the trade from pre-ledger/original book/idempotency, and rebuilds
  pre/post equity with the same price vector/time. It converts the actual output
  fee to quote and separates net execution P&L from gross-before-fee P&L.
  `paper-pnl-journal.v1` enforces unique intents, ledger continuity, exact retry,
  evidence-drift rejection, a 10,000-entry bound and replayed fee/net/gross
  totals. BUY base fees, SELL quote fees, restart, tamper and discontinuity are
  covered. All 113 E3 tests plus compilation/diff checks pass. No runtime,
  persistence, engine, endpoint, credential, network, flag or service change
  exists; every artifact remains `paperOnly:true/actionAllowed:false`. Next safe
  E3 slice: total-P&L snapshot binding baseline/current equity and journal while
  reporting market-and-holding residual separately (not tax-lot realized P&L).
- 2026-08-11 the E3 total mark-to-market P&L snapshot is frozen with prior
  context preserved. `paper-total-pnl-snapshot.v1` binds immutable baseline,
  current validated valuation and the complete continuous P&L journal; baseline
  ledger must equal journal start and current ledger must equal journal head,
  with identical account/quote. It replays total=current-baseline,
  marketAndHolding=total-executionNet and grossBeforeFees=total+fees. The result
  explicitly declares `MARK_TO_MARKET_DECOMPOSITION` and
  `taxLotAccounting:false`, with no misleading realized/unrealized fields.
  Genesis, market-move residual, fee bridge, boundary mismatch and tamper tests
  pass. The full E3 suite is 121 tests; compilation and diff checks pass. No
  runtime, persistence, engine, endpoint, credential, network, flag or service
  change exists; output remains `paperOnly:true/actionAllowed:false`. Next safe
  E3 slice: a read-only offline readiness proof that remains NO_GO until the E2
  prerequisite, production persistence, engine adapter, restricted testnet
  account and runtime reconciliation acceptance are independently satisfied.
- 2026-08-11 the read-only offline E3 readiness proof is frozen.
  `e3-readiness-proof.v1` has fourteen ordered exact booleans: six verified
  offline foundations and eight operational prerequisites. Current deterministic
  CLI output is `OFFLINE_FOUNDATION_COMPLETE/NO_GO`; blockers are E2,
  production persistence, engine adapter, restricted testnet account,
  withdrawal/transfer denial verification, runtime reconciliation acceptance,
  runtime emergency-stop proof and explicit owner approval. Synthetic all-true
  permits only runtime preparation; `runtimeEnableAllowed:false`,
  `actionAllowed:false` and `executionEffect:NONE` are invariant. CLI is JSON
  stdout-only and makes no probes/mutations. All 133 E3 tests plus compilation
  and diff checks pass. No runtime/service/config state changed. Next safe E3
  slice: isolated PostgreSQL schema/repository rehearsal for intents/events,
  usage, admission and P&L, without production migration or readiness change.
- 2026-08-11 isolated E3 PostgreSQL persistence rehearsal is complete but not
  production-ready. Dormant `024_e3_paper_evidence.sql` stores immutable
  validated evidence behind atomic compare-and-append; a disposable PostgreSQL
  17 rehearsal verified retry, continuity and immutability and was removed.
  Production PostgreSQL was never queried or migrated.
- 2026-08-11 the subsequent hermetic E3 boundary is frozen: typed engine
  submission/receipt and fill projection, terminal invocation attempts,
  UNKNOWN resolution without automatic retry, combined engine evidence and
  dormant PostgreSQL persistence, secret-free restricted-testnet capability
  evidence/verifier, and the independently measured verifier artifact,
  deployment, attestation and acceptance chain. A non-executing disposable-host
  rehearsal plan and bounded authorization-receipt contract are also frozen.
  All outputs remain offline/non-executing and cannot satisfy runtime readiness.
  The complete `tests/test_e3_*.py` suite passes 294 tests (1.62 s) using the
  existing LUMI virtualenv. The next boundary is actual rehearsal execution and
  is deliberately blocked until the owner separately approves one specific
  disposable isolated non-production target. General continuation is not that
  approval. Do not install, invoke, probe a CEX, use credentials, mutate
  production, or reinterpret repository fixtures as operational evidence.
- 2026-08-12 the next offline E5 boundary is frozen.
  `native-authenticator-evidence.v1` content-binds the exact synthetic signing
  request/consent chain to hashed device-key identity, challenge and assertion
  evidence. It enforces the consent/request time window, 30-second freshness,
  one-second future skew, monotonic counter advance and consumed-evidence-ID
  replay denial. Hardware backing and user verification remain unverified
  claims: platform attestation, authenticator verification, signing and every
  production/action permission are false. The complete E5 suite passes 46
  tests; compilation and diff checks pass. No SDK, key material, biometric
  data, storage, network, endpoint, service or production state changed. Next
  safe E5 slice: a recovery threat model and pure recovery-policy contract;
  no recovery mechanism or mobile SDK should be selected yet.
- 2026-08-12 the E5 recovery threat model and policy are frozen after owner
  confirmation that a user-held seed is allowed and an independent guardian
  path is preferred. `e5-native-wallet-threat-model.md` identifies seed
  phishing/malware as critical and server substitution, 2-guardian collusion,
  epoch rollback, build compromise, display compromise and recovery loss as
  high priorities. `native-wallet-recovery-policy.v1` defines two independent
  paths: local user-controlled seed restore and delayed 2-of-3 guardians across
  three non-server trust domains. The server cannot receive the seed, hold a
  share, act as guardian or override recovery. A 24-hour delay, notifications,
  active-device veto, local verification, new-device attestation, single-use
  approvals, monotonic epochs and prior-device revocation are mandatory. The
  complete E5 suite passes 63 tests; compilation and diff checks pass. No
  cryptography, SDK, secret/share, storage, network, endpoint, service or
  production state changed. Next safe E5 slice: a pure synthetic recovery-
  attempt state machine binding target device, epoch, delay, guardian approvals
  and veto; it must remain non-executing.
- 2026-08-12 the synthetic E5 recovery-attempt state machine is frozen.
  `native-wallet-recovery-attempt.v1` binds wallet, active/target device,
  synthetic target attestation and exactly-next recovery epoch. Hash-chained
  events accept only distinct policy guardians and bind evidence to the target
  and epoch; exact retry is idempotent and evidence drift fails. The only
  transitions are `PENDING_DELAY → ELIGIBLE_OFFLINE`, `VETOED` or `EXPIRED`.
  Eligibility needs 2-of-3 approvals plus 24 hours; active-device veto works
  only during the delay. Even eligible state cannot install authority, revoke
  the old device, execute recovery or allow production action. The complete E5
  suite passes 84 tests; compilation and diff checks pass. No SDK, secret/share,
  storage, network, endpoint, service or production state changed. Next safe E5
  slice: an offline-only recovery-completion proposal requiring independently
  verified new-device and revocation evidence, without installing authority.
- 2026-08-12 the native-wallet checkpoint signature algorithm selection is
  frozen in ADR 0002 and a read-only core/UniFFI contract. The selected profile
  is BIP340 Schnorr/secp256k1 with 32-byte x-only keys, 64-byte signatures,
  32-byte digests and domain `OBSIDIAN_CHECKPOINT_APPROVAL_V1`, retaining the
  locked `bitcoin` 0.32.102, `secp256k1` 0.29.1 and `secp256k1-sys` 0.10.1
  graph. This does not implement or enable verification, install keys, expose
  signing, or establish checkpoint/chain trust. All 158 E5/landmine tests,
  9 Rust tests, strict Clippy, formatting, RustSec audit and diff checks pass.
  No production state changed. Next safe slice: pin the official BIP340 CSV
  vectors by source revision and SHA-256, then build only a verification parser
  and mutation-test harness; do not add real trust keys or activate trust.
- 2026-08-12 the official BIP340 CSV is now vendored byte-exact at bitcoin/bips
  revision `c38071c8c45a1fc50cecaac0d82d99e3bbd56911`, SHA-256
  `34c9d1d9c3a88d524bc80778540dc43f8306ec249a7485293063c376db851c2d`,
  with source/license provenance. A strict test-only Rust parser covers all 19
  rows; the existing secp256k1 API verifies all 15 rows in the selected exact
  32-byte-digest profile, while the four arbitrary-message vectors are
  explicitly classified outside that profile. Key/message/signature, malformed
  length, schema/result and hex mutations fail closed. Rust workspace tests
  (13 total), strict Clippy, RustSec audit and 159 E5/landmine tests pass.
  Runtime verifier/signing APIs, trust keys, checkpoint trust and action remain
  absent/false. Next safe slice: define and test a pure application-level
  checkpoint approval digest/domain-binding verifier contract, still test-only
  and without installing keys or changing any trust state.
- 2026-08-12 the application-level checkpoint approval signature-message
  binding is frozen in ADR 0003 and a test-only Rust harness. It uses BIP340
  tagged SHA-256 with domain `OBSIDIAN_CHECKPOINT_APPROVAL_V1` over an ordered,
  length-prefixed binary payload binding schema, algorithm, approval/artifact/
  ceremony digests, key epoch, individual signer slot and expiry. All integer
  fields are big-endian and text-boundary SHA-256 is canonical lowercase hex.
  A fixed golden digest, every-field/domain mutation, malformed context and
  concatenation-ambiguity tests pass. The harness contains no key/signature or
  verification call and is absent from library `src` and UniFFI. The Rust
  workspace now passes 17 tests, strict Clippy, formatting and an offline
  RustSec audit; the full E5/landmine suite passes 160 tests. No runtime API,
  key, verifier, trust or production state changed. Next safe slice: freeze a
  test-only verification decision/result matrix using only non-trust fixtures,
  separating malformed binding, unknown/stale key epoch, invalid signature and
  quorum outcomes; do not install trust keys or expose a runtime verifier.
- 2026-08-12 the checkpoint verification decision matrix is frozen in ADR 0004
  and a symbolic test-only Rust harness. It deterministically separates, in
  fail-closed precedence order, malformed binding, unknown/zero/future epoch,
  stale epoch, expiry, unknown signer, duplicate signer, malformed signature,
  invalid signature, insufficient quorum and
  `QUORUM_SATISFIED_NON_AUTHORITATIVE`. Exactly two distinct claims from three
  active slots model the frozen 2-of-3 policy; zero and future epochs are never
  accepted. Every outcome, including quorum, keeps key installation,
  checkpoint/chain trust and action/production authority false. The harness has
  no key/signature bytes or crypto call and is absent from library `src` and
  UniFFI. Rust passes 21 tests, strict Clippy, formatting and offline RustSec;
  E5/landmine passes 161 tests. No runtime or production state changed. Next
  safe slice: define a test-only synthetic active-key-set evidence contract that
  binds epoch, signer IDs and x-only public-key commitments to the reviewed
  ceremony without installing or trusting those keys; runtime verification
  remains blocked.
- 2026-08-12 the synthetic active checkpoint key-set evidence contract is
  frozen in ADR 0005 and a test-only Rust harness. Review found that the prior
  ceremony's independently sorted key-ID and key-material commitment lists bind
  only two sets, not the mapping between them; parallel-list order must never be
  treated as authorization. The new evidence binds ceremony digest, epoch,
  algorithm and three sorted `signer ID → canonical x-only public key` records;
  each commitment is domain-separated and the resulting set must exactly match
  the ceremony set. A separate content digest binds that mapping plus two
  reviewer claims. Mapping permutation, ceremony/epoch/signer/commitment drift
  and invalid x-only keys fail closed. Reviewer authentication, key install,
  active authority, checkpoint/chain trust and production action remain false.
  Fixtures use only public non-trust BIP340 keys; there are no private keys,
  signing calls, runtime sources or UniFFI changes. Rust passes 24 tests, strict
  Clippy, formatting and offline RustSec; E5/landmine passes 162 tests. No
  production state changed. Next safe slice: define a synthetic, offline
  key-set review-acceptance bundle that binds the ceremony, mapping evidence,
  algorithm selection and distinct reviewer trust-domain claims, while keeping
  reviewer authentication and key installation explicitly false.
- 2026-08-12 the offline checkpoint key-set review-acceptance proposal is
  frozen in ADR 0006 and a test-only Rust harness. It binds the exact ceremony,
  mapping-evidence and frozen algorithm-selection digests, epoch, three signer
  slots, a maximum 24-hour validity window and two reviewer-attestation hashes.
  Reviewer IDs must be distinct/sorted, must not overlap signer slots and must
  claim different allowlisted domains (`independent_security`,
  `offline_ceremony_observer`, `reproducible_build`). Digest/epoch/time drift,
  expired/oversized windows, same-domain reviewers, signer-reviewer overlap and
  attestation drift fail closed. Success is explicitly
  `REVIEW_CLAIMS_BOUND_NON_AUTHORITATIVE`: attestation hashes are not signatures,
  reviewers remain unauthenticated, the bundle is not accepted and keys/trust/
  action remain false. There are no key/signature bytes or crypto calls and no
  library/UniFFI/runtime changes. Rust passes 27 tests, strict Clippy,
  formatting and offline RustSec; E5/landmine passes 163 tests. No production
  state changed. Next safe slice: threat-model and freeze a technology-neutral
  reviewer identity/attestation policy defining independent trust roots,
  freshness, replay prevention and revocation evidence; do not select or
  install real reviewer credentials yet.
- 2026-08-12 the reviewer identity/attestation threat model and structural
  policy are frozen after the owner confirmed that independence means separate
  administrative domains, credential roots and recovery authorities, not
  separate accounts in shared infrastructure. The AppSec report is
  `native-wallet-reviewer-identity-threat-model.md`; top future risks are false
  domain independence, evidence replay, revocation rollback, CI substitution
  and unauthenticated domain labels. ADR 0007 requires two distinct roots and
  recovery authorities, at most one automated reviewer, 10-minute attestations,
  one-second future skew, single-use evidence IDs, exact bundle/challenge
  binding and monotonic revocation epochs. A test-only Rust policy rejects
  shared domain/root/recovery control, two automated reviewers, expiry, replay,
  revoked roots and epoch rollback. Passing structure remains non-authoritative:
  attestations/reviewers are unverified and acceptance, keys, trust and action
  stay false. The security-threat-model workflow shaped the explicit assets,
  boundaries, abuse paths, risk ranking and mitigations. Rust passes 30 tests,
  strict Clippy, formatting and offline RustSec; E5/landmine passes 164 tests.
  No credential technology, real root, signature, network, runtime or production
  state changed. Next safe slice: a read-only technology-selection ADR comparing
  human offline reviewer and automated reproducible-build attestation options
  against ADR 0007, with standards/provenance pinned but no SDK, credential or
  trust-root installation.
- 2026-08-12 reviewer attestation technology comparison is frozen in ADR 0008.
  Human review selects `WEBAUTHN_L3_CTAP22_ROAMING_ES256_UV`: a device-bound
  roaming authenticator with exact RP/origin/challenge, UP+UV and pinned
  enrollment key; `signCount` is advisory because compliant authenticators may
  keep it zero, so replay still depends on the single-use evidence ledger.
  OpenSSH FIDO is rehearsal fallback, PIV a conditional managed-enterprise
  option and OpenPGP is not selected. Automated review selects
  `INTOTO_V1_SLSA_PROVENANCE_V1_DSSE_1_0_2_ED25519`: exact in-toto subject,
  SLSA builder/buildType/source/dependencies/external-parameter expectations,
  DSSE payload-type binding and an independently controlled Ed25519 build root.
  Reproducible byte equality remains a separate required check; provenance is
  not treated as equality proof. Sigstore is supplemental transparency only,
  never the offline trust root, because OIDC/CA/log control planes would add
  shared online dependencies. Standards are pinned by version/date/tag. A
  read-only test contract preserves both selections and all capability flags
  false. Rust passes 32 tests, strict Clippy, formatting and offline RustSec;
  E5/landmine passes 165 tests. No SDK, vendor, credential, root, parser,
  network, runtime or production state changed. Next safe slice: freeze exact
  synthetic structural envelopes and fail-closed expectation matrices for the
  selected WebAuthn assertion and in-toto/SLSA/DSSE provenance profiles, without
  cryptographic verification or dependency installation.
- 2026-08-12 the owner explicitly approved using the ADR 0008 technology
  selections going forward. Treat WebAuthn/CTAP roaming hardware credentials as
  the human-reviewer target and in-toto/SLSA/DSSE with an independent Ed25519
  build root as the automated-reviewer target. This confirms architecture only;
  it does not authorize SDK installation, credential issuance, trust-root
  installation, network enrollment, runtime activation or production changes.
- 2026-08-12 exact synthetic structural envelopes for both selected reviewer
  profiles are frozen in ADR 0009 and test-only Rust harnesses. The WebAuthn
  envelope binds evidence ID, `webauthn.get`, exact challenge/origin/RP hash,
  public-key credential, ES256, pinned credential/key fingerprints, UP+UV and
  device-bound BE/BS=false; only digests of client/authenticator/signature bytes
  are present. Zero and nonzero `signCount` are equally non-authoritative. The
  automated envelope binds DSSE `application/vnd.in-toto+json`, in-toto
  Statement v1, SLSA provenance v1, subject/rebuild digest equality, exact
  builder/build type/source revision, sorted dependencies, exact allowlisted
  external parameters, payload/root/signature digests. Context drift, unknown
  parameters and dependency reorder/duplication fail closed. Structural success
  verifies no signature, enrollment, builder or reproducible build and grants no
  acceptance/action. No signature bytes, public credential keys, parser, SDK or
  runtime surface exists. Rust passes 38 tests, strict Clippy, formatting and
  offline RustSec; E5/landmine passes 166 tests. No production state changed.
  Next safe slice: perform a read-only dependency/provenance/license/security
  comparison for parsers and verifiers capable of these exact profiles, pin a
  minimal shortlist and official conformance fixtures, but install nothing and
  keep implementation/activation blocked.
- 2026-08-12 the read-only checkpoint attestation verifier shortlist is frozen
  in ADR 0010 and a test-only invariant. Human RP verification selects stable
  `webauthn-rs` 0.5.5; `passkey-rs` is rejected because it implements the
  client/authenticator roles, and a hand-built WebAuthn verifier is rejected as
  security-critical reimplementation. Automated verification selects strict
  local DSSE 1.0.2 PAE/data modeling plus `ed25519-dalek` 3.0.0; early/unstable
  `in_toto_attestation` 0.1.0 is retained only as a schema-binding candidate,
  never a signature or policy verifier. DSSE v1.0.2, in-toto v1.2.0 and SLSA
  v1.2 revisions are pinned. Audit found no public standards-owned WebAuthn
  server-verifier vector corpus, so WPT/upstream library tests must not be
  mislabeled as official conformance; a reviewed local mutation corpus and the
  applicable FIDO conformance process remain gates. No dependency, fixture,
  parser, credential or root was installed and Cargo manifests/lock remain
  unchanged. Rust passes 40 tests, strict Clippy, formatting and offline
  RustSec; E5/landmine passes 167 tests. Next safe slice: prepare an isolated,
  non-runtime dependency-graph rehearsal and byte-exact automated-lane fixture
  provenance manifest; keep WebAuthn fixtures blocked pending corpus design and
  do not add UniFFI or production capability.
- 2026-08-12 the WebAuthn server-verifier corpus policy is frozen in ADR 0011
  and a test-only 24-case matrix. Because no public standards-owned RP corpus
  exists, the project will use deterministic synthetic assertions with
  standards-derived expectations written before results, immutable provenance,
  two non-generator reviewers and differential testing against an independently
  maintained oracle. The oracle is not authority: any disagreement blocks
  release and implementation majority voting is forbidden. The matrix covers
  two non-authoritative ES256/UV positives and 22 single-dimension fail-closed
  mutations across context, flags, credential/key, parser, signature,
  enrollment and replay boundaries. Test private keys may exist only in an
  offline generator and cannot be checked in or share reviewer infrastructure.
  FIDO conformance remains a separate gate and the local corpus cannot claim
  certification. No fixture, key, parser, dependency or runtime surface was
  added. Rust passes 42 tests, strict Clippy, formatting and offline RustSec;
  E5/landmine passes 168 tests. Next safe slice: define the deterministic
  corpus manifest/schema and offline generator review protocol without creating
  keys or assertions; independently pin byte-exact automated-lane standards
  fixtures and provenance.
- 2026-08-12 the attestation corpus manifest and source-provenance boundary is
  frozen in ADR 0012. A strict Draft 2020-12 JSON Schema requires at least 24
  WebAuthn RP cases, pre-sealed expectations, separate artifact/context/
  enrollment/recipe hashes, a pinned network-disabled generator, exactly two
  non-generator reviewers, two implementation results over the identical
  corpus digest, no private keys and all authority flags false. The generator
  protocol requires an ephemeral encrypted offline workspace, clean byte-exact
  regeneration, key destruction, independent review and quarantine on any
  oracle/verifier disagreement; no generator executable exists yet. A
  machine-readable provenance file pins byte-exact SHA-256 values for the DSSE
  1.0.2 protocol/reference vector, in-toto 1.2.0 Statement v1 and SLSA 1.2 CUE
  schema/verification rules at immutable revisions. These sources are not
  vendored and prove no conformance. No assertion, key, dependency, parser,
  runtime or UniFFI surface was added. Rust passes 42 tests, strict Clippy,
  formatting and offline RustSec; E5/landmine passes 169 tests. Next safe
  slice: create a read-only isolated Cargo dependency-graph rehearsal manifest
  and evaluate transitive licenses/advisories/platform impact without merging
  it into the native-wallet workspace or implementing verification.
- 2026-08-12 the isolated attestation dependency-graph rehearsal is complete in
  ADR 0013 with three standalone locked Cargo packages and a machine-readable
  result. `webauthn-rs` 0.5.5 resolves to 116 registry packages and passes
  RustSec/license-metadata checks, but its host build correctly remains blocked:
  `openssl-sys` is mandatory through core/attestation paths and requires system
  OpenSSL discovery. Do not hide this with host packages or vendored OpenSSL;
  integration requires explicit pinned iOS/Android crypto-provider builds and
  MPL/compound-license distribution review. The automated-minimal graph is 36
  packages, builds offline and has no RustSec or missing-license findings; it
  remains the sole candidate. Adding early `in_toto_attestation` expands the
  graph to 83 (+47) and adds protobuf codegen, so that profile is deferred/
  rejected unless strict local models prove insufficient. Rehearsal target
  artifacts (~580 MiB) were cleaned; only manifests, exact lockfiles and results
  remain. None is part of the native workspace and every rehearsal capability
  is false. Native Rust passes 42 tests, strict Clippy, formatting and offline
  RustSec; E5/landmine passes 170 tests. Next safe slice: freeze a minimal DSSE
  parser/verifier API and ordered fail-closed decision matrix in test-only form,
  using no dependency calls or raw signatures yet; separately define the mobile
  WebAuthn crypto-provider acceptance matrix before any cross-target build.
- 2026-08-12 the minimal DSSE verifier contract and mobile WebAuthn provider
  gates are frozen in ADR 0014 and symbolic test-only matrices. DSSE processing
  is strictly ordered: bounded/strict outer JSON, exact payload type/canonical
  Base64/one 64-byte signature, externally selected non-revoked root epoch,
  DSSE 1.0.2 PAE and signature verification over exact decoded bytes, then a
  single strict parse of those same verified bytes followed by Statement/SLSA/
  builder/dependency/rebuild/freshness/replay policy. `keyid` never chooses a
  root, reserialization cannot replace signed bytes and even full success is
  `VERIFIED_NON_AUTHORITATIVE`. The mobile matrix requires locked iOS/Android
  device and test-target builds, no ambient discovery/fallback, corpus parity,
  reproducible size-bounded binaries, update/CVE/license review and declared
  dynamic linkage. The current `webauthn-rs 0.5.5` OpenSSL path remains blocked;
  even a synthetic all-green provider grants no integration, credential or
  authentication capability. No bytes, keys, parser/crypto calls, dependencies,
  targets, SDKs, runtime or UniFFI changed. Rust passes 47 tests, strict Clippy,
  formatting and offline RustSec; E5/landmine passes 171 tests. Next safe slice:
  pin exact parser resource limits and strict JSON/Base64 lexical rules in a
  test-only contract, then vendor only the already hashed DSSE reference vector
  after independent byte/license verification; still do not verify signatures.
- 2026-08-12 DSSE parser limits, strict lexical rules and safe reference-fixture
  handling are frozen in ADR 0015. Exact pre-allocation gates are 256 KiB
  envelope, 192 KiB decoded payload, 128-byte payload type/key-id hint, outer/
  payload JSON depths 4/16, 8,192 tokens, 4 KiB strings, exactly one 64-byte
  signature, one subject, four digests/resource, 256 dependencies and 32
  external parameters. JSON must be UTF-8 without BOM, duplicates/unknown local
  fields/floats/unpaired surrogates fail; Base64 is canonical standard RFC 4648
  with padding and zero unused bits. Inspection confirmed the pinned upstream
  DSSE Python reference contains executable code and a published test signing
  scalar, so it was not vendored. Instead a hash-pinned Apache-2.0-derived PAE
  fixture contains only public payload/type/expected PAE, no signature or key,
  and explicitly makes no official-conformance claim. The test harness performs
  metadata/lexical checks and PAE byte construction only—no JSON parser, decode,
  crypto or verification call. Native Cargo/runtime/UniFFI remain unchanged.
  Rust passes 50 tests, strict Clippy, formatting and offline RustSec;
  E5/landmine passes 172 tests. Next safe slice: define strict local DSSE outer
  and in-toto/SLSA data models plus duplicate-key detection strategy in an
  isolated parser rehearsal using the minimal locked graph; keep Ed25519 calls,
  roots and runtime integration absent.
- 2026-08-12 the strict local DSSE/in-toto/SLSA typed-parser rehearsal is
  complete in the isolated locked `automated-minimal` package and ADR 0016.
  Every selected object uses `deny_unknown_fields`; Serde rejects duplicate
  known fields at outer and nested depths. Separate envelope and verified-
  payload APIs reject empty/BOM/invalid UTF-8/oversize input before typed parse,
  and enforce one signature/subject plus bounded key-id/dependencies. Tests
  cover exact models, duplicate/unknown nested fields and input boundaries.
  Signature text is opaque: no decoding, PAE, Ed25519 import/call, root or
  authority exists, and `VERIFIER_IMPLEMENTED` is false. This is intentionally
  not integration-ready: an allocation-safe lexical preflight must still apply
  depth/token/string limits before Serde, followed by canonical Base64 and
  semantic policy while preserving exact signed bytes. Rehearsal tests, strict
  Clippy, formatting and its offline RustSec audit pass; 175 MiB target output
  was cleaned. Native Rust remains 50 passing tests; E5/landmine passes 173.
  Next safe slice: implement and fuzz/property-test an allocation-safe lexical
  JSON preflight in the isolated rehearsal, with no payload decode or crypto;
  then integrate canonical payload Base64 decoding while preserving original
  bytes and keeping signature decoding/verification blocked.
- 2026-08-12 the isolated allocation-safe JSON preflight and exact payload-only
  Base64 slice are complete in ADR 0017. Before Serde, a single-pass scanner
  uses a fixed 16-entry stack and scalar counters to enforce the frozen byte,
  depth, token and encoded-string limits and reject mismatched containers,
  control characters, bad/incomplete escapes and incomplete JSON state. Serde
  remains the strict syntax/duplicate/unknown-field authority. An exhaustive
  two-byte test covers all 65,536 inputs without panic. `payload` decoding now
  checks encoded size before allocation, bounds decoded size and requires exact
  standard-padded RFC 4648 re-encoding, preserving the returned signed bytes;
  omitted padding, URL-safe alphabet, whitespace and non-zero padding bits fail.
  `sig` is still opaque: there is no signature decode, PAE, Ed25519 call, root,
  runtime or UniFFI integration and `VERIFIER_IMPLEMENTED` remains false.
  Isolated tests (6), strict Clippy/format/RustSec, native Rust tests (50),
  native strict Clippy/format/RustSec and E1-E5/landmine tests (603) pass;
  178.4 MiB rehearsal output was cleaned. Next safe slice: construct DSSE 1.0.2
  PAE from the exact payload bytes and add closed semantic URI/digest/order
  policy in the isolated rehearsal, while retaining a symbolic signature
  outcome and making no Ed25519 verification call.
- 2026-08-12 exact DSSE 1.0.2 PAE construction and the closed semantic policy
  are complete in the isolated rehearsal and ADR 0018. PAE uses checked
  capacity arithmetic, decimal byte lengths, the original payload-type string
  and exact decoded payload bytes without JSON normalization; the safe public
  reference matches byte-for-byte and a non-UTF-8 test proves byte preservation.
  The outer envelope now requires the exact in-toto MIME type and ASCII key-id
  hint. After a test-only symbolic signature-success gate, policy requires
  exact Statement/SLSA types, subject/digest, build type, builder, profile,
  target and ordered dependencies. Expected and observed URI/digest forms are
  closed, dependency URIs unique, and drift/reordering/uppercase digest fails.
  The symbolic outcome is unit-test-only; `sig` remains opaque and there is no
  signature decode, key/root, Ed25519 call, authority, runtime or UniFFI change.
  Isolated tests (9), strict Clippy/format/RustSec, native Rust tests (50),
  native strict Clippy/format/RustSec and E1-E5/landmine tests (603) pass;
  187.7 MiB rehearsal output was cleaned. Next safe slice: add bounded canonical
  decoding of the single signature to exactly 64 bytes and model externally
  selected root epoch/revocation gates symbolically; do not let `keyid` select
  authority and do not call Ed25519 until independently pinned public vectors
  and mutation cases are reviewed.
- 2026-08-12 canonical signature-shape decoding and external root epoch gates
  are complete in the isolated rehearsal and ADR 0019. The sole `sig` must be
  exactly 88 encoded bytes, decode as standard padded RFC 4648 to exactly 64
  bytes and reproduce the original text on re-encoding; omitted padding,
  whitespace, URL-safe alphabet, non-zero unused bits and length drift fail.
  The result is a fixed-width read-only byte container and performs no crypto.
  Separately, an API with no `keyid` or key-byte parameter checks an externally
  selected policy/epoch snapshot and distinguishes malformed expectation,
  unknown policy, stale/future epoch and revocation. Tests prove absent,
  matching-looking and attacker-controlled `keyid` hints cannot affect it.
  There is still no public key, Ed25519 import/call, trust installation,
  authority, runtime or UniFFI change and `VERIFIER_IMPLEMENTED` remains false.
  Isolated tests (11), strict Clippy/format/RustSec, native Rust tests (50),
  native strict Clippy/format/RustSec and E1-E5/landmine tests (603) pass;
  175.3 MiB rehearsal output was cleaned. Next safe slice: independently pin a
  verification-only Ed25519 public corpus (public key/message/signature only,
  no seed/private scalar), record provenance/license/hash and mutation cases;
  only after that review may the isolated package call `ed25519-dalek`, still
  without runtime integration, installed roots or authoritative success.
- 2026-08-12 the verification-only Ed25519 corpus is pinned in ADR 0020 and
  the isolated rehearsal. It contains only RFC 8032 Section 7.1 TEST 2 public
  key/message/signature fields, a byte-exact SHA-256 provenance record and
  seven predeclared single-field invalid mutation recipes; no RFC secret key,
  generated key or seed was copied. The corpus remains
  `PINNED_FOR_INDEPENDENT_REVIEW`: no `ed25519-dalek` call, key parsing, root,
  authority, runtime or UniFFI integration was added. Corpus tests pass 3/3;
  isolated Rust passes 11 tests, native Rust passes 50 tests, strict format/
  Clippy and both no-fetch RustSec audits pass, and the full landmine gate is
  clean in the bot runtime. The 175.3 MiB rehearsal target was cleaned. Next
  safe step: obtain two independent public-field/digest/license reviews, then
  add a verification-only `ed25519-dalek` call in the isolated package and
  execute the frozen valid/invalid matrix; success must remain non-authoritative.
- 2026-08-12 the Ed25519 corpus independent-review gate is frozen in ADR 0021.
  A request binds the corpus, provenance and ADR 0020 by exact SHA-256 and
  requires nine checks from two distinct non-generator reviewer identities in
  distinct trust domains. The closed response schema requires an explicit
  decision and externally authenticated evidence, but authentication remains
  an unselected placeholder, so structural completeness cannot grant
  permission. No reviewer response, identity or credential is checked in;
  `crypto_call_allowed` and runtime integration remain false. Seven corpus/
  review tests pass, isolated and native Rust tests plus strict Clippy/format,
  no-fetch RustSec, landmine and diff checks pass. Next safe step requires two
  real independent reviews and selection of an externally verified reviewer
  authentication scheme; do not fabricate approvals or call `ed25519-dalek`
  before that gate is genuinely satisfied.
- 2026-08-12 ADR 0022 selects the already approved human reviewer profile
  `WEBAUTHN_L3_CTAP22_ROAMING_ES256_UV` for Ed25519 corpus reviews and removes
  the generic authentication placeholder. A hash-bound contract defines an
  exact length-prefixed challenge over the review request, reviewer/domain,
  evidence ID, credential/recovery roots, revocation epoch and ten-minute
  validity window; a fixed test vector prevents cross-language drift. Pair
  policy now also rejects shared evidence IDs, credential roots and recovery
  authorities. Assertion bytes remain external and digest-referenced. No RP,
  origin, credential, authenticator, assertion, revocation source or verifier
  was installed, so reviewer authentication and crypto/runtime permission are
  still false. Eight corpus/review tests, isolated/native Rust, strict Clippy/
  format, both no-fetch RustSec audits, landmine and diff checks pass. Next safe
  step is to freeze the bounded WebAuthn assertion-envelope import and external
  verification-result contract for this review flow; do not enroll credentials
  or treat structural fixtures as authentication.
- 2026-08-15 ADR 0023 freezes the bounded WebAuthn assertion-import envelope
  and external verifier-result contract for Ed25519 corpus reviews. Assertion
  fields use canonical unpadded base64url with decoded limits (8 KiB client
  data, 1 KiB credential/authenticator/signature, 64-byte user handle and
  16 KiB envelope); the separate closed result binds the envelope/challenge,
  evidence ID, credential root/revocation epoch, exact RP/origin and verifier
  identity/build, with ordered fail-closed checks. No assertion, credential,
  RP, verifier or result is installed, and result authentication/attestation is
  intentionally undefined, so reviewer authentication, Ed25519 calls and
  runtime/UniFFI integration remain false. Ten contract tests and 11 isolated
  Rust tests pass; JSON and diff checks are clean. Next safe slice: shortlist
  and threat-model result-authentication mechanisms and verifier build identity
  sources before selecting either; do not import a real assertion or credential.
- 2026-08-15 ADR 0024 freezes a two-axis shortlist and threat model for the
  corpus-review WebAuthn verifier. Result authentication candidates are local
  pinned execution, dedicated DSSE-signed results, hardware workload quotes
  and supplemental Sigstore bundles; build identity candidates separately
  cover reproducible binary digests, in-toto/SLSA provenance, hardware
  measurement and insufficient-alone package/image digests. The contract
  forbids collapsing provenance, reproducibility and actual execution into one
  claim and requires cross-binding request/assertion/challenge/evidence,
  credential/revocation, verifier build/policy, time window and caller nonce.
  Threats include unsigned green-result forgery, signed wrong binaries, digest
  substitution, replay/rollback, parser differential, shared reviewer roots and
  compromised hosts. Nothing is selected and no trust material or runtime
  surface was added; reviewer authentication, crypto calls and integration stay
  false. Six new and ten preceding contract tests pass; JSON/diff checks are
  clean. Next safe slice: define a fail-closed selection scorecard and minimum
  independent-root/recovery evidence for the two shortlisted primary patterns,
  still without choosing one or importing real evidence.
- 2026-08-15 ADR 0025 freezes a conjunctive, fail-closed selection scorecard
  for local pinned execution and DSSE-signed verifier results. Ten common gates
  require exact closed bytes/cross-binding, signed provenance, two independent
  byte-identical builds, policy identity, atomic freshness/replay handling,
  parser parity, independent administration, rehearsed recovery and dependency/
  license review. Local execution adds private peer-authenticated IPC, measured
  executable/policy/dependencies and host separation; DSSE adds a dedicated
  result key, consumer-selected root/epoch/revocation, signer-to-measured-build
  enforcement and compromise recovery. Any `FAIL`, `UNKNOWN`, `NOT_EVALUATED`
  or missing evidence blocks selection; there is no weighted bypass or automatic
  winner. A closed independence-evidence schema requires distinct reviewer,
  credential, recovery, verifier, result, host, builder and issuer roots across
  and within reviews. All gates remain unevaluated, issuer authentication is
  undefined, and no real evidence/trust/runtime surface exists. Six new and 16
  preceding contract tests pass; JSON/diff checks are clean. Next safe slice:
  define the independence-evidence issuer authentication shortlist and exact
  evidence challenge/cross-binding contract without selecting or enrolling an
  issuer.
- 2026-08-15 ADR 0026 freezes the independence-evidence issuer authentication
  shortlist and exact challenge. The length-prefixed SHA-256 challenge binds
  the independence schema, scorecard, evidence record, issuer/domain,
  consumer-selected authentication root, separate recovery authority,
  revocation epoch, single-use nonce and ten-minute window; a fixed vector and
  mutation tests prevent field drift. Primary candidates are 2-of-3 threshold
  DSSE under independent offline roots and two human WebAuthn issuers with
  separate roaming credential/recovery roots; hardware-attested issuance is
  deferred. At least two issuers must differ by identity, trust domain, auth
  root, recovery authority and host failure domain, and may not administer the
  reviewed reviewer/verifier/builders. No option or issuer is selected/enrolled
  and no key/assertion/evidence/runtime surface exists; all permission flags
  remain false. Six new and 22 preceding contract tests pass; JSON/diff checks
  are clean. Next safe slice: freeze the hash-only supporting-evidence bundle
  and conflict-of-control matrix that issuers must review, without importing
  personnel data, credentials or operational evidence.
- 2026-08-15 ADR 0027 freezes a hash-only supporting-evidence bundle and
  conflict-of-control matrix for independence issuers. The closed manifest
  requires exactly 14 unique, external digest-referenced artifact kinds covering
  reviewer/credential/recovery, verifier/result roots, two builders, build
  equality/provenance, host failure domain, issuer control and the matrix; all
  artifacts must cover the bundle's at-most-24-hour lifetime and the manifest
  declares no personal data. The matrix evaluates direct and transitive control,
  activation/recovery/revocation, policy/build/runtime modification, self-
  issuance, shared roots/hosts and undisclosed delegation within and across
  reviews. Only `SEPARATE_WITH_EVIDENCE` passes; conflict, unknown, missing,
  duplicate/expired evidence or absent rows block without waiver or scoring.
  No real artifact, identity or matrix is present and all acceptance/runtime
  flags remain false. Six new and 28 preceding contract tests pass after fixing
  one test-only JSON Schema property lookup; JSON/diff checks are clean. Next
  safe slice: define a conjunctive selection scorecard comparing threshold DSSE
  and dual-WebAuthn issuer authentication, still selecting neither and adding
  no keys, issuers or real evidence.
- 2026-08-15 ADR 0028 freezes the conjunctive selection scorecard for threshold
  DSSE versus dual-WebAuthn independence-issuer authentication. Ten common
  mandatory gates cover exact challenge/bundle/matrix binding, two-issuer and
  subject-control independence, atomic freshness/replay, root recovery, parser
  parity, privacy/retention and dependency/incident readiness. Threshold DSSE
  adds unique 2-of-3 roots, signer/recovery role separation, exact-byte DSSE and
  witnessed offline ceremonies; WebAuthn adds two witnessed independent
  enrollments, exact no-fallback RP/origin, ES256 UP/UV non-backup flags and
  human collusion controls. Any non-PASS or missing evidence blocks; even two
  passing options require a later smaller-surface ADR. Both remain unevaluated
  with explicit missing-root/RP/parser/recovery blockers, and no real evidence,
  keys or runtime permission exists. Six new and 34 preceding contract tests
  pass; JSON/diff checks are clean. Next safe slice: freeze the hash-only audit,
  privacy, retention and deletion-rehearsal contract required by common gate
  `i09`, without importing or deleting any real personnel/credential evidence.
- 2026-08-15 ADR 0029 freezes audit minimization, privacy, retention and
  deletion-receipt contracts for issuer scorecard gate `i09`. Public synthetic
  contracts contain no real identities; hash-only audit metadata is limited to
  closed IDs/timestamps/decisions/reason codes/digests and retains for seven
  365-day years. External sensitive review copies are encrypted, outside the
  repository and ordinary backups, and live at most 24 hours; WebAuthn assertion
  copies live at most ten minutes. Names/contact data, credential/user handles,
  assertion/artifact bytes, paths, network addresses and free text are forbidden
  from audit; secrets are rejected rather than copied. A closed deletion receipt
  requires full inventory coverage, all locations attempted, zero failures/
  ordinary backups and an independent witness. It explicitly proves procedure
  over the declared inventory, not physical erasure. No workspace, audit store,
  real data, receipt or deletion action exists and `i09` remains false. Six new
  and 40 preceding contract tests pass; JSON/diff checks are clean. Next safe
  slice: freeze a symbolic append-only audit hash-chain and deletion-rehearsal
  state machine with crash/partial-failure transitions, still without creating
  storage or touching real evidence.
- 2026-08-15 ADR 0030 freezes a symbolic minimized audit hash-chain and
  deletion-rehearsal state machine. Closed events hash a domain-separated,
  ordered binary preimage of sequence/IDs/type/time/object/policy/previous hash/
  decision/reason; the genesis predecessor is 32 zero bytes and a fixed vector
  plus all-field mutations prevents serialization drift. The chain detects
  mutation/reorder/gaps only with an independent checkpoint and does not make
  mutable storage append-only by itself. Deletion progresses through planned,
  claimed, deleting, scanning and independent-witness states to complete;
  invalid pre-side-effect plans may fail, while partial/unknown effects, scan
  drift, witness failure or ambiguous crashes become terminal review. No
  automatic retry is allowed after a side effect; a new attempt needs a new
  linked plan. No persistence, event, worker or deletion exists and `i09` stays
  false. Seven new and 46 preceding contract tests pass; JSON/diff checks are
  clean. Next safe slice: freeze an append-only persistence/transaction ordering
  contract and fault-injection matrix for audit-before-state visibility, using
  only an in-memory symbolic model and no filesystem/database writes.
- 2026-08-15 ADR 0031 freezes the symbolic append-only persistence ordering and
  fault matrix for audit/deletion. Internal transitions lock state/audit head,
  compare expected values, stage the immutable event before state, and commit
  event/head/state atomically; pre-commit crashes expose neither half and a
  post-commit crash exposes both once. Each external location has one immutable
  prepared intent and at-most-once invocation; an exact outcome is committed
  with its audit event, while any possibly-started effect without durable outcome
  becomes `UNKNOWN_REVIEW` and is never auto-reinvoked. Ten fault points cover
  staged/committed transactions, before/during/after external effects, read-only
  scan recovery and unavailable checkpoints. The contract explicitly denies
  database/external-effect atomicity and exactly-once claims. No backend/store/
  worker/effect exists and `i09` stays false. Seven new and 53 preceding
  contract tests pass; JSON/diff checks are clean. Next safe slice: freeze the
  independent audit-checkpoint envelope, freshness/rollback policy and two-
  domain authentication shortlist, without choosing a service or adding keys.
- 2026-08-15 ADR 0032 freezes the closed independent audit-checkpoint envelope,
  rollback/freshness policy and authentication shortlist. A checkpoint binds a
  consumer-selected chain/policy, exact local sequence/head, previous checkpoint,
  monotonic epoch, single-use nonce, ten-minute window and exactly two witness
  evidence digests. Witness domains must differ by identity, auth root, recovery,
  host and evidence and cannot control the audit store. Ordered validation rejects
  stale/equal sequence, lower epoch, alternate same-sequence head, wrong previous
  checkpoint, local mismatch, reused nonce and future/expired evidence before
  atomically advancing high-water state. Dual DSSE and dual WebAuthn witnesses
  are shortlisted; DSSE plus transparency is supplemental only. Checkpoints make
  post-observation rollback detectable but cannot prove pre-observation omitted
  events. No witness/root/log/RP/store/verifier/checkpoint exists and `i09` stays
  false. Seven new and 60 preceding contract tests pass; JSON/diff checks are
  clean. Next safe slice: freeze a conjunctive authentication scorecard for the
  dual-witness checkpoint candidates and explicit split-view/checkpoint-recovery
  tests, still selecting none and adding no service or key.
- 2026-08-15 ADR 0033 freezes the conjunctive authentication scorecard and
  split-view/recovery matrix for independent audit checkpoints. Eight common
  gates require exact shared bytes, two-domain independence, nonce/freshness,
  rollback-resistant high-water state, equivocation quarantine, reviewed root
  recovery, parser/dependency evidence and no availability-driven quorum
  degradation. DSSE adds two active roots, exact DSSE/PAE, signer isolation and
  offline recovery; WebAuthn adds two witnessed enrollments, exact RP/origin,
  ES256 UP/UV non-backup flags and human replacement/collusion controls. Same-
  sequence forks, divergent descendants, checkpoint-ahead local drift and log
  split views quarantine without choosing a branch; loss of one witness or
  high-water state blocks, and root rotation needs independent recovery, higher
  epoch, continuity and old-root revocation. Both candidates remain unevaluated
  with no evidence/service/key/recovery action and `i09` false. Seven new and 67
  preceding contract tests pass; JSON/diff checks are clean. Next safe slice:
  freeze the exact checkpoint authentication challenge/preimage and fixed vector
  shared by DSSE/WebAuthn candidates, without decoding signatures or enrolling
  witnesses.
- 2026-08-15 ADR 0034 freezes the exact slot-specific checkpoint witness
  authentication challenge and fixed vector. The domain-separated SHA-256
  preimage binds checkpoint schema/exact-byte digests, chain/policy, sequence/
  head/predecessor, epoch, nonce/time and witness slot/domain/auth/recovery/host
  roots. DSSE statements must bind the slot challenge and exact checkpoint
  digest; WebAuthn uses the raw 32-byte slot challenge. Slot evidence cannot be
  swapped or reused across context. Review found and fixed a genesis ambiguity:
  predecessor encoding now includes a presence byte, so null (`0` + zeros) does
  not alias a present all-zero digest (`1` + digest). This remains hash-only;
  no signature/assertion decode, witness or permission exists and `i09` is false.
  Six new and 74 preceding contract tests pass; JSON/diff checks are clean. Next
  safe slice: freeze bounded candidate-specific evidence envelopes for DSSE and
  WebAuthn witness imports, keeping signature/assertion bytes opaque and all
  authentication/selection flags false.
- 2026-08-15 ADR 0035 freezes closed bounded transport envelopes for DSSE and
  WebAuthn checkpoint-witness evidence. DSSE binds declared slot/domain/root,
  checkpoint/challenge/evidence digests, exact payload type, one canonical
  standard-padded Base64 payload, one opaque signature and a bounded optional
  `keyid` hint; decoded payload/signature/evidence limits are 8 KiB/1 KiB/16 KiB
  and `keyid` never selects authority. WebAuthn binds the same context with
  canonical unpadded Base64URL assertion fields limited to 8 KiB client data,
  1 KiB credential/authenticator/signature, 64-byte user handle and 16 KiB
  evidence; user handle alone may be null. Both are transport-only: declared
  digests are untrusted until verified content matches, and no payload/assertion/
  signature decode, lookup or crypto exists. Six new and 80 preceding contract
  tests pass; JSON/diff checks are clean. Next safe slice: freeze strict local
  DSSE witness-statement semantics and WebAuthn client-data/authenticator-data
  preflight contracts while retaining symbolic signature outcomes and no root/
  credential verification.
- 2026-08-15 ADR 0036 freezes strict DSSE checkpoint-witness statement
  semantics and WebAuthn client/authenticator-data preflight. The DSSE payload
  is a closed bounded object binding slot/domain/root, checkpoint/challenge,
  epoch/time and exact `WITNESS`; unknown/duplicate fields fail and semantics
  run only after a symbolic signature-success gate. WebAuthn client data is
  closed `webauthn.get` with exact canonical 32-byte challenge and allowlisted
  origin; crossOrigin may be absent/false and topOrigin/unknowns fail.
  Authenticator data is exactly 37 bytes with exact RP hash and flags `0x05`
  (UP+UV only); BE/BS/AT/ED/reserved bits and extensions fail, while signCount
  remains advisory. External exact credential/ES256/enrollment/root/revocation
  lookup still follows preflight and is not implemented. Seven new and 86
  preceding contract tests pass; JSON/diff checks are clean. Next safe slice:
  freeze consumer-selected DSSE-root and WebAuthn-credential/revocation snapshot
  contracts plus epoch/rotation ordering, without public-key parsing or crypto.
- 2026-08-15 ADR 0037 freezes consumer-selected metadata-only trust snapshots
  for DSSE witness roots and WebAuthn credentials. Selection uses only expected
  policy/slot/domain/epoch; envelope `keyid`, declared root and assertion
  credential ID cannot choose authority. DSSE snapshots bind Ed25519 root/public-
  key digests; WebAuthn snapshots bind credential/COSE-key digests, ES256,
  exact RP/origin, non-backup status, enrollment provenance and optional user-
  handle digest. Active status, time, recovery separation and stored-byte digest
  match precede parsing/crypto. Rotation strictly advances epoch, links the
  highest snapshot, changes material, requires two recovery domains and atomically
  revokes/compromises old material; failure cannot expose partial activation or
  rollback. No key/credential bytes, parser, store or rotation exists. Seven new
  and 93 preceding contract tests pass after one test-only wording correction;
  JSON/diff checks are clean. Next safe slice: freeze public-key/COSE byte-shape
  parser requirements and a verification-only public fixture provenance plan,
  without importing keys, private material, parser dependencies or crypto calls.
- 2026-08-15 ADR 0038 freezes public-key byte-shape/parser requirements and a
  provenance gate for future verification-only fixtures. Ed25519 requires exact
  32-byte canonical compressed Edwards encoding, valid on-curve torsion-free/
  non-small-order semantics and strict verification behavior; length/digest
  alone is insufficient. WebAuthn ES256 requires deterministic bounded CBOR with
  exactly COSE `kty=2`, `alg=-7`, `crv=1`, 32-byte x/y, no unknown/duplicate/
  indefinite/tag/trailing/private fields and a finite on-curve P-256 point.
  Future fixtures may contain public verification inputs only and require an
  authoritative immutable source, byte/field/extraction digests, license review,
  closed mutation recipes and two authenticated independent non-generator
  reviews before import. No source/license/reviews/fixture bytes/parser dependency
  or crypto was added. Seven new and 100 preceding contract tests pass; JSON/
  diff checks are clean. Honest roadmap estimate at this point: the full E0-E5
  ecosystem vision is roughly 50–55% complete by milestone value (contractual
  foundation higher, operational/production gates lower); current checkpoint/
  attestation contract design is roughly 80–85%, but its real operational path
  remains under 10% because roots, witnesses, stores, parsers, authenticated
  reviews and device/runtime verification are intentionally absent.
- 2026-08-15 product priority shifted toward maximizing defensible acquisition
  value rather than extending design contracts indefinitely. A machine-readable
  100-point acquisition-readiness scorecard now weights verified financial
  quality (25), legal/regulatory evidence (20), traction (15), technology/
  security (15), transferability (10), IP defensibility (10) and transaction
  readiness (5). Unknown/blocked evidence contributes zero; no score or valuation
  may be published yet. An innovation registry forbids unsupported `unique` or
  patentability claims and lists four differentiated candidates with missing
  prior-art/FTO/market evidence.
- The first commercial moat candidate is `execution-trust-passport.v1`: a
  privacy-minimized, read-only proof joining immutable intent, service lane,
  identity/custody/executor, quote, consent, hard/advisory policy, provider
  attempt, reconciliation and an independently checkpointed evidence chain.
  `relay/core/execution_trust_passport.py` is a pure offline non-authoritative
  verifier with no I/O/action authority. It rejects unknown fields, digest/
  parameter drift, advisory weakening, non-ALLOW execution, invalid time/state
  transitions, uncertain outcomes outside review and hash-chain mutation. A
  synthetic fixture initially exposed and fixed an invalid HOLD+CONFIRMED case.
  Seven commercial-contract and ten passport-verifier tests pass with compile,
  JSON and diff checks clean. Production emission, buyer value, prior-art and
  FTO validation remain false. Next value step: build a privacy-safe KPI/cohort
  extraction contract and read-only report from production aggregates, with no
  customer identifiers or financial mutation; this is the highest valuation
  evidence gap before expanding the moat prototype.
- 2026-08-18 E0/E0.4 Editorial News Delivery read-only slice completed. Evidence
  is `docs/e0-4-editorial-news-delivery-runtime-observation.v1.json`; Telegram
  delivery is implemented but rejected for timestamp-only non-idempotent
  delivery, missing source provenance/freshness/licensing, consent/audit/
  retention, bounded retry/outbox, and separate legacy Telegram trust paths.
  Site/MiniApp/native/admin surfaces are absent; API is partial/unaccepted.
  No Telegram, customer, provider, deployment, or production mutation occurred.
  Next safe route is E0/E0.4/TELEGRAM_CHANNEL_POST_PROCESSING; E0.3 remains
  first unmet and BLOCKED_OWNER.
- 2026-08-18 E0/E0.4 Telegram Channel Post Processing read-only slice completed.
  Evidence: `docs/e0-4-telegram-channel-post-processing-runtime-observation.v1.json`.
  Premium Telethon userbot/channel editing is a high-authority writer and is
  not accepted: no least-privilege/session governance, immutable channel scope,
  durable edit receipt/idempotency/reconciliation, or sandboxed service.
  Duplicate source copies and legacy direct Telegram writers add drift. No
  Telegram call, authentication, edit, deployment, or production mutation was
  performed. Next safe route is E0/E0.4/LEGACY_PAYMENT_EDGE_UPSTREAM; E0.3
  remains first unmet and BLOCKED_OWNER.
- 2026-08-18 E0/E0.4 Framework Generated Admin HTTP Surface read-only slice
  completed. Evidence: `docs/e0-4-framework-generated-admin-http-surface-runtime-observation.v1.json`.
  Filament declares 12 resources, 16 resource-page files and one static web
  route, but generated auth/dashboard/resource/Livewire/vendor routes are not
  provable without boot. Acceptance rejected pending bound generated manifest,
  closed action/role scope, runtime artifact binding and audit reconciliation.
  No Laravel boot/authentication/customer/admin data access/deployment/mutation.
  Next safe route is E0/E0.4/GENERATED_FASTAPI_DOCS; E0.3 remains BLOCKED_OWNER.
- 2026-08-18 E0/E0.4 Legacy Payment Edge Upstream read-only slice completed.
  Evidence: `docs/e0-4-legacy-payment-edge-upstream-runtime-observation.v1.json`.
  Two enabled public TLS aliases wildcard-proxy to `127.0.0.1:8080`, but no
  mapped systemd/container owner or payment-truth authority was found and no
  listener was visible. Docker inspection was sandbox-inaccessible; nginx
  syntax parsed but runtime test was blocked by read-only `/run/nginx.pid`.
  Acceptance remains rejected pending ownership, reachability, TLS, scope,
  release, health and rollback evidence. No HTTP/payment/customer/deployment
  action occurred. Next safe route is E0/E0.4/FRAMEWORK_GENERATED_ADMIN_HTTP_SURFACE.
- 2026-08-18 E0/E0.4 Generated FastAPI Docs read-only slice completed.
  Evidence: `docs/e0-4-generated-fastapi-docs-runtime-observation.v1.json`.
  Relay exposes default OpenAPI/docs/redoc plus `/static`; LUMI does likewise;
  KAIROS disables docs and mounts `/assets`. Static counts infer 346 route
  objects, but runtime middleware/generated inclusion is unproven. Acceptance
  rejected pending docs exposure classification, static-mount policy and
  immutable deployed manifests. No app import/HTTP/auth/customer/provider or
  production action occurred. Next safe route is E0/E0.4/DEPLOYED_GENERATED_UNIVERSE_RECONCILIATION.
- 2026-08-18 E0/E0.4 Deployed Generated Universe Reconciliation completed.
  Evidence: `docs/e0-4-deployed-generated-universe-reconciliation.v1.json`.
  Effective systemd units execute `/root` paths while deployed route evidence is
  under `/opt` for Relay/KAIROS/LUMI; no immutable manifest binds unit,
  executable, dependencies, route inventory, Nginx and generated caches.
  Static route claims are therefore non-authoritative. No service start/restart,
  import, HTTP/auth/customer/provider access, deployment or mutation occurred.
  Next safe route is E0/E0.4/POST_CLOSURE_GAP_REGISTER; E0.3 remains BLOCKED_OWNER.
- 2026-08-18 E0/E0.4 Post Closure Gap Register completed.
  Evidence: `docs/e0-4-post-closure-gap-register.v1.json`.
  Eight confirmed closure gaps remain across money authority, deployment trust,
  editorial/channel delivery, public payment edge ownership, generated admin/
  API surfaces and `/root` versus `/opt` runtime drift. Register is restrictive
  and grants no acceptance or production authority. E0.3 remains first unmet/
  BLOCKED_OWNER; E0.4 remains IN_PROGRESS. Next step is owner-gated remediation
  planning; no production action is authorized.
- 2026-08-18 E0/E0.4 Owner Decision Intake template created:
  `docs/e0-4-owner-decision-intake.v1.json`. It contains no owner decision,
  no candidate hashes or allowed actions, and explicitly rejects missing auth,
  ambiguity, hash/path drift, expiry-as-allowance and reviewer/owner conflation.
  No authority or production action inferred. Next safe route is
  E0/E0.4/READ_ONLY_REMEDIATION_REHEARSAL; E0.3 remains BLOCKED_OWNER.
- 2026-08-18 E0/E0.4 Owner-Gated Remediation Plan drafted as documentation only.
  Evidence: `docs/e0-4-owner-gated-remediation-plan.v1.json`.
  Four workstreams cover runtime identity, money/payment edge, Telegram/editorial
  delivery and generated surfaces, each with exit evidence and forbidden actions.
  No implementation, deployment, restart, authentication, send/edit, charge or
  production authority was granted. E0.3 remains first unmet/BLOCKED_OWNER and
  E0.4 remains IN_PROGRESS. Next safe route is E0/E0.4/OWNER_DECISION_INTAKE.
- 2026-08-18 E0/E0.4 Read-only remediation rehearsal completed on synthetic
  contract data only: schema, restrictive flags, owner gates, hash/path rules,
  expiry monotonicity and E0.3/064B/064D restrictions passed. No production
  files, services, network, secrets or customer data touched. Owner decision and
  independent review remain absent. Next safe route is
  E0/E0.4/OWNER_DECISION_INTAKE_REVIEW.
- 2026-08-18 E0/E0.4 Owner Decision Intake Review completed.
  Evidence: `docs/e0-4-owner-decision-intake-review.v1.json`.
  Intake exists but authenticated owner, candidate hashes, bounded action enum,
  independent reviewer, runtime manifest and rollback/replay evidence are all
  absent. Result remains BLOCKED_OWNER; no decision or authority inferred.
  Next safe route is E0/E0.4/RESTRICTIVE_STATUS_REPORT.
