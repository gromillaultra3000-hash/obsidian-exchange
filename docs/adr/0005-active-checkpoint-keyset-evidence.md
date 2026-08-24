# ADR 0005: Synthetic active checkpoint key-set evidence

Date: 2026-08-12

Status: Test-only evidence contract frozen, installation and trust blocked

## Context

The existing design-only ceremony stores three sorted key IDs and three sorted
key-material commitments as independent sets. It proves set membership but does
not prove which key belongs to which signer slot. Treating parallel list order
as a mapping would silently invent an invariant that the ceremony never signed.

## Decision

`native-checkpoint-active-keyset-evidence.v1` binds a ceremony digest, exact
epoch and `BIP340_SECP256K1_XONLY_SHA256` algorithm to three sorted records:

```text
signerKeyId -> xOnlyPublicKey -> keyCommitment
```

Each key must be canonical lowercase 32-byte hex and parse as a secp256k1
x-only public key. Its commitment is
`SHA256("OBSIDIAN_CHECKPOINT_KEY_COMMITMENT_V1" || 0x00 || keyBytes)`.
The sorted commitment set must exactly equal the ceremony's committed set and
the signer IDs must exactly equal its ID set. Reviewer IDs are distinct, sorted,
opaque and cannot overlap the signer slots. The evidence digest length-prefix
binds each mapping record, the ceremony digest, epoch, algorithm, two distinct
reviewer claims and review time.

## Non-authority invariant

The review identifiers remain claims, not authenticated reviewers. Therefore
successful validation means only content/set/mapping binding. It explicitly
leaves reviewer verification, key installation, active-key authority,
checkpoint/chain trust and every action permission false. The harness is
test-only, uses public non-trust fixtures, contains no private keys or signing,
and is absent from library and UniFFI surfaces.
