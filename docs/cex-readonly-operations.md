# Read-only CEX: SLO, metrics and incident runbooks

Frozen: 2026-08-11. This contract applies to future authenticated CEX
connectors used by KAIROS and rendered through the Wallet. It does not authorize
credential ingress, a production key, trading, withdrawal or transfer.

## Safety invariants

- Accepted permissions are exactly `read=true`, `trade=false`,
  `withdraw=false`, `internal_transfer=false`. Unknown, missing, stale or
  contradictory permission evidence is `BLOCKED`.
- A balance request is never permission proof. Permission evidence is checked
  before every refresh and at least once every 15 minutes while a connector is
  eligible.
- The last valid snapshot is immutable on provider error. It becomes `STALE` or
  `UNAVAILABLE`; an error must never be rendered as a zero balance.
- Revocation stops new refreshes before vault deletion. Failed or ambiguous
  deletion remains terminally blocked for operator review and is never retried
  as a new connector.
- Metrics, alerts and events contain provider class and bounded error codes,
  never API keys, secrets, vault references, account identifiers, source IDs,
  balances or raw provider bodies.

## Service levels

These are initial operating objectives for the first bounded connector. They
are measured per provider over rolling UTC windows; planned maintenance is
reported separately and never converts stale data to healthy data.

| Signal | Objective | Hard safety response |
|---|---|---|
| Permission proof freshness | 100% of eligible refreshes use evidence age `<=15m` | Stop refresh; state `BLOCKED` |
| Balance freshness | 99% of successful snapshots are displayed with age `<=5m` over 24h | At `>5m` mark `STALE`; at `>15m` mark lane `UNAVAILABLE` |
| Refresh success | `>=99%` over 24h and `>=95%` over 15m | Open provider incident on fast-window breach |
| Refresh latency | p95 `<=2s`, p99 `<=5s` over 15m | Timeout is a failed refresh; retain last snapshot |
| Permission drift detection | next scheduled proof, no later than 15m | Immediately `BLOCKED`; page operator |
| Cross-owner disclosure | exactly 0 | Disable connector surface; security incident |
| Forbidden capability observed | exactly 0 | Revoke access path; security incident |
| Disconnect completion | 99% `<=60s`; 100% stop refresh immediately | `REVOKING` until deletion is proven; otherwise `BLOCKED` |

The availability SLO is subordinate to the safety invariants: degraded or
unavailable data is acceptable; silently broad permissions or fabricated zero
balances are not.

## Bounded metrics

Required counters and histograms:

- `cex_permission_checks_total{provider,outcome}` where outcome is one of
  `verified`, `blocked`, `drift`, `error`;
- `cex_balance_refresh_total{provider,outcome}` where outcome is one of
  `success`, `timeout`, `rate_limited`, `auth_error`, `provider_error`,
  `malformed`;
- `cex_balance_refresh_duration_seconds{provider}`;
- `cex_snapshot_age_seconds{provider,state}` with state limited to
  `fresh`, `stale`, `unavailable`;
- `cex_connector_state_total{provider,state}` using the frozen connector-state
  enum;
- `cex_disconnect_total{provider,outcome}` where outcome is `revoked`,
  `blocked`, or `error`;
- `cex_owner_boundary_denials_total{surface}` and
  `cex_forbidden_capability_total{provider,capability}`.

Labels are allowlisted. `owner`, `account`, `source`, `credential`, asset,
amount, exception text and URL are forbidden labels. Logs use a correlation ID
that cannot be reversed to a customer or connector identifier.

## Alert policy

| Severity | Trigger | Operator action |
|---|---|---|
| Critical | owner-boundary disclosure, forbidden capability, permission drift | Disable affected connector ingress/refresh, preserve evidence, begin security runbook |
| High | permission evidence older than 15m, auth failures for any eligible connector, disconnect blocked | Block affected connector, verify vault/revoke state manually |
| Warning | success `<95%` over 15m, p99 `>5s`, rate limiting, snapshot age `>5m` | Degrade provider, keep last snapshot stale, investigate provider health |
| Info | 24h SLO miss without a current fast-window breach | Open reliability follow-up; do not weaken gates |

An alert clears only after two consecutive healthy five-minute windows. A
process restart, missing metric series or clock regression cannot clear it.

## Incident runbooks

### Permission drift or forbidden capability

1. Stop new refreshes for the affected connector/provider and set `BLOCKED`.
2. Do not call order, transfer or withdrawal endpoints to test the finding.
3. Preserve sanitized permission evidence, timestamps and event hashes.
4. Revoke/delete the credential through the scoped vault path. If deletion is
   ambiguous, retain `BLOCKED` and require manual reconciliation.
5. Resume only with a newly issued read-only credential, fresh permission
   proof and an explicit owner-approved production gate.

### Provider outage, timeout or rate limit

1. Retain the last valid balance snapshot and advance its visible state from
   fresh to `STALE`, then `UNAVAILABLE` at the thresholds above.
2. Use bounded exponential backoff with provider-documented rate limits; never
   fan out retries across customer connectors.
3. Keep Wallet and ObsidianExchange lanes available independently.
4. Close after two healthy windows; record the SLO impact and provider cause.

### Authentication failure

1. Stop refreshes; distinguish bounded `auth_error` from provider outage
   without logging raw responses.
2. Re-run only the non-effectful permission self-inspection within retry
   limits. Repeated or malformed results become `BLOCKED`.
3. Ask the owner to reconnect only after confirming no withdrawal, transfer or
   trade permission exists. Never reuse an uncertain credential reference.

### Owner-boundary or privacy breach

1. Disable the affected Wallet CEX surface and block connector reads.
2. Preserve append-only sanitized audit evidence; do not copy credentials or
   raw balances into tickets or chat.
3. Determine the exposed principal/scope, revoke affected credentials and
   rotate service identity if its boundary is implicated.
4. Restore only after owner-isolation regression tests and an incident review.

### Disconnect stuck in `REVOKING`

1. Confirm refresh scheduling stopped before inspecting deletion state.
2. Query only the scoped vault deletion result and sanitized connector event.
3. If absence is proven, finalize `REVOKED`; otherwise set `BLOCKED` and
   escalate. Never recreate or automatically requeue the credential.

## Readiness evidence

Before any testnet credential, synthetic fault tests must demonstrate stale
rendering, timeout/backoff, permission drift, owner isolation and crash-safe
disconnect. Before any production credential, the owner must separately approve
the provider/account, evidence must show every forbidden permission is false,
and dashboards/alerts/runbooks must be exercised with credential-free fixtures.
