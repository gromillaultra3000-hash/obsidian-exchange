# E4 / TONCONNECT_PREPARATION_ROUTE_BINDING

2026-09-09. Canonical E4 continuation. Owner iPhone interface acceptance remains
complete without a local report. Full E4 remains IN_PROGRESS.

A deferred tcConnect payload response currently opens the TON modal after the
user selects BTC or changes recipient. Serialize preparation with an owned token;
reject duplicate preparation and starting during verification. Bind to valid TON
recipient route,exact address/memo/no-tag and existing edit/status generation.
Recheck SDK availability and captured intent after initialization, awaited JSON,
and awaited disconnect, before installing ready parameters or opening the modal.
Recheck after awaited modal opening and close this owned modal/clear parameters
if intent changed during that wait.
Reject non-success HTTP, non-string/empty/oversized payloads. Abort payload GET
at8seconds and reject a late response after the abort even if it resolves anyway.
Manual recipient editing remains available. Errors from retired preparation must
not overwrite current feedback. Clear failed/obsolete request parameters and
restore the button only for the owned token; retain ready proof after successful
modal handoff so the user can actually connect.

Existing SDK null callback invalidates recipient generation. An expected null
from our own awaited disconnect may advance this preparation snapshot ONLY when
the snapshot was still current immediately before the callback. User edits,
including away/back, cannot be rebound. Non-null replacement SDK status retires
the preparation. Disconnect failure or a still-connected SDK cannot open modal.
A non-null callback from an already obsolete preparation must not start proof
verification: SDK openModal can await discovery and auto-connect an embedded
wallet before returning. The existing response-verification guard remains in force.

Primary owns product and legacy fixture adaptation. Independent acceptance agent
owns real-helper and isolated native Chrome tests; independent ops agent reviews
scope and authors pinned rollout/rollback. Required Mini App surface only. Backend,
SDK bundle, buy submission/review,Sell and other surfaces are read-only. No real
wallet signing/connection, customer reads or money writes in tests/deployment.

Scope: tcPreparation marker, narrow tcHandleWallet preamble and tcConnect.
Test baseline late-modal failure and current success,unchanged refresh,edits and
route away/back,payload body delay,own disconnect,edits during disconnect,
SDK replacement,duplicate calls,malformedHTTP/payload,timeout/late resolution,
cleanup and retry. Reuse existing sandboxed non-root browser launcher.

After tests,two reviews,secret scan and local rollback rehearsal,atomically
replace only HTML,retain exact preimage/metadata and verify public bytes,56 other
live inputs and four service identities. No restart; reconcile same iteration.
Existing pages get the new guard on reload. This bounded slice guards preparation
before modal handoff; it does not claim to cancel an already open SDK modal or
bound SDK disconnect/verification response waits.
