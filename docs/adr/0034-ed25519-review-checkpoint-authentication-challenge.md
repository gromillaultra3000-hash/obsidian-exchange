# ADR 0034: Checkpoint authentication challenge

Date: 2026-08-15

Status: exact preimage and vector frozen; signatures/assertions blocked

ADR 0033 requires both witnesses to authenticate the same checkpoint while
remaining non-interchangeable. This record freezes a slot-specific SHA-256
challenge over an ordered binary preimage. It binds the checkpoint schema and
exact-byte digests, chain, policy, audit sequence/head, previous checkpoint,
epoch, caller nonce, issue/expiry window and the witness slot, domain,
authentication root, recovery authority and host failure domain.

Text fields are non-empty u16-length-prefixed UTF-8, digests are raw 32 bytes,
ordinary integers are u64 big-endian and witness slot is one byte (`0` or `1`).
The predecessor has a presence byte: null genesis is `0` plus 32 zero bytes;
non-genesis is `1` plus its raw digest. This prevents an all-zero digest from
aliasing null. The lifetime remains at most ten minutes. A fixed vector and
all-field mutation tests prevent serialization or field-order drift.

For DSSE, each closed witness statement binds its slot challenge and exact
checkpoint digest, and DSSE signs the exact statement bytes. For WebAuthn, the
raw 32-byte slot challenge is the `clientDataJSON` challenge input. Evidence for
slot 0 cannot satisfy slot 1; changing chain, policy, epoch, root, recovery or
host changes the challenge. The checkpoint's caller nonce remains single-use,
so neither slot can be replayed into another checkpoint.

This contract constructs hashes only. It does not parse or verify DSSE,
WebAuthn, ES256, roots, assertions or signatures. No witness is enrolled and no
real evidence exists. Checkpoint authentication, gate `i09`, crypto calls and
runtime/UniFFI integration remain false.
