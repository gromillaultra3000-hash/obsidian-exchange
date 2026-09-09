# E4 / SELL_REVIEW_ESTIMATE_FRESHNESS

2026-09-09. Accountable owner: project owner; current manual E4 continuation.
The existing owner iPhone acceptance remains closed; no device-report requirement.

The previous Sell form and review reused cached payout numbers indefinitely.
Independent baseline reproduction retains the same 45,500 RUB value after24h.
Bound the local receipt age of the public options response to60s. This endpoint
has no source timestamp; no market-source freshness or binding quote is claimed.

Use the server's net rate directly (amount * rate); never deduct its fee twice.
Show the selected coin's fee_percent, not the generic cross-coin fee_label.
Reject invalid numeric rate/fee, nonfinite, overflow and rounded-zero payouts.
Market breakdown is optional: server market=0 is legitimate unavailability.
Remove stale numeric payout, breakdown and tariff from the form; selectors show
labels only, so they cannot retain obsolete rate strings. Label the result as an
estimate, explain that the order may differ, and provide an explicit refresh.

Entering Sell refreshes with no-store and8s timeout. Latest request wins; old
success/failure cannot overwrite it. Latest failure clears the snapshot and keeps
the existing disabled-submit behavior. Expiry timer, visibility and every render
recheck age. Refresh captures selectors at response time, preserving coin, method,
bank, phone, name and amount. Removed choices become empty and require reselection;
the existing default selection applies only on the first successful load.

Review snapshots are immutable while open. Valid snapshot bounds the existing
consent deadline; callback rejects expiry and clock rollback. An expired estimate
may still open an explicitly unavailable review to create an unpaid order, with
the existing server validation and payload. No automatic confirmation/retry.

Independent review identified a refresh/pending-submit race: successful refresh
could re-enable submission while the first order was pending. A per-page pending
flag now guards both review opening and confirmation for the complete awaited
submission; option refresh respects it. This is not a cross-device idempotency
claim and does not change server execution. Preserve the existing submit function.

REQUIRED: Mini App Sell form and review. READ_ONLY: site, bot, public preview,
API/server code, other application files. Admin/native N/A. No new dependencies,
customer reads, secrets, wallet signing, money or064A authority. Primary implements
and verifies existing tests; independent acceptance agent owns adversarial/browser
tests; separate diff/ops reviewer owns scoped rollout and local rollback rehearsal.
Existing Playwright skill and isolated non-root browser supervisor apply.

Acceptance includes baseline stale-number failure, fresh/unavailable states,
malformed/expired data, response races, selection preservation/removal, immutable
review/deadline, explicit single mocked submission and pending-submit+refresh
exclusion. Existing Buy, wallet and recipient behavior must remain intact.

HTML-only rollout after proportional tests, two independent reviews, secret scan,
exact-byte scope check and pinned candidate/helper/wrapper/inventory. Save original
bytes/metadata before atomic replacement, preserve55 other inputs/four services,
verify public exact bytes and reconcile; no restart. Rehearse exact rollback on
temporary files. Existing pages receive new code on reload. Full E4 remains open.
