# ADR 0036: Checkpoint witness semantics and preflight

Date: 2026-08-15

Status: strict semantic contracts frozen; crypto remains symbolic

ADR 0035 bounded the opaque evidence transports. This record freezes the local
DSSE witness statement and WebAuthn preflight that may run before candidate-
specific signature verification.

The DSSE payload is a closed JSON object containing only schema, witness slot/
domain/root, checkpoint/challenge digests, epoch, issue/expiry and the exact
`WITNESS` decision. Unknown and duplicate fields fail. Decoded input is limited
to 8 KiB, depth 4, 128 tokens and 256-byte strings. The DSSE payload type is
exact. Semantic comparison runs only after a test-only symbolic signature-
success outcome, preserving the rule that unauthenticated payload fields cannot
authorize a checkpoint.

WebAuthn client data is a closed object requiring exact `webauthn.get`, the
canonical Base64URL raw 32-byte ADR 0034 challenge and a consumer-allowlisted
origin. `crossOrigin` may be absent or false; `topOrigin` and unknown/duplicate
fields fail. Authenticator data is exactly 37 bytes: expected RP ID hash,
flags byte exactly `0x05` (UP+UV only), and advisory four-byte sign count.
Backup, attested-credential, extension and reserved bits fail. Extensions are
deliberately absent to keep the parser surface closed.

After preflight, an external consumer-selected credential lookup must still
check exact credential ID, ES256 algorithm, enrollment/user handle, active root
and revocation before signature verification. None of those operations exists.
The DSSE root and signature outcomes and the WebAuthn ES256 outcome remain
symbolic; structural success authenticates nothing.

No real payload/assertion, root, credential, lookup, signature verification,
checkpoint acceptance, crypto permission or runtime/UniFFI integration exists.
Gate `i09` remains false.
