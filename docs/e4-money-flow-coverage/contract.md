# E4 / MONEY_FLOW_ACCEPTANCE_COVERAGE

The coverage assessment maps site, bot, Mini App and payment-page behavior to
the canonical E4 claims about executor, custody, KYC, fees, irreversibility and
protection against accidental actions. Existing tests do not prove every flow or
human/platform acceptance. The accompanying matrix records those distinctions.

The selected, reproduced defect is Mini App order-creation outcome certainty.
Both backend creation handlers can produce an order before the HTTP response is
received by the client. A rejected fetch, truncated JSON or gateway error cannot
prove that no order exists. The baseline sell UI claimed that no order was
created; buy failure handling could invite a repeat and render dynamic error HTML.

Only submitBuyOrder and submitSellOrder change. Known precreation HTTP errors
(400/403/429 with a string detail and no contradictory success/identity), or
successful HTTP responses with ok:false and the action's string reason and no
order identity, retain their rejection reason as literal text. Other HTTP errors
(including 408/409), transport/decode/server errors and malformed success envelopes
show an unknown-outcome message: check existing Activity/sell orders and support,
without repeating the order or payment. Literal error text wraps inside narrow screens. A positive safe integer order ID is
required before success UI/storage effects. Existing request URLs, methods,
payloads, acknowledgement callbacks and successful handoff behavior are retained.
No automatic reconciliation request, retry, wallet signature or new writer is added.

The primary owns Mini App code and executable response-loss tests. Acceptance
independently maps site/bot flows and builds browser checks. Security independently
reproduces fault cases and reviews the candidate and operational recipe. Operations
maps installed files and prepares exact HTML-only publication and rollback. The
existing isolated non-root browser launcher provides private-network verification.

The fault transports record an accepted synthetic request before losing its
response; they do not create a real order or demonstrate a customer incident.
Actual handlers are inspected/probed with inert boundaries. No production
customer data, provider request, signing, payment or database mutation is used.
The HTML file is read on each /webapp request, so publication needs no service
restart. Preserve the backend and drifting installed stores byte-exact.

Independent deferred-wallet probes also reproduced stale preparation reopening
a cancelled review and overlapping unresolved signature handoffs. Those findings
remain a separately bounded follow-up; this order-outcome change does not fix or
accept them. E4 and real Telegram/iOS/WebKit/assistive/human acceptance remain open.

Final browser review: the 320px malicious literal refusal exposed horizontal overflow; both submit result nodes now use overflow-wrap:anywhere. The initial success fixture lacked Telegram openLink and navigated away through the existing fallback; the harness now captures and asserts the external handoff without opening it. Failed run reports are retained under output/playwright/e4-money-flow-*; final evidence names only the exact successful candidate run.
