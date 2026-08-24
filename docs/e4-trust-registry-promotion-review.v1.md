# E4 trust registry promotion review

Date: 2026-08-22 UTC
Route: E4 / owner-gated disposable full-snapshot rehearsal

The existing `e4-trust-root` key signed the exact promotion payload. The
promotion verifier rechecked the v4 registry candidate, owner payload v5,
owner signature, reviewer envelope/signature, exact target/snapshot/key
bindings, and the DigiCert RFC 3161 response using the pinned public CA chain.

Evidence:

- promotion payload SHA-256:
  `63635fad160683ca50496831e4cdcc418c346e226def3e612cfec0b7b1f8458a`;
- trust-root signature SHA-256:
  `5668d7eadffc3025edb940d3ed170b356c1262d63edbc97bb990eaa1ca91e713`;
- authenticated registry result: `AUTHENTICATED_ACTIVE`;
- timestamp: `2026-08-22T23:06:34Z`, `Verification: OK`;
- temporary replay claim: `CONSUMED`, claim ID
  `e4orr_6c04eca3ed40e2ab9a625424b615b44d338c4b5816123708cad6b2f09ea2ed29`.

The focused promotion harness passed 3/3, including tampered promotion and
tampered timestamp response failures. The replay ledger accepted one exact
claim and remains non-production. Full authority is still `NO_GO`: the sole
remaining blocker is `HARDENED_EXECUTOR_NOT_AVAILABLE`. The evidence does not
authorize Docker, PostgreSQL, production contact, credentials, snapshot
decryption or money actions.

Next canonical item: hardened executor review and implementation, including a
safe encrypted-snapshot key handoff that never stores the private key on the
server, network-none and read-only container controls, TOCTOU target binding,
bounded health/shutdown, teardown and absence proof. Do not retry the consumed
claim or create more signing keys.
