# E4 / BUY_RECIPIENT_REFRESH_PRESERVATION

2026-09-09. Accountable owner: project owner; manual canonical E4 continuation.
The accepted owner iPhone check remains complete without a report requirement.

The automatic30s Buy rates update calls applyOfferings, which formerly reset the
network to its first option and restored a saved address over the typed recipient.
Keep background refresh separate from an explicit currency/network change.

Validate the complete offering structure before any offering/DOM mutation:
arrays, unique nonempty currency/network codes, string network labels and optional
string tag metadata. Build options using textContent. Valid empty offerings retire
all routes. Known currencies with no advertised networks are unavailable; never
interpret that state as permission to send an empty/default network. Independent
review found this default-network fallthrough and required its correction.

Same route and unchanged tag contract preserve currency, network, exact address,
memo and no-tag choice, including edits made while the response is in flight.
Reordering is not a route change. Only first hydration may choose the sole announced
network when none was previously selected; it never restores a cached address over
pending input. Multiple networks require a choice. Explicit currency/network edits
retain the current saved-address behavior, clear old memo/no-tag and tolerate
unavailable localStorage.

If currency/network disappears, leave an empty selection rather than substitute
another route. A material tag_name/tag_kind/tag_sep change requires currency
reselection. Clear previous recipient inputs after a known route is retired,
invalidate outstanding address-book responses and hide their chips. Initial
unresolved metadata may retain typed input but cannot reach a known invalid route.

A Buy review captures the route+tag signature and its unique callback. Offering
refresh invalidates only the matching active Buy review if that signature changes;
unrelated Sell/wallet reviews remain intact. Confirmation rechecks the captured
signature before the unchanged order submission. Same-route review values stay
frozen. Preserve existing estimate expiry, acknowledgement and payload semantics.

REQUIRED: Mini App Buy selectors, recipient form and review. READ_ONLY: site, bot,
public/device preview, backend/API and other application files. Admin/native N/A.
No new dependency, credential, customer read, real signature or money authority.
Primary owns product/legacy regression fixture; independent acceptance agent owns
adversarial/native browser checks; independent diff/ops agent owns bounded rollout.
Existing Playwright skill and isolated non-root browser supervisor apply.

Acceptance includes native baseline overwrite reproduction, unchanged/reordered/
in-flight updates, malformed inputs, disappeared/empty-network routes, changed tag
contract, initial hydration, explicit route reset, matching-review invalidation,
and exactly one intended synthetic POST only after explicit confirmation.

Rollout is atomic HTML-only replacement after tests, two independent reviews,
secret scan and temporary-file rollback rehearsal. Scope includes only the new
helper/marker block and applyOfferings/onCurrencyChange/updateAddressPlaceholder/
beginBuyOrder. Shared review, loadRates and submitBuyOrder are byte-identical.
Pin candidate/helper/wrapper/inventory; save original bytes/metadata, preserve55
other application inputs/four service states, verify public bytes and reconcile.
No restart. Existing pages receive the fix on reload; full E4 remains IN_PROGRESS.
