# E4 / TONCONNECT_SDK_HANDOFF_WAIT_RECOVERY

2026-09-09. Accountable implementation owner: primary Codex agent; acceptance
and diff/operations reviewed independently. Full E4 remains IN_PROGRESS.

Bound disconnect, modal opening and obsolete-modal closure waits to eight seconds
per operation. Race SDK completion against a deadline; reject elapsed >=8s and
clock rollback even when timer dispatch is delayed. Release owned preparation
and its disabled button through one finally path. No automatic retry.

SDK singleton operations cannot be cancelled or reliably attributed after timeout.
Quarantine this page through the existing SDK-unavailable flag, retire the connection
intent and recipient generation, and ignore subsequent SDK callbacks. Timely errors
retain explicit retry. An uncertain timeout requires an explicit page reload for
another SDK attempt; manual recipient entry remains usable. The message states this
recovery path. This deliberately narrows the prior proposed same-page retry to avoid
late disconnect/open effects interfering with a new attempt. A late SDK modal may
still physically appear; it has no authority to apply a recipient. Reload is not
represented as server cancellation or reversal of an existing wallet association.

Surface matrix: Mini App TON recipient helper REQUIRED; backend verification and
SDK bundle READ_ONLY; bot entry READ_ONLY; admin, native wallet and other monetary
executors N/A to this browser wait correction. No money, credentials, signatures,
customer reads, server association semantics or order submission changes.

Acceptance covers indefinite waits, late resolve/reject, null/proof events after
expiry, clock delivery delay, manual edits, fresh successful connection and timely
failure retry. Native browser fixture intercepts requests and uses inert SDK.
Rollout: exact HTML-only replacement after two reviews, tests, secret scan and
atomic apply/reconcile/rollback rehearsal. Preserve live input hashes and four
service identities. Rollback uses retained exact preimage/metadata and pinned plan.
Existing pages must reload to receive this code.
