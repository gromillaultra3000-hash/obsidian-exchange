# ObsidianExchange security and reproducibility report

Updated: 2026-08-08 UTC

## Executive summary

The production signing boundary and Filament authorization are materially
hardened. Git history contains no gitleaks findings, but local ignored `.env`
copies still contain credentials that must be invalidated at their providers.
Admin/payment source was previously absent from Git; it is now staged with a
redacted secret scan and new CI security gates. PostgreSQL cutover is not yet
safe because business flows still assume SQLite and referral withdrawals do
not yet have a durable intent/reconciliation contract.

## Critical / high priority

### SEC-001 — Exposed external credentials require provider-side rotation

- Severity: High
- Location: ignored `bot/.env*`, legacy `bot/gold_v*/.env`, and external
  provider credentials represented in `/etc/obsidian-exchange/app.env`.
- Evidence: redacted gitleaks source scan found 66 matches; Git-history scan of
  266 commits found zero. No secret values are retained in this report.
- Impact: anyone who previously obtained a copied token may continue using it
  until the provider invalidates it.
- Fix: reissue Telegram/provider credentials, update only root-owned `0600`
  env files, restart one consumer at a time, and delete obsolete local copies.
- Mitigation: active runtime env files are already root-owned `0600`; callback
  handler is disabled and now has no inline token.

### SEC-002 — Referral withdrawals lack durable payout intents

- Severity: High
- Location: `bot/main_bot.py`, `withdraw_referral_bonus`.
- Evidence: the function only alerts administrators and leaves the balance
  unchanged; it cannot provide atomic reservation, signing idempotency,
  reconciliation, or customer outbox delivery.
- Impact: manual handling can lose, duplicate, or ambiguously settle a debt.
- Fix: introduce a typed payout subject contract and referral-specific atomic
  reservation/reconciliation ledger before enabling automated signing.
- Mitigation: the current path is fail-closed/manual and does not sign or zero
  balances.

## Medium priority

### SEC-003 — Python dependencies are only range-constrained

- Severity: Medium
- Location: `relay/core/requirements.txt`, `relay/wallet/requirements.txt`,
  `tests/requirements.txt`.
- Evidence: direct dependencies use ranges and there is no complete transitive
  runtime lock.
- Impact: fresh CI/deploy environments can resolve different packages.
- Fix: generate reviewed hash-pinned lockfiles for runtime and CI, then install
  from those locks in deployment.
- Current mitigation: pip-audit reports zero advisories for all three current
  manifests; security tools are pinned in CI.

### SEC-004 — Existing SAST debt needs incremental remediation

- Severity: Medium
- Location: active Python source baseline in
  `security/bandit-baseline.json`.
- Evidence: 21 Medium and 145 Low Bandit findings; zero High. Reviewed B608
  Medium-confidence locations construct placeholder counts or constant SQL
  fragments while binding values separately.
- Impact: a large baseline can hide future risk if it is never reduced.
- Fix: review and remove baseline findings module by module.
- Mitigation: CI now fails on any new Medium/High finding.

### SEC-005 — PostgreSQL cutover lacks a proven compatibility gate

- Severity: Medium
- Location: direct `sqlite3` access across bot, relay, worker, and Laravel
  exchange connection.
- Evidence: SQLite-specific PRAGMAs, `INSERT OR IGNORE`, triggers, datetime
  expressions, and multiple independent writers remain.
- Impact: direct production migration risks state divergence or double payout.
- Fix: introduce repository interfaces, dual-engine contract tests, rehearsal
  migration with row/hash reconciliation, write freeze, and tested rollback.
- Mitigation: production remains on the canonical SQLite database; no cutover
  has been attempted.

## Verification completed

- Gitleaks 8.30.0: 266 Git commits, zero findings; staged scope, zero findings.
- pip-audit: zero known advisories in all three Python manifests.
- Composer audit and npm audit: zero known advisories.
- Bandit baseline gate: no new Medium/High findings.
- Production bot has zero-length `PAYOUT_SEED` and
  `WALLET_PAYOUT_PASSWORD`; callback handler is disabled/inactive.
- Production SQLite `quick_check` is `ok`; payout intent queue is empty.
