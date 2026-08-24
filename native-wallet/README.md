# Obsidian native wallet

Hermetic foundation for the future native non-custodial wallet. The first
vertical slice is Bitcoin Signet. Production networks and real key operations
remain deliberately absent.

- `wallet-core`: domain contracts plus a pinned rust-bitcoin address parser.
- `wallet-ffi`: narrow UniFFI adapter for Swift/Kotlin.

The current API creates display-bound preview drafts with checksum/network
validation, a canonical output set and each exact destination scriptPubKey. The
fee is derived exclusively from total inputs minus total outputs. It cannot
generate a seed, derive a key, sign, persist, broadcast or contact a server.
The preview also binds Bitcoin transaction version two, consensus lock time and
a canonical set of previous outpoints/sequences. Its displayed SHA-256 must
match the core-built unsigned consensus serialization exactly.

Every input also carries a fresh, content-addressed Signet UTXO snapshot from
the allowlisted Bitcoin Core snapshot contract. The digest binds its block,
outpoint, value, sequence, previous script and consensus-encoded `MerkleBlock`.
The core locally verifies the header hash, Merkle root and exact TXID inclusion.
This is explicitly labelled
`TX_INCLUSION_VERIFIED_CHAIN_AND_UTXO_STATE_NOT_VERIFIED`: the offline core
performs no RPC, trusted-header-chain validation or unspent-state verification.

A bounded sequence of one to 144 headers must link an external checkpoint to
the Merkle-proof block with exact height continuity. The checkpoint kind is
deliberately `UNREVIEWED_EXTERNAL_SIGNET_CHECKPOINT_V1`; linkage can be true,
but checkpoint trust and chain verification remain false because Signet
challenge and difficulty-schedule consensus are not implemented in this slice.

The checkpoint also carries `native-signet-checkpoint-review.v1`: two distinct
sorted source digests and two distinct opaque reviewer identifiers bound to the
exact network, height, hash and review time. This validates the integrity of
review claims only. Reviewer identity and source authenticity are not proven,
so the checkpoint remains untrusted.

An offline `native-signet-checkpoint-approval-proposal.v1` binds that artifact
to a strict 2-of-3 policy: three sorted opaque signer key IDs, two distinct
sorted signature-byte digests and a short expiry. It validates proposal shape
and content only. No public keys or signature verifier are embedded, so
`approval_signatures_verified` and checkpoint trust remain false.

The initial `native-checkpoint-trust-key-ceremony.v1` freezes epoch one with
three key slots, three external key-material commitments, three distinct
participants and two transcript digests. The approval signer set must exactly
match these slots. Algorithm remains `UNDECIDED`; no public keys are accepted,
installed or used, and initial predecessor/revocation fields must be empty.

A separate pure lifecycle review validates an epoch-one to epoch-two rotation
and an emergency epoch-one revocation proposal. Rotation requires three wholly
new slots, commitments, participants and transcript evidence; revocation names
only predecessor slots with bounded reason/evidence/observer fields. Both are
available through UniFFI but always return execution, key-change and algorithm
selection as false.

The future checkpoint verifier algorithm is frozen separately as BIP340
Schnorr over secp256k1 with x-only keys and application domain
`OBSIDIAN_CHECKPOINT_APPROVAL_V1`. The read-only UniFFI contract records the
exact locked dependency versions. The verifier remains unimplemented and
disabled pending the separate application-level approval, active-key and trust
gates; no trust keys, signing capability, checkpoint trust or chain verification
are enabled.

The official BIP340 CSV is vendored test-only at bitcoin/bips revision
`c38071c8c45a1fc50cecaac0d82d99e3bbd56911`; its byte-exact SHA-256 and
license provenance are recorded beside the fixture. A strict parser covers all
19 rows and the existing secp256k1 dependency verifies the 15 rows belonging to
the frozen 32-byte-digest profile. This exposes no runtime verifier or signing
surface and installs no trust key.

The test-only application message-binding harness uses the exact tagged
SHA-256 preimage from ADR 0003 and rejects unsupported domains and malformed
context. It is not compiled into the libraries or exposed through UniFFI.
