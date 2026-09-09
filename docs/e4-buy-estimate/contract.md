# E4 / BUY_REVIEW_RECEIVE_ESTIMATE_DISCLOSURE

2026-09-09. Accountable owner: project owner, manual canonical E4 continuation.
The accepted owner iPhone check remains closed; no report prerequisite.

The previous Buy modal displays only fee percentage and says the total is above,
while the approximate receive amount/rate sit in the background form. Show the
indicative calculation inside the review before consent. This is not a fixed
quote: the actual order calculation may differ, including server-side asset
overrides not exposed in the public standard-tariff response.

Use an independent snapshot of /api/rates, not copied DOM text or fallback tiers.
The API ts is response construction time; it is not the underlying market quote
time. Local receipt must be less than 60 seconds old and response ts less than
120 seconds old. These bound use of a response, not market-source freshness.
Reject future/backward-clock observations, missing/invalid numeric rates or
tariffs, unordered/unterminated tiers, nonfinite or rounded-zero receive amounts.
Use the existing half-open standard tariff calculation and display rounding.

Rate reads use no-store, an eight-second abort and latest-request-wins handling.
A latest failed response clears the estimate snapshot. Older success/failure
cannot overwrite a newer response. Existing background form calculation and
offering handling remain outside this slice. An open review captures its own
strings and deadline; refresh cannot silently change acknowledged values.

Valid-estimate consent expires at the earlier of the normal two-minute review
deadline and the captured snapshot deadline. Submission also rejects a wall-clock
rollback before receipt. On expiry reopen the review; no automatic submission.
When no valid estimate exists, disclose unavailability explicitly and retain the
existing ability to create an unpaid order; never invent a fee or a receive amount.
The API payload, address validation and subsequent payment flow are unchanged.

Required surfaces: Mini App /webapp Buy review. READ_ONLY: bot, site, public
device harness, API implementation and other application inputs. Admin/native N/A.
No new dependency, credential, real wallet connection, signing or money authority.
Primary owns product and legacy regression fixtures; independent acceptance agent
owns adversarial and browser tests; separate agent owns diff/ops review and
bounded rollout. Existing Playwright skill and isolated browser supervisor apply.

Acceptance: baseline missing-estimate reproduction; correct indicative amount,
rate and fee at 320/390 widths; explicit unavailable states; malformed-data,
race/failure/expiry/clock guards; immutable review snapshot; no POST on open/ack/
cancel; exact single synthetic order POST only on explicit valid confirmation.
Retain the default review behavior for Sell and wallet handoffs.

Rollout is HTML-only atomic replacement after tests, two independent reviews,
saved original bytes/metadata and temporary-file rollback rehearsal. Scope permits
only the rates/snapshot helper block, openExchangeReview and beginBuyOrder.
Pinned helper/wrapper/inventory/candidate, 55 unrelated inputs and four service
identities are checked before/after apply. No restart. Exact rollback and
reconciliation use the same saved plan. Existing pages obtain the change on reload.
Full E4 remains IN_PROGRESS; this closes only the in-modal indicative Buy estimate.
