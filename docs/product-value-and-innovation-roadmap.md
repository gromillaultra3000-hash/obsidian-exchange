# Product value and defensible innovation roadmap

Date: 2026-08-15

Status: acquisition-readiness baseline frozen; first privacy-safe traction evidence produced

## Objective

Maximize durable buyer value by converting the existing production exchange,
wallet ecosystem and fail-closed contracts into a transferable, measurable and
legally supportable business. Code volume and unsupported claims of uniqueness
do not count as value. Revenue quality, regulatory clarity, transferability,
security evidence, customer retention and defensible integration do.

Current private-software market references are useful only after metrics are
verified. SEG reported a 3.6x median public SaaS EV/TTM revenue multiple in Q1
2026, while 2025 fintech M&A summaries cited roughly 4.2x revenue and 12.1x
EBITDA averages. ObsidianExchange must not apply those multiples until revenue,
margin, growth, legal and concentration evidence is complete.

## Value gates

The machine-readable acquisition scorecard weights financial quality 25%, legal
and regulatory clarity 20%, traction 15%, technology/security 15%, operational
transferability 10%, IP defensibility 10% and transaction readiness 5%. Unknown
or blocked evidence contributes zero. A score and valuation may not be published
from narrative estimates.

Highest-value next work, in order:

1. Produce a privacy-safe 24-month KPI and cohort pack reconciled to ledgers.
2. Obtain jurisdiction-specific regulatory and provider-transfer opinions.
3. Close E0 inventory and create a clean reproducible buyer release.
4. Complete one real read-only CEX testnet connector and disconnect drill.
5. Prototype the Execution Trust Passport verifier over synthetic E2-E4 evidence.
6. Run buyer/customer interviews measuring audit, integration and custody-value.
7. Commission independent security and prior-art/FTO reviews.
8. Only then choose a narrow E3 canary and native-wallet device rehearsal.

## First acquisition evidence slice

`scripts/acquisition_kpi_report.py` produces a deterministic, aggregate-only
report from an immutable read-only SQLite connection. It suppresses monthly and
acquisition cohorts below 10 users, emits no customer identifiers, and binds the
result with SHA-256. The metric contract deliberately distinguishes fulfilled
GMV (`sent`) from revenue and treats `paid` as payment-confirmed but not yet
fulfilled.

The 2026-08-15 production snapshot covers 2026-05-10 through 2026-08-09 and
reports 854 orders, 76 fulfilled orders, RUB 1,835,803 fulfilled GMV, 40 users
with at least one fulfilled order, and 13 repeat fulfilled users (32.5% of
fulfilled users). These figures establish an auditable traction baseline only.
Revenue, gross margin, normalized EBITDA/SDE, CAC, LTV and contribution margin
remain unavailable, so the financial and traction scorecard gates remain
unverified and no valuation multiple may be applied.

Next financial evidence: define a normalized revenue and direct-cost ledger,
reconcile provider settlements and crypto execution costs to orders, then
generate monthly gross margin and contribution-margin cohorts without exposing
customer-level records.

## First moat candidate: Execution Trust Passport

The passport is a portable, privacy-minimized proof that one action retained the
same intent, lane, identity/custody explanation, quote, consented parameters,
hard-policy decision, provider attempt and reconciliation result. It cannot
authorize or retry an action. External evidence remains digest-referenced.

This packages existing strengths into a buyer-visible integration primitive:

- exchanges can demonstrate consent-to-settlement continuity;
- wallets can explain custody and executor changes;
- compliance and support can inspect one bounded evidence object;
- an acquirer can integrate verification without receiving secrets;
- advisory/AI output is provably unable to weaken deterministic policy.

The concept is only a differentiated candidate. “Unique”, “patentable” and
“freedom to operate” are prohibited claims until documented searches and legal
review are complete.

## Transaction discipline

No buyer data room receives secrets, private keys, cookies, customer identity
documents or raw provider credentials. Demos use synthetic/redacted evidence.
Every claimed KPI, security property and innovation has an owner, date, source
digest and independent verification status.
