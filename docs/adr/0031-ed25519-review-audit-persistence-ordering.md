# ADR 0031: Audit persistence ordering and fault matrix

Date: 2026-08-15

Status: symbolic transactional contract frozen; backend absent

ADR 0030 requires audit visibility before state visibility. For internal state
changes, this record makes that requirement atomic: lock state and audit head,
compare expected state/sequence/head, validate, stage the immutable event first,
stage the state referencing its digest, then commit event, head and state in one
transaction. Nothing is published before commit. A crash before commit exposes
neither half; a crash after commit exposes both exactly once, so recovery reads
the authorizing event instead of repeating the transition.

External deletion cannot be atomic with a database transaction. Each inventory
location therefore has one immutable attempt intent. A transaction appends the
prepared event and inserts `PREPARED`; the executor invokes deletion at most
once; another transaction appends the exact outcome and moves to `SUCCEEDED` or
`FAILED`. If invocation may have begun but no durable exact outcome exists, the
only recovery is `UNKNOWN_REVIEW`. Neither `PREPARED` nor `UNKNOWN_REVIEW` may
be automatically invoked again. This contract makes no distributed-transaction
or exactly-once side-effect claim.

The fault matrix covers crashes before/staged/committed internal transitions,
before/during/after external effects, after outcome commit, during repeatable
read-only scans and while an independent audit checkpoint is unavailable.
Read-only scan, receipt validation and witness evaluation may repeat over the
same digests. A locally valid hash chain without an independently authenticated
checkpoint cannot satisfy gate `i09`.

This is an in-memory symbolic model only. No persistence backend, database,
table, worker, checkpoint, audit record or deletion effect exists. Gate `i09`,
issuer/verifier selection, crypto calls and runtime/UniFFI integration remain
false.
