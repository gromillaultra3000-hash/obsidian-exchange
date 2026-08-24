# E2 risk-intelligence contracts

Foundation frozen: 2026-08-11. This slice is pure and keyless; it is not wired
to trading, payout, connector scheduling or live CEX data.

`evidence-record.v1` contains an opaque content hash, aware observation time,
bounded subject/signal/source/freshness enums and at most 32 scalar minimized
facts. Fact names that imply owner/account/credential/key/address/wallet/balance/
amount/PII/KYC data are rejected. Raw provider payloads are forbidden.

`decision-envelope.v1` orders verdicts as:

`ALLOW < HOLD < MANUAL < FREEZE`

The combined verdict is always the stricter of the deterministic hard gate and
the advisory verdict. Timeout, error, malformed or unknown advisory output is
normalized to `HOLD`; it cannot soften an existing `MANUAL` or `FREEZE`.
`actionAllowed=true` is valid only when the combined verdict is exactly `ALLOW`.
Forged non-monotonic envelopes fail model validation.

Frozen compatibility examples live in `contracts/e2-risk/` for both schemas;
their timestamps, content-derived evidence reference, exact fields and policy
version are regression-tested.

This contract does not authorize LUMI to execute money actions. Future bridge
integration must persist versioned inputs/policy and prove the same monotonic
matrix at the HTTP boundary before any shadow verdict is consumed.

## Frozen observation and metrics contracts

`shadow-trigger-catalog.v1` permits only five observations: permission drift,
connector degradation, provider rate limiting, stale market data and advisory
unavailability. Every trigger fixes subject/signal/source, the exact fact-key
set and a 1/60/300-second UTC sampling bucket. `shadow-observation-plan.v1`
hashes catalog version, trigger, bucket and frozen submission into an opaque
idempotency key. Repeated input inside one bucket is identical; fact or bucket
changes produce a new key. Unknown triggers and added/missing fact keys fail.

`shadow-metrics.v1` exposes only fixed zero-filled counters by catalogued signal,
freshness and combined verdict, plus disagreement and advisory-tightening
counts. Evidence facts, IDs, timestamps, principals and record IDs are never
projected. Unknown signals fail verification instead of becoming an unreviewed
bucket. The daily read-only operator verifier computes this projection only
after replaying every archived and active generation.

The catalog and empty metrics fixtures live in `contracts/e2-shadow/`. Neither
contract schedules observations, enables either producer flag, calls LUMI or
affects execution.

## Frozen operator alarm policy

`shadow-alert-policy.v1` evaluates exact aligned five-minute windows. Permission
drift is immediately CRITICAL. Stale market observations, provider rate limits
and slow/unavailable advisory observations have fixed count thresholds. Hard vs
advisory divergence requires both a minimum count and rate, preventing tiny
windows from creating a percentage-only alarm.

Escalation is immediate. Recovery requires two consecutive healthy windows;
the state carries the exact previous window end, so a gap or replay fails rather
than falsely advancing recovery. A recurring condition resets recovery to zero.
The fixed alarm set uses only CLEAR/WARN/CRITICAL and ACTIVE/RECOVERING/CLEAR.
Every `shadow-alarm-projection.v1`, including CRITICAL, has
`actionAllowed:false` and contains no evidence, fact, identity or record field.
This evaluator is a pure deployed module and has no timer, route or execution
consumer.

## Deterministic window extraction and replay

`shadow-alarm-replay.v1` accepts only contiguous verified journal records and
aligned five-minute UTC bounds. Every record is assigned by `recordedAt`; empty
intervals become explicit zero windows, so recovery cannot skip silence. A
record outside the requested bounds, a sequence gap, naive/unaligned time or a
range above seven days fails closed. Longer history is replayed in consecutive
chunks using the exact prior `shadow-alarm-state.v1`; whole and chunked replay
produce the same final state.

