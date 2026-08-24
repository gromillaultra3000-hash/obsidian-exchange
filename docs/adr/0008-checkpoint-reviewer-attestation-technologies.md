# ADR 0008: Checkpoint reviewer attestation technologies

Date: 2026-08-12

Status: Profiles selected for offline contract design; implementation blocked

## Requirements

ADR 0007 requires two independent administrative, credential and recovery roots,
ten-minute freshness, single-use challenges, monotonic revocation and no more
than one automated reviewer. Verification must work without a live identity or
transparency service and must bind the exact review-bundle digest.

## Human reviewer comparison

| Option | Strengths | Weaknesses | Decision |
|---|---|---|---|
| WebAuthn Level 3 + CTAP 2.2 roaming authenticator | Hardware-scoped credential, challenge/origin/RP binding, UP/UV flags, mature cross-platform protocol | Requires controlled RP/origin and enrollment; signature counter may remain zero; attestation privacy/chain policy is complex | Selected |
| OpenSSH FIDO security-key signature | Excellent offline tooling, namespace separation, touch/UV support | OpenSSH-specific envelope; organizational identity and revocation remain out-of-band | Fallback for rehearsal only |
| PIV smart card | Mature enterprise issuance, identity proofing and PKI revocation | Heavy CA/CRL operations and weak portability outside managed organizations | Conditional enterprise alternative |
| OpenPGP v6 | Generic offline document signing and revocation model | Large flexible format, greater parser/policy surface, hardware binding not inherent | Not selected |

The selected human profile is
`WEBAUTHN_L3_CTAP22_ROAMING_ES256_UV`. It requires a non-backup-eligible roaming
authenticator, UP and UV, exact allowlisted RP ID/origin, exact challenge, pinned
credential ID/public key and verified enrollment provenance. `signCount` is an
advisory clone signal only and never replaces the consumed-evidence ledger.
Enterprise attestation, if used, is restricted to controlled enrollment and is
not emitted during ordinary review.

## Automated reviewer comparison

| Option | Strengths | Weaknesses | Decision |
|---|---|---|---|
| in-toto Statement v1 + SLSA Provenance v1.2 + DSSE 1.0.2 | Standard artifact/predicate binding, builder identity and parameters; DSSE separates payload type; offline verification | Does not itself prove reproducibility; trusted builder/root expectations remain local policy | Selected |
| Sigstore keyless bundle | Strong identity/transparency ecosystem and portable bundles | OIDC, CA and transparency roots add online/shared control planes | Supplemental evidence only |
| Raw detached Ed25519 signature | Small verifier and offline operation | Omits provenance schema, builder/input expectations and artifact semantics | Insufficient alone |
| OpenPGP signed build report | Offline and widely tooled | More format/key-policy surface than DSSE and weak standardized build semantics | Not selected |

The selected automated profile is
`INTOTO_V1_SLSA_PROVENANCE_V1_DSSE_1_0_2_ED25519`. The in-toto subject must bind
the exact rebuilt artifact digest. The verifier must pin `predicateType`,
`builder.id`, `buildType`, canonical source revision, resolved dependencies and
all recognized external parameters, rejecting unknown parameters. DSSE
`payloadType` is exact and its unauthenticated `keyid` is only a lookup hint.
The Ed25519 credential root is independently administered and inaccessible to
user-controlled build steps. Reproducible byte equality is an additional local
requirement; provenance alone is not equality proof.

## Pinned standards

- W3C Web Authentication Level 3, current published document reviewed
  2026-08-12: `https://www.w3.org/TR/webauthn-3/`.
- FIDO CTAP 2.2 Proposed Standard, 2025-07-14:
  `fido-client-to-authenticator-protocol-v2.2-ps-20250714`.
- in-toto Attestation Framework tag `v1.2.0`, Statement type
  `https://in-toto.io/Statement/v1`.
- SLSA specification 1.2, approved; predicate type
  `https://slsa.dev/provenance/v1`.
- DSSE protocol 1.0.2, 2024-05-10.
- Ed25519 as specified by RFC 8032.

## Activation blockers

No SDK, parser, browser/RP, authenticator, builder, signing key, credential,
root, revocation source or network service is installed or selected by vendor.
Before implementation, pin conformance vectors, define exact canonical parsing,
review dependency provenance/licenses, and rehearse both profiles in disposable
offline environments. All current authentication, acceptance, key installation,
checkpoint trust and action flags remain false.
