# E4 / TONCONNECT_VERIFY_RESPONSE_RECIPIENT_BINDING

2026-09-09. Continue canonical E4; accepted owner iPhone interface observation
remains complete without a local-report requirement. Full E4 remains IN_PROGRESS.

An asynchronous tcHandleWallet verification begun for TON currently overwrites
a subsequently selected BTC/manual recipient when its response arrives. Bind
application of verification to the initiating valid TON wallet-connect route,
address, memo/no-tag and a monotonically increasing local edit/status generation.
Compare again after the response body resolves. User edits away and back must
invalidate the response; equality alone is insufficient. Observe native input/
change in capture phase and explicit programmatic route/address-book changes.
A disconnect or any newer SDK status invalidates the old response even while
verification is pending. Same-route background refresh without changes stays valid.

Apply only HTTP-success responses with verified exactly true and a nonempty,
bounded string address. The backend remains the verification authority; this
change does not implement proof verification. Successful substitution clears the
old memo before selecting no-tag. Obsolete success/failure must not mutate the
recipient, validation, confirmation message, haptics or profile refresh. Manual
input remains available. No real wallet signatures or verification requests in
tests, and no money operation is authorized by this slice.

Required surface: Mini App recipient selection and TON verification completion.
Backend, wallet SDK setup/preparation, submission/review payloads, Sell and other
surfaces are read-only. Existing pending serialization retained. SDK preparation
and request deadlines are separate work, not claimed resolved by this guard.

Primary owns product implementation and existing regressions; independent
acceptance agent owns adversarial and isolated native Chrome cases; independent
ops agent reviews the diff and authors bounded rollout/rollback rehearsal.
Scope: generation/helper/event-listener block, tcHandleWallet, and explicit
invalidation calls in applyOfferings, loadAddressBook, updateAddressPlaceholder.
Tests must reproduce old behavior and cover eligible success, obsolete routes/
recipient/tag, away/back edits, SDK disconnect/status, deferred JSON, errors,
malformed success and programmatic route/address changes. Test no unintended POST.

After proportional tests, two reviews and secret scan, atomically replace only
HTML with exact preimage/metadata backup and pinned reviewed candidate. Verify
public bytes,55 unrelated live inputs and four service identities; no restart.
Reconcile in the same iteration. Existing pages get the fix on reload.
