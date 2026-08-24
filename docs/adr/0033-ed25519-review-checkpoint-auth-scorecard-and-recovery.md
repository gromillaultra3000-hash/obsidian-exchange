# ADR 0033: Checkpoint authentication scorecard and recovery

Date: 2026-08-15

Status: gates and split-view matrix frozen; candidates unevaluated

ADR 0032 shortlisted dual DSSE and dual WebAuthn witnesses. This record defines
a conjunctive scorecard: all common and candidate-specific gates must pass with
current hash-bound evidence. No weighted compensation, automatic winner,
emergency single-witness mode or quorum degradation is permitted.

Common gates cover exact shared checkpoint bytes, two-domain independence,
nonce/freshness, rollback-resistant high-water state, equivocation quarantine,
root rotation/recovery, parser/dependency review and fail-closed availability.
DSSE additionally requires distinct active roots, exact DSSE/PAE, signer
isolation and two offline recovery rehearsals. WebAuthn additionally requires
two distinct witnessed enrollments, exact RP/origin, the ES256 UP/UV non-backup
profile and replacement/collusion procedures that preserve two human domains.

Same-sequence alternate heads, divergent descendants, a checkpoint ahead of the
local store or inconsistent transparency checkpoints quarantine the chain. Loss
of one witness or high-water state blocks. A local store ahead of its checkpoint
may only wait for a fresh checkpoint. Root rotation is reviewed, never automatic:
it requires independent recovery, a higher epoch, continuous predecessor and
old-root revocation. A revoked old root always rejects.

Quarantine never chooses a winning fork. Exit requires the complete conflict
set, control investigation, a new consumer-approved policy epoch and two
non-conflicting witness approvals, with continuity from the last uncontested
checkpoint or permanent retirement of the chain.

Both candidates remain `NOT_EVALUATED`. No witness, root, enrollment, RP, log,
high-water store, evidence or recovery action exists. Gate `i09`, all selection,
crypto and runtime/UniFFI permissions remain false.
