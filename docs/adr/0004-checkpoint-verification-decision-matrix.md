# ADR 0004: Checkpoint verification decision matrix

Date: 2026-08-12

Status: Test-only decision contract frozen, runtime implementation blocked

## Decision

Future checkpoint approval verification must produce one deterministic terminal
decision. Failures are evaluated in this order:

1. `MALFORMED_BINDING`
2. `UNKNOWN_KEY_EPOCH`
3. `STALE_KEY_EPOCH`
4. `EXPIRED_APPROVAL`
5. `UNKNOWN_SIGNER`
6. `DUPLICATE_SIGNER`
7. `MALFORMED_SIGNATURE`
8. `INVALID_SIGNATURE`
9. `INSUFFICIENT_QUORUM`
10. `QUORUM_SATISFIED_NON_AUTHORITATIVE`

The test contract models exactly two distinct claims from a three-slot active
key set, matching the frozen 2-of-3 approval proposal. Missing claims are
insufficient quorum, while an oversized claim set or duplicate active slot is
malformed binding; malformed or cryptographically invalid claim outcomes are
reported separately. An epoch newer than the locally known active epoch is
unknown, not implicitly accepted. An older epoch is stale.

## Non-authority invariant

Even the final quorum outcome means only that the decision pipeline would have
enough valid claims. It does not install keys, accept a ceremony, trust a
checkpoint, verify the header chain, enable an action or authorize production.
Those booleans remain false for every decision.

The harness contains only symbolic non-trust fixtures. It contains no public or
private key bytes, no signature bytes, and no cryptographic verification call.
It is not compiled into the wallet libraries or exposed through UniFFI.
