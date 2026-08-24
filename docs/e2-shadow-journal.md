# E2 shadow decision journal

The keyless shadow journal is an append-only JSONL hash chain. Every record
contains exact frozen evidence and decision envelopes, a deterministic record
ID, sequence, previous hash, recorded time and record hash. Append takes an
exclusive process lock, verifies the full existing chain, appends one bounded
line, fsyncs the file and directory, and keeps mode `0600`.

Replay revalidates evidence content hashes, privacy schema, exact evidence refs,
monotonic decision policy, timestamps, sequence and both hashes. Duplicate
core evidence+decision is idempotent. Malformed JSON, field drift, mutation,
reordering, deletion, duplicate IDs or a partial tail fail closed; there is no
automatic repair or truncation.

## Storage and operations policy

The only production path is
`/var/lib/kairos/e2-shadow/decisions.jsonl`, owned by `kairos-svc`, under a
`0700` directory; journal and lock files are `0600`. The path is passed through
`KAIROS_E2_SHADOW_JOURNAL`, but no runtime producer reads it yet. Code, logs,
temporary directories and `/root` are forbidden journal locations.

The active generation is never truncated, repaired, compacted or selectively
deleted. It is capped at 16 MiB and fails closed at capacity. Before a future
producer is enabled, generation rotation and restore tooling must preserve the
last record hash as the next generation's checkpoint. Archived generations are
retained for 400 days. Deletion is allowed only for a complete archived
generation older than 400 days after two independently stored backups have
both been hash-verified and one restore rehearsal has replayed the full chain.
No automatic deletion exists in this slice.

Backups are required daily once the first record exists, after every rotation,
and before deployment affecting either evidence or journal contracts. A backup
is acceptable only if its SHA-256 digest is recorded, its replay result matches
the source record count/head hash, and a restore rehearsal succeeds. Backup
bundles from both destinations replay to the same source head. The management
CLI implements explicit `verify`, `rotate`, two-destination `backup` and
`rehearse-restore` operations. Rotation copies and fsyncs the immutable archive,
appends and fsyncs a hash-chained checkpoint, then atomically replaces active
with an empty generation. Global sequence and previous hash continue from that
checkpoint. An interruption between checkpoint and active replacement is
intentionally fail-closed and requires operator recovery; it never silently
truncates or resets the chain.

Restore rehearsal first verifies every file digest and the backup manifest,
then copies only into a newly created `shadow-restore-rehearsal-*` directory
under an existing explicit scratch root. Cleanup rejects any target outside
that root or without the exact prefix. It never accepts `/` as scratch and never
overwrites a production path. No retention deletion command exists.

## Scheduled readiness boundary

The deployed backup task has read-only access to the journal and write access
only to `/var/backups/kairos-e2-shadow-primary`,
`/var/lib/kairos-e2-shadow-secondary` and the guarded restore scratch
`/var/lib/kairos-e2-shadow-restore`. A path unit reacts when the active journal
first appears; a persistent daily timer catches missed events and later drift.
An empty journal returns `ARMED_NO_RECORDS` and creates no bundle or state file.
Once records exist, the task requires two current, replay-equivalent bundles
and runs a restore rehearsal after producing a new pair.

Both current destinations are separate `0700` permission/storage boundaries
but share the host's `/dev/sda1` failure domain. Readiness therefore reports
`independentFailureDomains:false` and `producerReady:false`. These local copies
exercise and preserve the backup contract, but they do not satisfy the policy's
two-independent-copy requirement and cannot authorize retention deletion or a
runtime producer. One destination must move to independently mounted storage
before that gate can become ready.

## Disabled shadow submission boundary

KAIROS exposes `POST /internal/v1/shadow-decisions` only behind the existing
Ed25519 Relay service identity with the exact `shadow:write` scope, replay
protection, a 4 KiB body cap and `no-store`. The body must be the frozen
`shadow-submission.v1` envelope containing only validated EvidenceRecord and
DecisionEnvelope values. The authenticated principal proves caller authority
but is never written into the evidence or journal.

Two independent gates precede append: `KAIROS_E2_SHADOW_INGRESS_ENABLED=1` and
different filesystem device IDs for both configured backup destinations. Both
production flags are currently false, so even a correctly signed request gets
`503` and cannot create state. Relay's matching producer is also explicitly
disabled with `RELAY_E2_SHADOW_PRODUCER_ENABLED=0`; while disabled it does not
read its signing key or make a network request. It has no route or background
task wired to it.

The successful submission projection always returns `actionAllowed:false`,
including when the shadow combined verdict is ALLOW. Neither ingress nor
producer imports LUMI or execution/trading code. Hermetic wire compatibility
proves the Relay JSON payload is accepted by the frozen KAIROS contract without
enabling either production side.

The read-only daily verifier now also emits `shadow-metrics.v1`. It reconstructs
all verified records across generation checkpoints and publishes only frozen
aggregate counters. A signal outside `shadow-trigger-catalog.v1` makes the probe
fail closed. Empty state produces explicit zeroes and still creates no journal
or lock file.

`scripts/verify_shadow_journal.py` emits `shadow-operator-signal.v1` and exits
non-zero on any replay failure. Its read-only path takes a shared existing lock
and never creates the state directory, journal or lock. The supplied oneshot
unit has only read access and its daily timer writes the result to journald.
An absent journal is honestly reported as `journalPresent:false` with an empty,
valid genesis replay; this is expected while the producer is disabled.

The module remains disconnected from KAIROS scheduling, LUMI HTTP, trading and
money execution. A narrow authenticated shadow-only producer plus implemented
and restore-tested rotation/backups are still required before runtime use.