Latency values are frozen categories, never raw durations:
`LT_250MS`, `MS250_999`, `S1_3`, `OVER_3S`, `TIMEOUT`. Slow advisory count is
at most one per submission for the last three categories. Age and retry values
are likewise bounded enums, and numeric counts are limited to 0..1000. The
Relay catalog rejects any uncatalogued value before constructing a submission.

The replay projection contains windows, alarm projections and final state but
no record/evidence/fact/identity material; `actionAllowed` remains false. An
empty-window compatibility fixture freezes its exact wire shape. The module is
hermetic and non-persistent.

## Offline operator replay

`scripts/replay_shadow_alerts.py` is an explicit read-only CLI requiring aligned
aware `--start` and `--end` values. It first verifies the complete archive +
active chain, so tamper outside the selected range still fails. Only then does
it select the bounded records and run deterministic window/alarm replay.

Success is one `shadow-operator-replay.v1` JSON object on stdout with exit 0.
Contract, range, replay or filesystem failure is one `NO_GO` JSON object on
stdout with exit 1; malformed/missing CLI arguments use the same stdout-only
shape and exit 2. There is no output-file option, network import, state write,
route, timer or service. An absent journal is an honest valid genesis replay and
does not create its directory or lock.

## Frozen LUMI advisory wire

`shadow-advisory-request.v1` contains only the policy version, aware request
time, deterministic hard verdict and at most eight already validated minimized
EvidenceRecords. Its opaque `ar_…` ID hashes the complete canonical request;
duplicates, future evidence, field drift or hash mismatch fail validation. It
contains no principal, account, credential, raw provider payload or execution
instruction.

`shadow-advisory-response.v1` is bound to the exact request ID and contains only
an advisory verdict, bounded reason codes, evaluated time and bounded model
version. The hermetic dispatcher uses an injected transport with an exact
750 ms deadline; it imports no HTTP client, endpoint, token or environment.
Wrong IDs, extra fields, invalid enums/reasons or timestamps outside
request..decision become `MALFORMED`; timeout and transport failure become
`TIMEOUT`/`ERROR`. Every failure normalizes advisory to HOLD.

The combined verdict is always max(hard, advisory), so a valid or failed LUMI
response cannot soften MANUAL/FREEZE. `shadow-advisory-dispatch.v1` always
returns `executionEffect:NONE` and `actionAllowed:false`, even for ALLOW/ALLOW.
Frozen request/response fixtures and the complete 4×4 matrix are tested. This
new wire is separate from the legacy committee `lumi_bridge.py`; it has no
runtime endpoint or production transport.

The LUMI-side adapter is also pure and deterministic. It independently checks
the complete request/evidence hashes and the exact frozen five-signal catalog,
including boolean types, bounded integer counts and enumerated latency/age/retry
buckets. Unknown signals, extra/missing facts and raw or type-coerced values are
rejected before advisory rules run. The fixed rules can only tighten the hard
floor; they make no model/provider call and expose no route, token, network or
state surface. Cross-package fixture evaluation and KAIROS dispatch are tested
under the production service identity without starting or restarting a service.

## Frozen offline end-to-end replay

`shadow-offline-replay.v1` composes the frozen Relay observation plan, LUMI
adapter, KAIROS dispatcher and exact next journal-record projection entirely in
memory. The observation identity and JSON wire submission are revalidated
before advisory evaluation. The output binds the observation/request IDs,
advisory response, non-executing dispatch and projected genesis record, and is
frozen as an exact fixture.

`project_record` is the shared pure journal formatter used by both offline
replay and the real append implementation. A temporary-journal test proves the
projection and append formats are byte-equivalent. Replay itself has no file,
lock, route, scheduler, network, token or execution surface and always returns
`projectionOnly:true`, `executionEffect:NONE`, `actionAllowed:false`.

`shadow-offline-batch.v1` extends this projection from an explicit trusted
`baseSequence`/`baseHash`. Each unique observation advances sequence and uses
the prior projected record hash; an exact retry is reported as a duplicate and
does not advance the head. Reusing an observation ID with changed request,
advisory, dispatch or decision inputs fails closed. Tests cover all five frozen
triggers, a non-genesis head, exact append/replay equivalence and malformed head
values. The bounded batch accepts 1..64 inputs and remains projection-only.

