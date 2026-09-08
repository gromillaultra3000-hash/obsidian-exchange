# E4 payment page terminal reasons

The opaque payment page previously labelled `failed` and `cancelled` as expiry.
An old verification request could hide the terminal outcome; receipt metadata
also replaced the reason with a generic closed caption on opaque and numeric
pages. Exact synthetic handlers and browser fixtures establish the baseline;
no actual customer incident is inferred.

Each canonical terminal state now keeps its own caption: payment time expired,
exchange not completed, or order cancelled. Stored and delivered receipt facts
appear independently without asserting that payment was received, a payout is
promised, or a member of staff has already accepted the case. Closed orders show
no payment, copy or QR controls and direct the user to existing support with
explicit advice against another transfer.

Only `relay-fastapi/main.py` is published. Changes are limited to `pay`'s numeric
caption and embedded terminal renderer. Authentication, repository queries,
status API, serialization escaping, callbacks and background workers retain
their established behavior. Paid/sent precedence and the local timer's inability
to mutate canonical order status remain covered by focused tests.

The one-file rollout preserves 16 runtime dependencies and retains the exact
main preimage and metadata for explicit rollback. The existing API/database
contract is unchanged, so this presentation slice does not repeat PostgreSQL
container rehearsals or broaden deployment to shared repository drift.
Acceptance instead exercises exact generated pages over synthetic read-only
SQLite fixtures and sandboxed Chrome, alongside independent diff/security and
interrupted-rollout reviews. Runtime probes use no valid bearer, proof or
authenticated customer request. Ordinary Relay restart resumes existing workers;
their pre-existing database/notification effects are not claimed to be zero.

E4 remains open. Real Telegram/iOS/WebKit, assistive technology and human
comprehension are outside the acceptance demonstrated here.
