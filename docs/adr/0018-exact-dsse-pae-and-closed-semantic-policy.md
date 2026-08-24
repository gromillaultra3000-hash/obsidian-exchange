# ADR 0018: Exact DSSE PAE and closed semantic policy

Date: 2026-08-12

Status: Isolated PAE and semantic policy pass; signature verification blocked

The isolated `automated-minimal` rehearsal now constructs DSSE 1.0.2
pre-authentication encoding directly from the original payload-type string and
the exact decoded payload byte slice. Decimal byte lengths are computed without
JSON parsing or reserialization, capacity arithmetic is checked, and arbitrary
payload bytes—including non-UTF-8 bytes—are preserved. The safe public ADR 0015
reference PAE is reproduced byte-for-byte.

Only the exact `application/vnd.in-toto+json` envelope type passes the outer
policy. After a test-only symbolic signature-success gate, strict payload
parsing is followed by an externally supplied closed expectation. It requires
exact in-toto Statement v1 and SLSA provenance v1 identifiers, one exact
subject and lowercase 64-hex SHA-256 digest, exact build type, builder,
profile, target and an exact ordered dependency sequence. Expected and observed
URIs must be ASCII absolute HTTPS forms (dependencies may use `git+https`),
without whitespace, fragments, queries or userinfo; dependency URIs must be
unique. Claim drift, uppercase/malformed digests and dependency reordering fail.

The symbolic signature outcome exists only inside unit tests to prove that
payload semantics are not evaluated on rejection. The `sig` field remains
opaque: no Base64 signature decoding, public key, trust root or Ed25519 API is
present. PAE construction is not verification, successful semantic comparison
grants no authority, and nothing is integrated into native runtime or UniFFI.
