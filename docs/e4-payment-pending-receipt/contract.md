# E4 / PAYMENT_STATUS_PENDING_RECEIPT_EVIDENCE_CONSISTENCY

Pending orders with unavailable payment instructions must acknowledge a stored
receipt file on both numeric and opaque payment pages. Storage does not prove
delivery to the payment partner or payment confirmation. Existing video/PDF
verification prompts remain visible; the file fact accompanies the prompt.
Delivered receipts remain distinct from stored files. Absent or unknown receipt
states never create a received-file claim, including after local timer expiry.

The change is limited to presentation inside `pay`. It preserves the canonical
order state, terminal and paid/sent precedence, authorization, read queries,
redirects, JSON escaping and polling. Unavailable instructions expose no payment,
copy or QR controls. The new copy adds no promised review assignment or deadline.

Validation: 141 focused pytest checks, 49 exact handler/SQLite checks, 142 isolated
Chrome checks, 122 independent security cases and 17 ops tests. Acceptance and
security also independently probe interruption/reconcile/rollback behavior. The
browser uses synthetic fixtures, a sandboxed non-root process and private network;
its process/cgroup cleanup is verified. No PostgreSQL rehearsal is repeated for
this presentation-only change, and no whole-project test result is inferred.

Deployment publishes only `relay-fastapi/main.py`, preserving 16 installed
dependencies and exact rollback bytes/metadata. Only Relay restarts. Runtime
checks use public unauthenticated routes. No real customer read, payment outcome,
new money operation or 064A authority is part of this change. Existing Relay
workers resume on restart; their pre-existing effects are not claimed to be zero.
The owner's autonomous runner remains stopped.

Separate next evidence: the retained serializer emits aware ISO timestamps with
`+00:00`; the current timer appends `Z`, producing `NaN:NaN` in actual Chrome.
That defect is recorded for the next bounded E4 item, without expanding this one.
