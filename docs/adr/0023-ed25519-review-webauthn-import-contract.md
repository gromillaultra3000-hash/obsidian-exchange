# ADR 0023: Ed25519 review WebAuthn import contract

Date: 2026-08-15

Status: bounded import/result contracts frozen; verifier selection blocked

The Ed25519 corpus-review gate imports a WebAuthn assertion only through a
closed JSON envelope. The envelope carries the evidence ID and the five byte
fields returned by `navigator.credentials.get`; byte fields use canonical
unpadded RFC 4648 base64url and must reproduce their input after bounded decode.
Decoded limits are 1,024 bytes each for credential ID, authenticator data and
signature, 8,192 bytes for client data JSON, 64 bytes for user handle and
16,384 bytes for the complete envelope. The user handle is the only nullable
field. Unknown fields, padding, whitespace and non-canonical encodings fail.

The review response continues to contain only the assertion-envelope SHA-256.
An external verifier result is a separate closed record bound to the review
request and verifier-policy digests, assertion digest, ADR 0022 challenge,
evidence ID, credential root, revocation epoch, exact RP ID/origin, caller
nonce and an allowlisted verifier identity/build. It explicitly records the
result issue/expiry window, required WebAuthn type, ES256 algorithm, UP/UV,
non-backup flags, credential/revocation checks and signature result. Validation
order is frozen in the schema; caller nonces and evidence IDs must be
single-use, timestamps must be fresh and bounded, and `signCount` is
intentionally absent and non-authoritative.

The result is not self-authenticating: its signing/attestation mechanism and
the external verifier identity/build allowlist have not been selected. No
assertion, credential, RP, origin, verifier result or secret is checked in.
Therefore even a structurally all-green synthetic result cannot authenticate a
reviewer or permit an Ed25519 call. Runtime and UniFFI remain unchanged.
