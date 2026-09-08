# E4 payment status runtime read contract

The installed Relay called absent authorized order, session and receipt methods.
The public baseline returned HTTP500 for `/api/order/0` and `/pay/0`; disposable
exact-source tests also reproduced failures with synthetic authorized subjects.
No actual customer incident or payment outcome was observed.

`PaymentStatusReadStore` supplies bounded, parameterized SELECTs through the
installed order repository's connection policy. Verified user identity takes
precedence over a simultaneous bearer token. Opaque tokens authorize only their
own order; orphan sessions disclose no page. Numeric links require a bounded,
order/user/time-bound HMAC proof, supplied by the additive `core.order_access`
module. No production proof is issued during delivery.

Only the highest-id session can supply payment instructions, and only in
`created`, `invoice_created` or `awaiting_payment`. Stale links, closed/unknown
sessions and post-payment session states cannot invite another transfer. These
facts never promote the canonical order status to paid. Receipt state remains
independent, with HTTP503 on unavailable reads rather than fabricated absence.
Provider fields are escaped at the JSON/script boundary, and clipboard buttons
use data attributes instead of inserting values into executable JavaScript.

The status GET no longer contains Brabus/Vertu polling or payment transitions.
Restoring its former provider lookup would make a previously unreachable money
writer available as part of a page-read repair. Existing verified callbacks,
background workers and `_mark_order_paid` remain unchanged. The existing page
audit logging remains; the unexpected-error log no longer includes bearer data.
Routine Relay restart resumes its already-enabled background workers; delivery
does not claim that those pre-existing database or notification effects are zero.

Exactly four files are published: `relay-fastapi/main.py`, `relay/webapp.html`,
the additive read adapter, and `relay/core/order_access.py`. Shared live order,
session and receipt repositories remain byte-exact; unrelated checkout drift
is not deployed. The recipe binds the runtime's disabled authorized-read RPC
flag and refuses a changed connection-policy context.

Validation uses synthetic identities/data, read-only SQLite sessions with the
exact retained installed dependency, and real PostgreSQL17.11 in a disposable
networkless container. Public deployment probes use no authenticated subject,
valid bearer or customer order. Rehearsal/reviews must bind final source hashes;
deployment requires retained exact preimages and verified rollback behavior.
Real Telegram/iOS/WebKit, screen-reader behavior and human comprehension remain
outside the demonstrated acceptance evidence.
