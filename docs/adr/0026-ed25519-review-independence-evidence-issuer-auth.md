# ADR 0026: Independence-evidence issuer authentication

Date: 2026-08-15

Status: shortlist and challenge frozen; issuer enrollment blocked

ADR 0025 requires authenticated evidence that reviewer, verifier, builder,
recovery and host failure domains are genuinely independent. A self-asserted
issuer ID is insufficient. This record defines the issuer challenge and three
candidate authentication patterns without selecting or enrolling any issuer.

The challenge is SHA-256 over an ordered binary preimage. It binds the exact
independence schema, selection scorecard and evidence-record digests; issuer and
trust-domain identities; consumer-selected authentication root; separate
recovery authority; monotonic revocation epoch; single-use caller nonce; and a
maximum ten-minute issue/expiry window. Text is non-empty length-prefixed UTF-8,
digests are raw 32-byte values and integers are unsigned 64-bit big-endian.
The verification-only contract keeps this field order closed, rejects an expired
or over-future context, requires the consumer's root and current revocation
epoch, and rejects a caller nonce already present in the consumer replay set.

The primary candidates are a 2-of-3 threshold DSSE statement under independent
offline roots and dual human WebAuthn issuers with separate roaming credential
and recovery roots. Hardware-attested evidence service remains deferred because
of vendor, measurement, parser and recovery complexity. Threshold signatures
prove authorized key use, not that an investigation was correct; human approval
can be wrong or collusive. Neither is sufficient without supporting evidence,
conflict-of-control review, monotonic revocation and atomic nonce consumption.

At least two authenticated issuers must differ by identity, trust domain,
authentication root, recovery authority and host failure domain. No issuer may
administer the reviewer, verifier or builders it evaluates. The same mechanism
may be used twice only when every administrative and recovery root is actually
independent; string inequality alone is not proof.
Each independence record also has a closed schema and `INDEPENDENT` decision,
requires distinct credential, verifier-administration and result roots, distinct
review and verifier recovery authorities, and distinct builder roots within the
record. Across records, all nine declared pairwise fields must differ; malformed,
replayed, expired or structurally reused records cannot satisfy the pair policy.

No option is selected. No issuer, root, recovery authority, assertion, key,
verifier or runtime surface exists. Issuer authentication, independence-evidence
acceptance, verifier selection, crypto calls and runtime/UniFFI integration all
remain false.
