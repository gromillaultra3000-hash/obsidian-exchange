E4 / PAYMENT_STATUS_RUNTIME_READ_CONTRACT — independent security review, 2026-09-08 UTC.

No unresolved blocker remains in the reviewed candidate. The final JSON review binds the exact source and evidence. Product and deployment code were authored by other agents; this reviewer changed only security probes and review artifacts.

Resolved findings:

- High: restoring `api_order` provider polling could reactivate `_mark_order_paid` from a status GET. The repaired handler reads the canonical ledger; provider polling blocks were removed. The independent AST comparison confirms callbacks, background functions and payment transition helpers remain unchanged.
- High: provider requisites could terminate the JSON-containing script in `/pay`. The candidate escapes HTML metacharacters and JavaScript line separators before embedding JSON. An in-memory regression mutant reproduces two script tags; the corrected handler emits one and the provider payload remains data.
- High: the copy button interpolated provider-controlled detail text into an inline JavaScript string. The candidate places escaped text in a quoted `data-value` attribute and uses a fixed handler. Exact generated HTML/JavaScript preserves hostile quote-shaped detail text without adding attributes or executing code.
- Medium: stale, unknown or post-payment session states must not invite another transfer or claim that a partner closed a deal. Only `created`, `invoice_created` and `awaiting_payment` may offer current payment instructions; highest-ID selection prevents an older-session fallback. Unavailable requisites use support/no-repeat guidance. Stored receipts also hide unusable instructions; sent receipts retain precedence without asserting a staff assignment.
- Medium: missing receipt/session reads previously appeared as no receipt or an open session. Read failures now produce HTTP 503; authorization failure remains 404. Unexpected payment-page logging no longer interpolates the bearer token or arbitrary exception text.

Independent checks use a read-only synthetic SQLite ledger, isolated real handlers, a synthetic proof key, and the actual generated page script in a Node VM. They verify owner precedence over bearer authority, SQL binding, orphan denial, malformed/expired proof denial, canonical order status and no read-triggered provider transition. Disposable operations probes cover each of five partial-publication boundaries and a lost restart acknowledgement, followed by observation without replay and explicit exact rollback.

This is a bounded source and deployment review. It does not establish a real customer incident, production Telegram authentication, bank/provider completion, payout success, full application security or closure of E4. The browser and PostgreSQL evidence are separately authored and hash-checked. A normal Relay restart resumes its already configured workers; unchanged worker effects are not claimed to be zero.
