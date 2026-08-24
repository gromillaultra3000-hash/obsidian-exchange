# ADR 0028: Independence-issuer authentication scorecard

Date: 2026-08-15

Status: conjunctive gates frozen; both candidates unevaluated

ADR 0026 shortlisted threshold DSSE and dual human WebAuthn as authentication
patterns for issuers of ADR 0027 independence evidence. This record defines a
conjunctive scorecard. Every common and option-specific gate must be `PASS` with
current hash-bound evidence. `FAIL`, `UNKNOWN`, `NOT_EVALUATED` or missing
evidence blocks the option; no weighted score or compensating control exists.

The scorecard handoff is a closed object. It must bind canonical SHA-256
references for the scorecard itself, the independence record, supporting bundle,
conflict matrix and issuer challenge, plus the exact review-domain identity.
Omitted or extra context fields, non-canonical references or context drift
invalidate the handoff. Gate evidence is likewise a closed map of the exact gate
IDs and canonical digest references; an omitted or unknown gate cannot be
bypassed.

Ten common gates require exact challenge and complete bundle binding, a fully
evidence-backed conflict matrix, two independent issuers, absence of issuer
control over reviewed subjects, atomic nonce/evidence replay protection,
separate root recovery, parser corpus parity, privacy/retention discipline and
dependency/incident readiness.

Threshold DSSE additionally requires enforced 2-of-3 unique active roots, role
separation that prevents ordinary signers changing threshold/root/revocation,
bounded exact-byte DSSE parsing and independently witnessed offline root and
recovery ceremonies. Dual WebAuthn additionally requires separate witnessed
roaming-authenticator enrollments, exact RP/origin with no fallback, ES256 plus
UP/UV and non-backup flags, and controls preventing one operator or colluding
control domain from satisfying both approvals.

Neither candidate can currently pass. Threshold DSSE has no roots, ceremony,
role policy, parser or recovery evidence. WebAuthn has no RP, origin, enrollment,
authenticator, assertion verifier or human issuer evidence. If both eventually
pass, a later ADR must choose the smaller independently reviewed trust, parser,
recovery and operational surface; there is no automatic winner.

The test-only evaluator verifies the exact gate inventories and minimum evidence
cardinalities, requires every evidence reference to be a canonical digest, and
rejects gate omission, extra IDs, invalid states and evidence drift. It remains
a structural predicate only: an all-pass synthetic map cannot mutate the frozen
`NOT_EVALUATED` state or grant issuer authentication.

The final decision boundary has four non-authoritative outcomes: no candidate
evaluated, one candidate requiring an explicit owner plus independent-reviewer
decision, a tie requiring a separate ADR, or invalid state. Automatic selection
is forbidden; synthetic all-pass input, selected-option drift or any capability
flag change is rejected rather than promoted.

The decision is carried only in a closed immutable result envelope. Its canonical
self-digest covers the outcome, candidate, `selected_option:null`, exact handoff
context digest, all five source digests, review domain, timestamps and caller
nonce. The envelope requires a unique decision ID and caller nonce, a ten-minute
maximum lifetime and bounded future skew; consumers must reject either ID or
nonce replay. The envelope is evidence of a decision boundary, not issuer
authentication or selection authority.

No option, issuer, root, credential, assertion, key or runtime surface is
selected or installed. Issuer authentication, verifier selection, crypto calls
and runtime/UniFFI integration remain false.
