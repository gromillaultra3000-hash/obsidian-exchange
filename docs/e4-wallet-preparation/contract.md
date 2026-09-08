# E4 / WALLET_REVIEW_PREPARATION_CANCELLATION

The deployed Mini App permits asynchronous TON transfer and existing sell-payment
preparations. The reproduced defect is an older response opening a review after
the user cancelled a newer one. A preparation response is not a signature.

A shared review generation now invalidates pending preparation when another wallet
preparation starts, any review opens, the review closes or expires. Only the
current response may update preparation feedback and open a review. Both successful
JSON and rejected transport paths check the generation. Starting preparation
closes the previous review and clears its acknowledgement callback; later signing
still requires a fresh acknowledgement of the current response. Existing wallet
onConfirm callbacks and API payloads are byte-identical. No new writer, key,
credential, SDK, dependency or automatic retry is added.

Primary: implementation, native browser race checks and HTML-only rollout.
Independent acceptance: /root/wallet_acceptance, exact-source deterministic races.
Independent diff/operations: /root/wallet_diff_ops, callback equivalence, scope
checks and temporary atomic publication/reconcile/rollback rehearsal.
Playwright skill uses the existing non-root Chrome supervisor with PrivateNetwork
and ProtectHome. SDK and API boundaries are synthetic, with unusable transaction
fixtures and a rejecting signer. No external research or new plugin is required.

Surface matrix: Mini App REQUIRED; public site READ_ONLY for exact served template;
bot/payment APIs READ_ONLY for retained hashes and service state; admin/native
N/A because this slice adds no action on them. Accountable owner is the project
owner under current manual, reversible E4 delivery authorization.

Acceptance includes transfer/payment and cross-action response ordering, stale
transport/JSON errors, replacement buy/sell reviews, cancellation, visible-review
Escape, expiry and fresh acknowledgement. Browser uses shipped DOM/fetch/review
handlers and intercepted deferred responses. Escape with no visible review is
unchanged; no new pending-state cancellation control is claimed. An already
confirmed unresolved wallet handoff is a separately retained finding, not fixed
by preparation invalidation. Real Telegram/iOS/WebKit and human acceptance remain
open; no real wallet or money result is inferred from synthetic tests.

Rollout publishes only webapp.html after two reviews, tests, exact current file/
process inventory and public template preflight. Backup bytes and metadata are
verified before atomic replacement. No restart is required. On a post-write
verification failure inspect/reconcile the candidate or explicitly restore the
retained backup; never repeat apply under the assumption no replacement occurred.
The helper refuses unrelated live drift and changes outside the five allowed
functions plus the exact generation declaration. Earlier 064A authority remains
consumed and untouched.

Next canonical item: E4 / WALLET_PENDING_HANDOFF_SERIALIZATION — independently
reproduced overlapping unresolved wallet SDK handoffs remain separately bounded.
