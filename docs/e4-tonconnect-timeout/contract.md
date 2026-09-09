# E4 / TONCONNECT_VERIFICATION_WAIT_RECOVERY

2026-09-09. Canonical E4 continuation;owner iPhone interface acceptance remains
complete without local report prerequisite. Full E4 remains IN_PROGRESS.

A stalled tcHandleWallet verification leaves tcPending true indefinitely and
prevents explicit new connection preparation. Limit the entire response and body
wait to8seconds using Promise.race and an abort signal. The timer rejects the race
even if fetch/body ignores abort. Mark timeout before abort so an AbortError race
still yields truthful timeout feedback. Reject elapsed>=8s or clock rollback
on completion too,so delayed/throttled timer dispatch cannot admit a late result.
The losing async operation may only return
data;it must never mutate recipient/UI or release pending ownership.

The awaiting handler applies the existing response-time recipient guard on timely
results,retains strict server-response checks,and clears deadline/tcPending once
in finally. A late loser cannot release a newer pending request or apply success/
error after retry. Timeout while original input is still current offers another
explicit connection or manual address entry;timeout/error after edits/disconnect
is silent. No automatic retry,nonce reuse or new proof authority. Existing intent
consumption and duplicate-event protection remain unchanged.

Browser timeout does not cancel or reverse server verification/profile association.
Backend verified response may remember a(user,chain) wallet link before its response
arrives. This slice changes only browser waiting and feedback;it makes no claim
that a timed-out wallet is unverified/unlinked or that server writes are ordered.
No real verification requests/customer reads/wallet signatures/money operations
are used in tests or deployment. Backend,SDK and submission/review read-only.

Primary owns product/legacy helper fixture support. Independent acceptance agent
owns real flow/browser and timer-race tests;independent ops agent owns reviewed
scope,preflight and rollback rehearsal. Required Mini App surface only.
Scope: tcHandleWallet verification-wait and error/finally handling;intent and
preparation logic and successful response application are preserved.

Acceptance: baseline indefinite pending,headers/body stall,noncooperative abort,
late success/error aftertimeout and during fresh retry,old loser not clearing
new pending,normal verification,existing recipient edits/disconnect,manual entry,
explicit fresh-nonce retry,clear deadline/no extra POST. Fake clock and mocked
SDK/network;isolated non-root browser checks at320/390.

Publish exact HTML after tests,two reviews,secret scan and local rollback rehearsal.
Backup exact preimage/metadata,protect58 live inputs/four services,verify public
bytes and reconcile without restart. Existing pages reload for the new deadline.
