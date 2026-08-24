# ADR 0025: Ed25519 review verifier selection scorecard

Date: 2026-08-15

Status: fail-closed gates frozen; no option evaluated or selected

ADR 0024 shortlisted local pinned execution and a DSSE-signed closed result as
the two primary verifier-result authentication patterns. This record defines a
conjunctive scorecard, not a weighted score. Every common and option-specific
mandatory gate must be `PASS` with hash-bound evidence. `FAIL`, `UNKNOWN`,
`NOT_EVALUATED` or missing evidence blocks selection; a strong property cannot
compensate for an absent replay, revocation, recovery or execution guarantee.

Ten common gates cover exact closed bytes, complete cross-binding, signed build
provenance, two-builder byte reproducibility, policy identity, atomic freshness
and replay handling, parser parity, independent administration, rehearsed
rotation/recovery and dependency/license review. Local execution additionally
requires a private peer-authenticated process boundary, measurement of the
actual executable/policy/dependencies and host failure-domain separation. A
DSSE result additionally requires a purpose-limited result key, consumer-chosen
root/epoch/revocation, enforced signer-to-measured-verifier binding and rehearsed
key-compromise recovery without rollback.

Independence evidence is a closed, time-bounded record. Across the two reviews,
reviewer, credential, recovery, verifier administration/recovery, result-root,
host and evidence-issuer identities must all differ. Within each review, the
credential, verifier and result roots differ; reviewer and verifier recovery
authorities differ; and the two reproducible builders have distinct roots. A
string inequality is necessary but not sufficient: supporting evidence and a
conflict-of-control review remain mandatory.

If both options eventually pass, there is no automatic winner. A later ADR must
choose the smaller independently reviewed trust and runtime surface. Currently
every gate is `NOT_EVALUATED`; issuer authentication for independence evidence
is undefined, and no real evidence exists. No option, key, root, verifier,
credential, assertion, crypto call or runtime/UniFFI integration is enabled.
