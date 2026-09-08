# E4 / WALLET_HANDOFF_REENTRY_STATE

Preserve an unresolved TON wallet handoff across reload of the same browser tab.
Before entering the SDK, persist and read back a single versioned sessionStorage
record. Retain only the public sender, TON network, operation kind and, for a sell
payment, order number. Do not persist the destination, amount, memo, transaction
payload, signature, Telegram identity, keys or secrets. No external dependency.

The record blocks both wallet action paths, including after an account switch.
SDK resolution/rejection, elapsed time and page reload do not establish a chain
outcome and do not clear it. An explicit unchecked acknowledgement states that
the user checked the indicated wallet history and applicable order status and
established the outcome. Removal deletes only local evidence, never signs, retries
or updates payment status. It is unavailable while the current SDK call is pending.
Storage failures and malformed records block signing. Unexpected removal from
storage does not discard an already loaded record in the current document.

Retention is the browser's tab session, subject to browser session restoration,
until explicit removal. No timer expiry or backend copy. Public sender and order
number are locally sensitive metadata: deletion is explicit, no telemetry export
or backup is introduced. Closing/clearing the tab or using another tab/device is
outside this guard's guarantee. This is a user reconciliation checkpoint, not
automatic verification of a blockchain outcome or global idempotency.

Sender binding must accommodate the actual server contract: tonconnect.verify_proof
stores a friendly address; SDK account.address is raw. Normalize and checksum-check
the public sender, compare account/network before review and again before SDK entry.
The SDK transaction payload remains unchanged. Reference checked 2026-09-08:
[official TON address formats](https://docs.ton.org/foundations/addresses/formats).

Capability split: primary verifies backend compatibility, full regression suite,
secret scan, publication and runtime; implementation agent writes product/unit
tests; acceptance agent independently exercises page reload and controls through
the existing non-root, private-network, sandboxed Chrome supervisor; diff/ops agent
reviews storage/scope and rehearses atomic apply/reconcile/rollback failure paths.
No real wallet, signature, transfer, provider request or authenticated customer
read is used. Autopilot remains failed/MainPID 0 and is not restarted.

Surface matrix: Mini App REQUIRED; public HTML delivery READ_ONLY; bot and existing
payment runtime READ_ONLY; admin/native N/A. Accountable owner: project owner under
manual reversible E4 continuation. Earlier roadmap gates and real Telegram,
iOS/WebKit, assistive technology and human acceptance remain open.

Publish only webapp.html after two independent reviews, proportional tests and an
exact live-input/process/public-template preflight. Preserve rollback preimage and
all other 55 inventoried inputs; no service restart. Rollback restores prior HTML,
not a wallet outcome: it does not cancel a request, clear session evidence, or
replace JavaScript in already open documents. A rollback loses the new guard on
subsequent loads; prior no-repeat/unknown-outcome guidance remains available.
