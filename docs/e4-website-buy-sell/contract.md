# E4 / WEBSITE_BUY_SELL_ACTION_REVIEW

2026-09-09. Accountable implementation owner: primary Codex, under the owner's
code-first reversible delivery instruction. Full E4 remains IN_PROGRESS.

Both existing website order forms receive a deliberate review before their
existing POST. The review names ObsidianExchange/private lane, recipient or
deposit custody, external bank/CEX identity requirements, indicative existing
fees and amounts, and irreversible transfer risk. It captures exact submitted
recipient/tag or payout details, requires a separate acknowledgement, invalidates
changed inputs, and supports keyboard cancellation and focus restoration.

SELL creates deposit instructions; its address and marker do not exist in the
pre-creation context. Show the server's selected asset label (including network
for multi-network assets) and require checking the issued network/address/marker
before the user's later manual transfer. Do not invent deposit instructions or
describe order creation as a completed payment. BUY's existing RUB-equivalent
estimate is not a locked crypto quote. This slice does not change server pricing,
validation, CSRF, POST fields, provider routing or money execution.

Surface matrix: website Buy/Sell REQUIRED; existing backend handlers, pricing,
asset/payout registries READ_ONLY; Mini App and bot READ_ONLY for regression;
admin/native N/A because no action on those surfaces changes here.

Capabilities: implementation agent owns templates and focused regressions;
independent acceptance agent owns synthetic rendered browser verification;
operations agent owns hash-bound reversible rollout and rehearsal. A separate
context-poor review will inspect the final diff and operations tooling. No new
packages, credentials, customer reads, provider requests or real transfers.

Rollout scope is two templates and one shared include. Preserve service identity
and unrelated deployed inputs, retain metadata and preimages, rehearse partial
apply and rollback, verify installed bytes and public unauthenticated routing.
Authenticated rendering is verified with synthetic fixtures under the installed
template engine; public redirects do not prove authenticated browser acceptance.

Legacy regression intake: the old sell-pricing source assertion expected the
Mini App's aggregate fee_label. The already deployed sellSnapshotInfo/sellCalc
uses the selected coin's validated fee_percent and shows it before amount input.
Update that stale assertion and retain the existing behavioral numeric/freshness
regression. Initial system and bot Python interpreters lack pytest; use the
existing /opt/lumi/venv interpreter for pytest and bot Python for standalone tests.

Exactly next after this package: E4 / WEBSITE_SWAP_ACTION_REVIEW, as identified
by docs/e4-completion-assessment-20260909.md. Bot reviews remain further work;
the owner's iPhone Mini App acceptance remains complete.
