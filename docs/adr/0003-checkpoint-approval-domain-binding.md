# ADR 0003: Checkpoint approval signature-message binding

Date: 2026-08-12

Status: Test-only contract frozen, implementation and activation blocked

## Decision

Each future checkpoint-approval signature will verify an exact 32-byte message
derived with BIP340-style tagged SHA-256. The immutable UTF-8 tag is
`OBSIDIAN_CHECKPOINT_APPROVAL_V1`. The message is:

```text
tagHash = SHA256(tag)
message = SHA256(tagHash || tagHash || payload)
```

The binary payload is ordered and unambiguous:

```text
u16be(schemaLength) || schemaUtf8 ||
u16be(algorithmLength) || algorithmUtf8 ||
approvalContentSha256[32] || checkpointArtifactSha256[32] ||
keyCeremonySha256[32] || u32be(keyEpoch) ||
u16be(signerKeyIdLength) || signerKeyIdUtf8 || u64be(expiresAtEpochMs)
```

The schema is `native-checkpoint-approval-signature-message.v1`; the algorithm
is `BIP340_SECP256K1_XONLY_SHA256`. SHA-256 values use exactly 64 lowercase hex
characters at the text boundary and become raw 32-byte values in the payload.
The signer identifier follows the existing lowercase opaque-ID grammar and is
bound individually so one signer's signature cannot be replayed as another's.

## Security boundary

The contract binds context only. The harness is compiled as an integration
test, not into either wallet library. It accepts no public key or signature and
does not expose verification or signing through UniFFI. It installs no key,
changes no lifecycle epoch, and cannot set checkpoint or chain trust.

A later separately reviewed verifier must first validate the complete approval
proposal and active key-set evidence, reconstruct this message independently,
then invoke BIP340 verification. Domain, schema, algorithm, digest, epoch,
signer, expiry or byte-order drift must fail closed.
