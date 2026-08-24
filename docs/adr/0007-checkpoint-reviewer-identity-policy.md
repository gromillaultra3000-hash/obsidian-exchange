# ADR 0007: Checkpoint reviewer identity and attestation policy

Date: 2026-08-12

Status: Technology-neutral test policy frozen, credentials and activation blocked

## Decision

Checkpoint key-set review requires two reviewers from independent administrative
domains and independent credential roots. Different accounts under one IAM,
organization owner, recovery authority or CI control plane count as one domain.

Each future attestation must bind reviewer ID, trust-domain ID, credential-root
fingerprint, exact review-bundle digest, 32-byte challenge digest, monotonic
revocation epoch, issue/expiry and evidence ID. Maximum lifetime is ten minutes,
future clock skew is one second, and an evidence ID is single-use. The verifier
must use a revocation snapshot at the same epoch, reject revoked roots and reject
rollback below the previously accepted revocation epoch.

The policy review receives the active signer-slot set and rejects any reviewer
whose ID overlaps a signer slot. The two reviewers may not share an
administrative domain, credential root, root recovery authority or controlling
CI identity. At most one automated `reproducible_build` reviewer may participate.

## Non-authority invariant

This slice defines structural policy only. Synthetic fixtures do not authenticate
reviewers or verify attestations. No real root fingerprint, credential, signature,
revocation feed or identity provider is selected or installed. Passing structural
checks leaves authentication, acceptance, key installation, checkpoint trust and
production action false.
