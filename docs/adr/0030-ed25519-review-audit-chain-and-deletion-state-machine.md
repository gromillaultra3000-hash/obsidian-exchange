# ADR 0030: Audit chain and deletion state machine

Date: 2026-08-15

Status: symbolic contracts frozen; persistence and side effects absent

ADR 0029 defines minimized audit fields and deletion receipts. This record
freezes deterministic event hashing and a deletion-rehearsal state machine. It
does not create an audit store or authorize deletion.

Each closed audit event is SHA-256 over a domain-separated ordered binary
preimage containing its monotonic sequence, bounded identifiers/type/time,
object and policy digests, the previous event digest, decision and reason code.
Text is length-prefixed UTF-8, integers are u64 big-endian, digests are raw
32-byte values and the first event uses 32 zero bytes as its predecessor. A
fixed vector prevents serialization drift. Events allow no free text and may
never be updated or deleted. The chain detects omission, mutation and reorder
when an independently retained checkpoint is available; it does not by itself
make mutable storage append-only or prove completeness.

Deletion proceeds `PLANNED → CLAIMED → DELETING → SCANNING →
AWAITING_WITNESS → COMPLETE`. Invalid plans or proven pre-side-effect failures
may become `FAILED`. Any partial or unknown side effect, scan mismatch, witness
rejection/timeout or ambiguous crash becomes terminal `REVIEW_REQUIRED`.
Automatic retry is forbidden after any deletion side effect. A later manual
attempt requires a new plan linked to the prior receipt.

A crash in `PLANNED` may be claimed once. A crash in `CLAIMED` can resume only
with durable proof that no side effect began. During deletion, every location
outcome must be durable; otherwise review is mandatory. Scans and witness checks
may repeat over identical digests because they are read-only, but deletion may
not. Audit append must become visible before the corresponding state transition.

No persistence, checkpoint, worker, file operation, audit event or deletion
attempt exists. Gate `i09`, issuer/verifier selection, crypto calls and runtime/
UniFFI integration remain false.
