# E4 / WALLET_HANDOFF_WEBKIT_ACCEPTANCE

Run the deployed wallet handoff state machine in native Linux Playwright WebKit,
with real Web Locks, local/session storage and two same-origin browser pages.
Wallet SDK and API requests remain inert fixtures. Preserve all cross-tab cases:
concurrent acknowledgement, lock contention without queued signing, holder exit,
SDK outcomes, explicit reconciliation, unique-record stale acknowledgement,
legacy evidence, capability/storage failure and delayed review invalidation.
Inspect actual review and pending controls at 320/390 pixels.

The deliverable is project browser-test code, a reusable isolated WebKit launcher,
locked runtime provenance and executable acceptance evidence. Modify and redeploy
product HTML only if this browser run reproduces a product defect. Passing browser
tests do not justify an empty product deployment or a claim of real money success.

Runtime: installed playwright-core 1.62.0 with existing lockfile integrity;
official Playwright WebKit revision 2336 (26.5), Ubuntu 24.04. Browser and required
Ubuntu libraries are staged under /tmp/e4-webkit-runtime. Packages are downloaded
and extracted, not installed into the host. Any staged wrapper modification is
limited to preserving the supervisor's explicit dependency search path, with
before/after hashes; original downloaded browser cache remains unchanged.

The transient service runs as nobody, without host networking or access to /root,
with NoNewPrivileges and read-only runtime/library binds. Source, runner, package
and runtime content hashes bind evidence. Stop/MainPID/cgroup checks precede
cleanup. Engine-native sandbox is NOT_ATTESTED; do not reuse the Chrome sandbox
claim. Content digests are not a complete file ownership/mode attestation.

Capability split: primary owns intake, upstream download/references, dependency
audit and independent launcher review; implementation agent prepares isolated
Ubuntu libraries/provenance; acceptance agent independently exercises WebKit and
reviews UI/runtime behavior; ops agent authors/tests the launcher and reviews
runtime provenance. No unrelated plugin or product capability is introduced.

References checked 2026-09-08:
[Playwright browsers](https://playwright.dev/docs/browsers) and
[Playwright Linux WebKit guidance](https://playwright.dev/python/docs/browsers).
Playwright WebKit on Linux is not Safari on a real iPhone or Telegram's iOS webview.
Browser acceptance remains limited to the recorded runtime and inert boundaries.

Surface matrix: Mini App REQUIRED in isolated browser; production HTML/runtime
READ_ONLY; bot/admin/native N/A. Accountable owner: project owner under authorized
manual E4 continuation. No actual signature, trade, transfer, authenticated
customer read, production credentials or consumed 064A authority. Autopilot stays
failed/MainPID0. Earlier/full E4 gates remain open.

Rollback/removal: stop and verify the disposable service before deleting staged
test artifacts. No application rollback is required when product bytes stay
unchanged. Retain executable tests, provenance and result receipts in Git; keep
the runtime outside production applications. Real iOS/Telegram and human
acceptance require independent evidence and cannot be inferred from this run.