`shadow-offline-batch-verification.v1` is produced by a strict pure verifier.
It rejects field/count/flag drift, unknown duplicate IDs, broken request ↔
response ↔ dispatch ↔ decision bindings, invalid evidence/decision contracts,
sequence/previous-hash discontinuity and record/head hash tamper. The journal's
same in-memory chain verifier is shared here, with failures normalized to the
public fail-closed validation boundary. Whole replay and resumed `2 + 3` chunks
produce identical records and final head for the five-trigger fixture.

## Frozen KAIROS → LUMI shadow service identity

`shadow-service-envelope.v1` binds Ed25519 to the exact future POST path, empty
query, canonical advisory body SHA-256, JSON content type, key ID, integer
timestamp, nonce, issuer `kairos-shadow`, scope `shadow:advisory` and audience
`lumi-shadow`. The acceptance window is ±30 seconds. Newline injection, field
drift, wrong body/signature/time and extra fields fail before nonce consumption.

Signing, signature verification and nonce consumption are injected callables.
The pure module therefore reads no key/env/file, stores no replay state and
makes no network call. A nonce is consumed only after all fields, body hash,
clock and signature validate; the frozen replay test rejects its second use.
`shadow-service-verification.v1` is always non-executing. The signed body still
passes the independent LUMI advisory validator after identity verification.
There is no runtime route or key provisioning. Production LUMI's current venv
does not include `cryptography`; that remains an explicit runtime-readiness
blocker rather than being silently installed during this contract slice.

`shadow-replay-ledger.v1` is the bounded immutable replay snapshot. Entries
contain only `SHA-256(keyId NUL nonce)` and expiry, never raw key IDs or nonces.
`shadow-replay-transition.v1` validates the complete snapshot, prunes entries
only after their inclusive expiry window, rejects an active replay or full
capacity, and returns a new deterministically sorted snapshot without mutating
the input. Capacity is explicit and bounded at 1..10,000; accepted expiry is
limited to `now..now+60s`. JSON round-trip preserves replay rejection across a
simulated restart, while expiry and capacity recovery are deterministic. This
slice has no filesystem or lock implementation and creates no production state.

`AtomicReplayStore` is the optional file adapter around that unchanged pure
transition. It serializes consumers with an exclusive `flock`, rejects symlink,
non-regular, permissive, corrupt, partial and oversized state, and commits a
canonical snapshot through a `0600` temporary file, file `fsync`, atomic
`replace`, and directory `fsync`. State and lock are both `0600`.

Fault injection after temporary-file `fsync` leaves the prior snapshot intact;
fault after `replace` leaves a valid committed snapshot whose retry is rejected.
Eight concurrent unique nonces commit without lost updates, while six processes
racing one nonce produce exactly one acceptance. Restart, capacity and expiry
semantics remain those of the pure ledger.

`shadow-replay-provisioning-plan.v1` fixes the production state path at
`/var/lib/lumi/e2-shadow/replay-ledger.json`, its adjacent lock, `lumi-svc`
ownership, `0700` directory, `0600` files and capacity 10,000. The one-shot
provisioner requires an exact safe ancestor, creates both targets exclusively,
fsyncs them and rolls back the complete fresh layout after injected failures at
the directory, state or lock stages. Existing, partial and symlink targets fail
without overwrite. Production now contains a validated empty snapshot and lock;
the read-only path is configured, but no runtime caller or endpoint consumes it.

`shadow-public-keyring.v1` is a content-hashed Ed25519 allowlist for audience
`lumi-shadow`, bounded to eight public keys. Entries are sorted, uniquely keyed,
valid for at most one year and have status `ACTIVE`, `RETIRING` or `REVOKED`;
there can be at most one ACTIVE key. Rotation is immutable: the new key becomes
ACTIVE and the prior ACTIVE key becomes RETIRING for an explicit 0..300-second
inclusive overlap. Revocation rejects immediately and may intentionally leave
zero ACTIVE keys as a fail-closed stop.

