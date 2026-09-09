# E4 / TONCONNECT_PAYLOAD_WAIT_RECOVERY

2026-09-09. Continue canonical E4; owner asks to finish E4 in one run if its
remaining scope is small. Independent full-criterion assessment runs alongside
this code fix; only evidence can mark the full gate verified.

The existing payload AbortSignal does not bound an uncooperative fetch or JSON
body. Race the complete response/body operation against8seconds. Mark expiration
before abort, check completion wall clock for >=8seconds or rollback, and retain
current recipient/preparation ownership checks. The losing promise only returns
data; it cannot configure the SDK, apply UI, clear a newer timer, or release a
newer preparation. One outer finally releases the owned preparation/button.

A payload timeout allows a fresh explicit request or manual input, with truthful
feedback only while the original recipient is current. No automatic retry. Payload
timeout occurs before SDK handoff and does not quarantine the SDK; existing
uncancellable SDK timeout quarantine/reload recovery remains unchanged.

Surface matrix: Mini App recipient helper REQUIRED; backend payload/verification,
SDK, bot entry READ_ONLY; site/admin/native wallet N/A for this wait correction.
Full E4 assessment separately checks remaining mandatory product surfaces.
No signatures, money operations, credentials, real customer reads or profile
association changes. Accountable implementation owner: primary Codex; independent
acceptance/browser and diff/ops agents review actual candidate digest.

Verification: stalled headers/body ignoring abort, late response during fresh
retry, route edits, wall-clock deadline, normal fresh handoff, inherited TON and
recipient regressions. Native Chrome fixtures intercept all network; no real
wallet. Production rollout is one exact HTML replacement with pinned inputs,
backup preimage/metadata,18 local rollback/scope/drift checks and public/runtime
reconciliation without service restart. Existing pages reload for the patch.
