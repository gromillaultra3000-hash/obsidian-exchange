# ADR 0002: Checkpoint signature verification algorithm

Date: 2026-08-12

Status: Selected, test-only verifier harness complete, activation blocked

## Decision

Future checkpoint-approval verification will use BIP340 Schnorr signatures over
secp256k1. The frozen profile is `BIP340_SECP256K1_XONLY_SHA256`: a 32-byte
x-only encoded public key, a 64-byte signature and an exact 32-byte message
digest. The application message is independently bound to
`OBSIDIAN_CHECKPOINT_APPROVAL_V1` before it may reach the verifier.

This is a verification-only decision. It adds no signing interface, trust-key
material, key installation, checkpoint trust, chain verification or execution
authority.

## Provenance

The existing locked dependency graph is retained rather than adding a second
cryptography implementation:

- `bitcoin` 0.32.102 (direct, default features disabled);
- `secp256k1` 0.29.1 (locked transitive dependency);
- `secp256k1-sys` 0.10.1 (locked transitive binding).

The normative algorithm specification is
[BIP 340](https://github.com/bitcoin/bips/blob/master/bip-0340.mediawiki).
The official CSV is pinned at bitcoin/bips revision
`c38071c8c45a1fc50cecaac0d82d99e3bbd56911` with SHA-256
`34c9d1d9c3a88d524bc80778540dc43f8306ec249a7485293063c376db851c2d`.
The test-only parser exercises every row. The frozen 32-byte-digest profile is
verified through the dependency's BIP340 API; the four upstream arbitrary-size
message cases are parsed and explicitly classified outside this narrower
application profile. No application verification or signing API is exposed.

## Activation gate

The application verifier remains unimplemented and disabled. The pinned CSV,
strict parser and mutation harness are test-only. Tests cover every official
row in the selected profile, malformed schema/result/hex and key, signature and
message mutations. Domain binding still belongs to the later application
verifier boundary and cannot be inferred from this primitive harness.

Real trust-key bytes, an allowlist, lifecycle execution and any transition from
an approval proposal to trusted checkpoint status require separate review and
explicit authorization.
