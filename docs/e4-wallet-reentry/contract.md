# E4 / WALLET_HANDOFF_REENTRY_COVERAGE / OUTCOME_GUIDANCE

Assessment reproduced two bounded UX gaps: generic wallet SDK errors give only
'not confirmed' without a verification route/no-repeat instruction, and fresh
wallet reviews lack a prior-attempt/reload warning. A new page also resets the
in-memory lock. The browser probe demonstrates page-state reset with an inert SDK;
it does not demonstrate real wallet SDK reconnection or an actual transfer.

Exactly four literals change. Transfer and sell-payment review risk copy asks users
who already attempted the transfer or returned after reload to check the connected
wallet's operation history (and sell order status) before proceeding. While the
previous result is unclear, do not repeat. Generic SDK catch feedback conservatively
states that the outcome is unknown and the transfer may have been sent, with the
same verification route/no-repeat guidance. Explicit SDK error types are not
classified, and no rejected promise is treated as proof of absent transfer.
Existing success, request/SDK payloads, guards, callbacks and acknowledgement
semantics are unchanged. These are instructions, not a durable or cross-tab lock.

Primary owns four-string patch, full-page browser checks and HTML rollout;
/root/reentry_acceptance independently tests fresh review and SDK failure/success;
/root/reentry_diff_ops independently proves literal-only diff equivalence and
rehearses atomic publication/rollback failures in temporary files. Existing
Playwright supervisor provides nobody/Chromium sandbox/PrivateNetwork/ProtectHome
and verified cleanup. All wallet and API fixtures are inert; no SDK or dependency
is added. No external research/plugin is required for this copy change.

Surface matrix: Mini App REQUIRED (actual wallet buttons and review); public site
READ_ONLY (exact HTML delivery); bot/payment READ_ONLY (retained inventory/runtime);
admin/native N/A. Accountable owner is project owner under manual reversible E4
continuation. No real customer authenticated request, wallet signature, provider
operation, key/credential, money change or 064A authority.

Acceptance includes baseline red/candidate green, unchanged success and request,
fresh/reloaded review guidance before acknowledgement, generic/synchronous errors,
no automatic retry, and 320/390 native-browser layout. First browser attempt used
an empty wallet fixture and could not reach Send; corrected fixture represents a
synthetic connected TON wallet. Product did not change during harness correction.
Real Telegram/iOS/WebKit/assistive technology and human comprehension remain open.

Publication changes only webapp.html after exact 56-file/process/public-template
preflight and two reviews; verified backup precedes atomic replace. No service
restart. Failed post-write public verification requires explicit reconcile or
rollback, never blind reapply. Rollback rejects unrelated live drift.

Exactly next: E4 / WALLET_HANDOFF_REENTRY_STATE — preserve unresolved-attempt
evidence across same-tab reload with an explicit reconciliation path and no
automatic signing. Current generic guidance does not persist or reconcile an
attempt, and real SDK reconnection remains unverified.
