# E0 gate audit

Observed: 2026-08-15 UTC. Scope: read-only repository and runtime inventory.
No service was restarted, no credential value was read and no production state
was changed. E0 status is machine-readable in
`docs/e0-gate-status.v1.json`; this scoped artifact does not assert E1–E5 status.

## Result

E0 is `IN_PROGRESS`. Its first ordered unmet criterion is now `E0.3`. On
2026-08-15 the owner explicitly removed Aurevia from the ecosystem scope, so
the former E0.1 owner blocker is superseded rather than treated as implemented.

## E0.1

`SUPERSEDED`. Repository search found no Aurevia code, service, data owner or
API. The owner explicitly removed it from product scope on 2026-08-15; the
canonical roadmap and execution charter no longer assign it a role.

## E0.2

`VERIFIED`. `docs/ecosystem-contracts.v1.json` is the authoritative current
machine-readable inventory and `docs/ecosystem-contracts.md` its concise view.
They replace the contradictory append-only snapshot and explicitly model
implemented and dormant Wallet, Exchange, KAIROS, LUMI, provider, operator and
signer boundaries. Logical roles are separated from effective/reachable money
capability; the current advisory-only LUMI failure behavior and the linked-web
disconnect CSRF gap are stated rather than hidden. Semantic/source-anchor and
stale-claim regressions are in `tests/test_ecosystem_contract_inventory.py`.

## E0.3

`IN_PROGRESS`. `docs/operational-ownership.v1.json` now inventories twelve data
stores, secret-reference groups and eight effectful writer classes without
reading secret values or customer rows. It records lifecycle UNKNOWN/PARTIAL,
shared full-schema DML, root principals and dormant capabilities. The project
owner accepted all accountable role scopes on 2026-08-15 and remains their sole
accountable principal until written delegation. `docs/secret-reference-members.v1.json`
adds variable-name-only bundle membership, forbidden/dormant refs and exact
service-to-DB-role bindings. The read-only privilege verifier reports the
declared PostgreSQL matrix as a match, while broad shared `obsidian_app` remains
a control gap. Rotation/revocation/expiry and external-store coverage remain
incomplete. Relay is `relay-svc`, payout worker is `obsidian-payout`,
and KAIROS/LUMI have dedicated users; bot, support and admin remain root.

## E0.4

`IN_PROGRESS`. Core buy/sell functions exist across bot, site and Mini App, but
the three-custody portfolio, CEX lifecycle and market-mode UI are evidenced only
in Mini App tests. Bot and site may legitimately be `READ_ONLY` or `N/A`, but no
approved applicability matrix records that decision. Admin and legacy operator
surfaces overlap and also lack a single current owner/status inventory. Native
is an honest Signet/offline Rust scaffold, not a shipped mobile surface.

## E0.5

`VERIFIED` for the canonical E0 requirement to define SLOs, metrics and
runbooks. `docs/cex-readonly-operations.md` freezes privacy-safe SLOs, metric
names, alert thresholds and five incident runbooks. Runtime dashboards/alerts
and credential-free operational rehearsal remain explicit later pre-credential
readiness work; they are not silently added to the E0 acceptance criterion.

## Runtime observation

At `2026-08-15T07:27:30Z`, the observed core units `relay-fastapi`, `exchange-bot`, `support-bot`,
`admin-panel`, `obsidian-payout-worker`, `kairos` and `lumi` were active.
`systemctl show` configured Relay, admin, KAIROS and LUMI to bind loopback;
`ss -lntp` confirmed those sockets and nginx on public HTTP/S ports. This
observation is point-in-time evidence, not a perpetual status.

## Next canonical slice

E0.3 remains active. All 43 Relay read and all 26 writer bodies are rehearsed
proposal-only in disposable PostgreSQL 17. R5/R6 add transition CAS,
idempotency and atomic settlement rollback evidence. This completes only the
69-body Relay SQL subplan. The next bounded slice is the exact exchange-bot
caller-to-repository/database capability graph; shared roles/bundles and root
money-capable services also remain. No production rollout is authorized.