Resolution requires exact key ID, status and validity window. The read-only
loader rejects symlink, non-regular, group/world-writable, corrupt and oversized
files; public keyrings may be `0644`. Frozen fixtures use synthetic keys only.
No `/etc/lumi` or `/var/lib/lumi` keyring was provisioned, and production LUMI
still has no Ed25519 dependency or runtime caller.

## Shadow transport readiness gate

`shadow-transport-readiness.v1` is a strict read-only gate over twelve explicit
prerequisites: Ed25519 dependency; configured, valid keyring and active key;
configured replay path, safe writable parent and valid existing state; KAIROS
transport, LUMI endpoint, KAIROS ingress and Relay producer flags; and genuinely
independent backup devices. Probe values must be exact booleans and internally
consistent. Any missing check yields ordered blockers and `NO_GO`.

Even a fully satisfied synthetic probe returns `executionEffect:NONE` and
`actionAllowed:false`; readiness is not authorization. The standalone CLI emits
one stdout JSON object and exits 0 for GO or 1 for NO_GO. It reads only already
configured files/directories/device IDs and never creates a replay file or
lock. Under the production LUMI interpreter/UID it matches the frozen
replay-ready `NO_GO` fixture: dependency, public request keyring and empty replay
state are ready, while four feature flags and independent backup remain blocked.
No unit or timer invokes it automatically.

## Frozen signed LUMI response receipt

`shadow-response-receipt.v1` gives the reverse LUMI→KAIROS leg an independent
Ed25519 proof. It binds the exact validated advisory request ID, canonical
request and response body hashes, JSON content type, key ID, timestamp, nonce,
issuer `lumi-shadow`, scope `shadow:advisory-response`, audience
`kairos-shadow`, and literal `executionEffect:NONE/actionAllowed:false`.
`rr_…` is the SHA-256 of the canonical unsigned receipt and is included in the
signature.

KAIROS independently validates both frozen request/response contracts and their
shared request ID before signature verification. Body/field/hash/time/signature
drift fails before nonce consumption; exact receipt replay is rejected. The
verified response still passes the monotonic dispatcher and remains
non-executing. Signer, verifier and nonce consumer are injected; there is no
key/env/file/network/route/state access or production key provisioning.

## Hermetic mutual-auth round-trip transcript

`shadow-mutual-auth-transcript.v1` composes the two frozen identity legs into
one deterministic offline proof: KAIROS request signature verification, the
independent LUMI advisory evaluation, LUMI response receipt signing and KAIROS
receipt verification, followed by the monotonic advisory dispatch. The
transcript content hash has an `rt_…` identity and binds the shared request ID,
exact request/response hashes, receipt ID and every stage result.

Every nested stage and the transcript itself must retain
`executionEffect:NONE/actionAllowed:false`; dispatch must be `OK`. Request
replay stops before LUMI evaluation, response replay stops before dispatch, and
signature or binding failures do not consume the affected response nonce.
Signer/verifier/evaluator/replay consumers remain injected. This is a hermetic
self-test contract, not a route, client, service, key store or runtime switch.

## Read-only transport preflight proof

`shadow-preflight-proof.v1` strictly composes a complete
`shadow-transport-readiness.v1` result with the validated mutual-auth transcript
summary. Its content-derived `pf_…` ID binds the ordered readiness checks and
blockers plus the transcript/request/body hashes. Malformed, inconsistent or
tampered readiness and self-test inputs fail closed.

Only `GO` readiness plus a valid self-test can produce `ELIGIBLE`; eligibility
still carries `executionEffect:NONE/actionAllowed:false` and is not runtime
authorization. The frozen production-equivalent proof is `INELIGIBLE`: the
hermetic self-test passes. After pinning `cryptography==49.0.0` in the isolated
LUMI runtime and configuring its public request-verification keyring plus empty
replay state, seven file/dependency checks are ready and five operational
prerequisites remain explicit blockers. The pure proof module itself has no
environment, filesystem, network, key, crypto, route or state surface.

