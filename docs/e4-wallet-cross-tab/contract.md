# E4 / WALLET_HANDOFF_CROSS_TAB_COORDINATION

Coordinate upgraded Mini App pages in the same origin/browser storage partition.
Reproduce the current two-tab gap with inert SDK calls before accepting the fix.
An exclusive Web Lock with `ifAvailable` protects publication of a shared minimal
attempt record and remains held for the SDK promise. Contention rejects this
attempt; it never queues a future signature, retries, steals a lock or uses elapsed
time to release unresolved evidence. SDK settlement and page destruction release
the browser lock but do not establish the money outcome or delete the record.

The shared record retains only a version, a fresh random non-secret attempt ID,
public sender, network, operation and applicable order number. The attempt ID
distinguishes identical successive attempts so acknowledgement of old evidence
cannot delete new evidence. No destination, amount, memo, payload, signature,
Telegram identity, private key or secret. No dependency or backend writer added.

Retention changes from tab lifetime to local browser storage until explicit user
reconciliation/removal or browser data clearing. No timer expiry, server backup or
telemetry export. The user sees this scope and can remove reconciled evidence;
neither removal nor user assertion changes payment status. Existing session-only
unresolved evidence must not be silently discarded or overwritten during upgrade.

Read, write, readback and removal errors, malformed evidence or missing Web Locks
stop signing. Storage events are UI hints; the authoritative reread occurs within
the exclusive lock. Removal uses the same lock, exact observed evidence and a fresh
explicit acknowledgement; another page's pending SDK must exclude removal.
Lock acquisition is asynchronous even with ifAvailable: recheck the consumed
review generation, deadline and current wallet/network inside the callback before
publication/signing. Unrelated order-creation callbacks retain their existing
confirmation semantics.

References verified 2026-09-08: [W3C Web Locks](https://www.w3.org/TR/web-locks/)
defines asynchronous ifAvailable and lock lifetime through callback settlement.
This lock is browser coordination, not blockchain finality or global idempotency.

Capability split: implementation agent owns product and regressions; acceptance
agent owns independent native two-page/browser tests with real browser locks and
storage but inert SDK/API; diff/ops agent owns scope review, isolated reversible
publication tests and read-only preflight; primary owns contract, full regression,
secret scan, bounded publication and runtime evidence. Existing Playwright skill
and non-root sandbox/private-network supervisor; no installed external plugin.

Surface matrix: Mini App REQUIRED; public HTML delivery and bot/runtime READ_ONLY;
admin/native N/A. Accountable owner: project owner, authorized manual reversible
E4 continuation. Autopilot remains failed/MainPID0. No actual money, signing,
provider operation, authenticated customer read, new credentials or 064A authority.

Publish only reviewed HTML with exact dependency/process/public-template preflight
and rollback preimage, preserving other 55 inputs with no service restart. Old
already-open pages, different browser profiles/devices and cleared storage cannot
participate in this guarantee. Reload older pages before relying on coordination.
Rollback restores previous HTML for later loads; it cannot cancel requests, alter
already-open JavaScript or reconcile wallet outcomes. Shared evidence may survive
rollback while older code does not understand it; keep this limitation explicit.
Real Telegram/WebKit/iOS, assistive technology and human/chain acceptance remain
open, along with the full E4 and earlier gates.
