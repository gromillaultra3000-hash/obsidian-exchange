# ADR 0022: Ed25519 corpus reviewer authentication profile

Date: 2026-08-12

Status: WebAuthn profile and challenge binding frozen; implementation blocked

Human corpus reviews reuse the already selected reviewer profile from ADR 0008:
`WEBAUTHN_L3_CTAP22_ROAMING_ES256_UV`. This avoids introducing a second human
identity mechanism solely for the Ed25519 corpus gate. Reviewers must use
non-backup-eligible roaming authenticators with UP and UV, exact allowlisted RP
ID/origin, pinned enrollment provenance, independent credential/recovery roots,
a monotonic revocation snapshot and a single-use evidence ID. `signCount`
remains advisory.

The challenge is SHA-256 over an ordered binary preimage. Text fields use a
two-byte big-endian byte length followed by exact UTF-8; digests are raw 32-byte
values and epochs/timestamps are unsigned 64-bit big-endian values. The preimage
binds the domain separator, review-request digest, reviewer and trust-domain IDs,
evidence ID, credential-root digest, recovery-authority ID, revocation epoch and
issue/expiry window. Maximum lifetime is ten minutes. The raw assertion is a
separate bounded envelope referenced by SHA-256, not embedded in the response.

The response schema now requires this exact profile and context. It no longer
contains the generic authentication placeholder. This is still a structural
contract: no RP, origin, credential, authenticator, assertion, public key,
revocation source or verifier is installed. The request continues to prohibit a
crypto call and runtime integration, and two real independently authenticated
reviews are still absent.
