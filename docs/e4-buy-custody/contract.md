# E4 / BUY_RECIPIENT_CUSTODY_DISCLOSURE

2026-09-09. Accountable owner: project owner; current manual E4 continuation.
Owner iPhone Telegram acceptance is complete and requires no additional report.

The first confirmed gap in the remaining preconfirmation UX is the Mini App
Buy review's unconditional claim that the destination keys are controlled by the
user. A valid pasted destination can belong to a custodial exchange or service.
The review must describe both destinations truthfully before acknowledgement.
The shared checkbox already mentions possible irreversibility; the Buy-specific
risk now explicitly explains that a blockchain payout cannot be cancelled after
sending and asks the user to check address, network and tag/memo.

Change exactly two static rows in beginBuyOrder: the custody label/value and
the Buy risk string. No classification or ownership inference from an address.
Private-lane executor/identity, fee copy, payload, validation, acknowledgement,
expiry, cancellation and order submission remain byte-identical. External-service
custody and KYC are separate from ObsidianExchange's private lane.

Acceptance: rendered own-wallet and service-custody explanation before consent;
explicit irreversible payout text; readable at 320/390/1280 widths; no write on
open, acknowledgement or cancel; only explicit confirmation invokes the existing
synthetic order contract once. Baseline must demonstrate the false old claim.
Existing recipient/review/outcome tests protect the surrounding behavior.

Surface matrix: canonical Mini App /webapp REQUIRED; site, bot, public preview
and APIs READ_ONLY (this finding is in the Mini App Buy dialog); admin/native N/A.
No new dependency, key, credential, customer read, money or signing authority.
Available capabilities: primary implementation/verification; independent acceptance
agent with isolated Playwright; independent diff/operations agent. No external
research needed for repository-local static wording and existing browser tooling.

Rollout: exact two-replacement scope, pinned candidate, read-only runtime preflight,
saved original HTML/metadata, atomic HTML-only replacement, public exact-byte check
and reconciliation; no service restart. Rollback restores the saved original file
under the same checks. Existing open pages show the new copy after reload.
Full E4 remains IN_PROGRESS; this slice closes only this reproduced disclosure gap.
