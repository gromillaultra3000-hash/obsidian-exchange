# E4 / WALLET_PENDING_HANDOFF_SERIALIZATION

Within one open Mini App document, a pending wallet SDK call must prevent another
wallet transfer or sell-payment handoff, including across action types and stale
confirmation callbacks. The prior code allows overlapping sendTransaction promises
from separately acknowledged reviews; synthetic tests reproduce that behavior.

A shared walletHandoffPending guard now covers action entry, delayed preparation
JSON, and confirmation dispatch. It is acquired immediately before the exact
existing sendTransaction(d.request) call, with no async gap. The inner finally
releases only when the SDK call settles or throws synchronously. No timer, review
cancel/expiry or same-document navigation releases it. Blocked attempts explain
that the user must wait and not repeat the transfer. No attempt is queued/retried.
Fresh action after settlement still requires a new unchecked review. The existing
post-signature send-signed notification remains outside the SDK lock and cannot
hold or clear a newer handoff lock. No request payload, endpoint, signing authority
or server money behavior is added or broadened.

This guard is in memory, not durable or cross-tab. SDK promise rejection is not
proof that no chain operation exists; existing failure wording remains 'not
confirmed' and no automatic repeat is introduced. SDK resolution is not chain
settlement. Real wallet/platform behavior, reload/re-entry and ambiguous error
reconciliation remain unverified and explicitly outside this bounded fix.

Primary owns code, native Chrome harness and exact HTML publication. Independent
/root/handoff_acceptance owns deferred SDK tests; /root/handoff_diff_ops reviews
race/error semantics and temporary atomic apply/reconcile/rollback/failure tests.
Playwright uses the existing non-root/private-network supervisor with inert SDK
and API fixtures. No new dependency, plugin or external research is required for
this local Promise serialization change.

Surface matrix: Mini App REQUIRED; public site READ_ONLY for exact HTML delivery;
bot/payment READ_ONLY for preserved inventory and service checks; native/admin N/A
because no implementation or authority there changes. Accountable owner: project
owner under current manual reversible E4 continuation. No real wallet call,
authenticated customer request, provider transfer, key/credential or 064A authority.

Acceptance: cross-action unresolved SDK, repeated attempts, stale callbacks,
review cancel/expiry, delayed preparation response, resolve/reject/sync throw,
exact signing request, no notification after failed SDK, and post-signature
notification independent from lock lifetime. Baseline red/new green, prior
preparation/order review regressions, native DOM tests and two reviews required.

Rollout is HTML-only with exact 56-file inventory, unchanged service tuple and
public template preflight. Verified bytes/metadata backup precedes atomic replace.
No restart. On post-write verification failure, explicitly reconcile or rollback;
do not assume no replacement occurred. Rollback refuses unrelated live drift.

Exactly next: E4 / WALLET_HANDOFF_REENTRY_COVERAGE — assess reload/re-entry and
ambiguous SDK failure guidance using executable evidence; select the next product
fix only from a reproduced gap. The full E4/platform/human gate remains open.