## Two-direction service-key ownership and provisioning

`shadow-service-key-plan.v1` fixes the ownership boundary before any production
key exists. KAIROS owns only its request-signing private key and the public LUMI
response keyring; LUMI owns only its response-signing private key and the public
KAIROS request keyring. Directions have distinct key IDs, issuer/audience,
scope, paths and service groups. The plan is content-hashed as `kp_…`, valid for
one year and itself remains non-executing.

The provisioner accepts injected 32-byte private/public material, creates files
exclusively with `O_EXCL|O_NOFOLLOW`, fsyncs them, uses `0640` files in exact
`0750` service-group directories and never returns or logs key bytes. Existing,
partial or symlink targets fail without overwrite. A fault after any of the four
writes removes every newly created key/keyring, preventing half-provisioned
identity. Public keyrings retain strict expected-audience validation for both
`lumi-shadow` and `kairos-shadow`; the historical default stays fail-closed at
`lumi-shadow`.

The ownership contract was subsequently applied in production. `/etc/kairos`
and its two shadow leaf directories are `0750 root:kairos-svc`; `/etc/lumi` and
its two shadow leaf directories are `0750 root:lumi-svc`. The one-shot
provisioner created two `0640` private keys and the two opposite-audience public
keyrings without exposing key material. Each service UID can read only its own
private key and trust keyring; cross-service reads fail. Cryptographic binding
between each private key and its public keyring was verified locally.

The LUMI request-verification keyring and replay paths are configured through a
dedicated systemd drop-in. The production probe validates the active keyring,
safe writable replay parent and empty snapshot, but remains the frozen
five-blocker `NO_GO`: all four transport/endpoint/ingress/producer flags remain
disabled and independent backup is unavailable. No endpoint, network wiring or
service restart was added.

## Independent backup/restore evidence

`shadow-backup-restore-evidence.v1` is the pure fail-closed gate that must
replace directory-existence heuristics before transport can be considered.
READY requires a source, primary and secondary copy on three distinct device
IDs; both backup copies must be verified; a restore must be rehearsed; and the
source, both copies and restored artifact must have the same SHA-256. Shared
devices or any digest mismatch return `NO_GO`. Malformed combinations such as
an unconfigured-but-verified copy or a restore hash without a rehearsal are
rejected rather than converted into evidence.

The module has no filesystem, environment, network, subprocess or runtime
surface and remains dormant. Frozen synthetic READY and no-storage NO_GO
fixtures cover the complete result. Production has no qualifying storage: the
existing primary, secondary and restore directories resolve to the same
`/dev/sda1` device (`st_dev=2049`). No backup, mount, evidence file or feature
flag was created by this slice.

The production readiness CLI now accepts `INDEPENDENT_BACKUP` only from
`LUMI_E2_SHADOW_BACKUP_EVIDENCE`. Its loader requires a non-symlink regular
file owned by root and the executing LUMI group, exact `0640`, bounded to 16
KiB, opened with `O_NOFOLLOW`, and unchanged inode/device/size across
`lstat`/`open`. The complete evidence schema is revalidated and only a READY
result can satisfy readiness. Missing, malformed, permissive, NO_GO or symlink
evidence fails closed. The prior two-directory `st_dev` heuristic and both
  legacy backup-path variables are no longer accepted by this gate. Production
  does not configure an evidence path and therefore remains five-blocker NO_GO.

The guarded `produce_shadow_backup_evidence.py` performs the operational side
of this contract. Before copying it requires the journal source and both backup
destinations to occupy three different device IDs. It then runs the existing
verified two-copy operation and guarded restore rehearsal, requires matching
replays and manifest digests, and atomically writes only validated READY
evidence at `0640`. Empty journals and a single-device layout fail before any
bundle or evidence file is created. It is not scheduled and changes no flag.
