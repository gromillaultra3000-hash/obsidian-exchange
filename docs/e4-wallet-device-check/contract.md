# E4 / WALLET_HANDOFF_DEVICE_ACCEPTANCE

Prepare an inert device-check page usable on the owner's real iPhone. Public
publication and synthetic browser checks do not constitute owner-device acceptance.
The real-device observation remains pending until supplied, and is explicitly
self-reported rather than cryptographically attested.

The generator extracts the production wallet-attempt/review logic from
relay/webapp.html and records its source/region hashes. Narrow declared transforms
change only storage/lock names to a disjoint test namespace and externalize inline
presentation styles for the existing preview CSP. Test-only controls provide a
synthetic account and inert pending/success/error SDK boundary. No real SDK,
Telegram initData, user identity, credentials, provider/API or money request exists.
No full production-app scripts or unrelated wallet/order flows are included.

The page guides a test review, acknowledgement, pending block, reload, simulated
settlement and explicit reconciliation. Shared browser primitives remain native.
A readable local report is available even if clipboard access fails. Its platform
label is user-selected; it must not infer verified iOS/Telegram acceptance from a
user-agent string. No report upload, analytics or fingerprinting. Test storage
and Web Lock names must never read, overwrite or clear production coordination.
Seeded production-key sentinels and lock assertions verify this independently.

Four deterministic static artifacts live under /preview/device-check/. A stricter
meta CSP disallows connections; the actual server CSP also applies (scripts and
styles from self, no inline execution). No inline style exceptions, eval or remote
script may be introduced to make tests pass. Externalized style mappings are
evidence of presentation transformations, not a byte-identical full app claim.

Actual Mini App entry uses the existing bot /preview WebAppInfo button, whose
installed handler targets /preview/. Add exactly one footer link to the preview
index so the owner can navigate within that surface. No bot code/deployment or
message sending by the agent. Opening a direct URL in Telegram's browser must not
be silently called Mini App acceptance. The owner reports the context used.

Publication clones the exact live static preview tree into a new release, adds
only the four device-check assets and applies only the reviewed footer link.
All other preview files, application inputs, Nginx configuration and service
identities remain unchanged. Atomic current-pointer swap follows preflight,
local rollback tests, two independent reviews and saved exact previous pointer.
Reconciliation after interruption precedes another action; rollback rejects drift.
No service restart or production application HTML change is required.

Capability split: implementation agent owns generator/assets/unit tests; primary
owns the footer link, contract and release execution; acceptance agent independently
checks native Chrome/WebKit, actual DOM and CSP, privacy boundaries and report;
ops agent reviews generation/isolation and authors/tests scoped static rollout.
The primary independently reviews that rollout code. Existing Playwright skill
and isolated supervisors bind exact test assets, runtime and output evidence.

Surface matrix: static device page REQUIRED; preview Mini App entry REQUIRED;
bot/application/API/runtime READ_ONLY; admin/native N/A. Accountable owner: project
owner under manual E4 continuation. Autopilot remains failed/MainPID0. No actual
signature, money/customer operation, new credential or 064A authority. Full E4,
actual wallet reconnect/signature and human/device gates remain open.
