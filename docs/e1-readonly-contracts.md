# E1 read-only CEX contracts

Frozen: 2026-08-10. These schemas are additive-versioned public contracts for
the authenticated Wallet surface. Removing/renaming a field, changing custody
semantics or broadening an enum requires a new schema version and compatibility
fixture; silently changing a `v1` response is forbidden.

## Frozen responses

| Endpoint | Version | Fixture | Privacy/custody invariant |
|---|---|---|---|
| `GET /api/wallet/cex-sources` | `connector-list.v1` | `contracts/e1-readonly/connector-list.v1.json` | authenticated owner only; no secret/vault ref |
| `GET /api/wallet/cex-events` | `connector-events.v1` | `contracts/e1-readonly/connector-events.v1.json` | no owner/source/account/credential identifiers; 90 days/1,000 events |
| `GET /api/wallet/portfolio` | `unified-portfolio.v1` | `contracts/e1-readonly/unified-portfolio.v1.json` | three ordered, non-crossing custody lanes; unavailable is never zero |

`connector-list.v1` may expose an opaque source/account reference only to its
authenticated owner so the owner can identify and revoke a connection. The
event projection deliberately omits both identifiers. ObsidianExchange exposes
activity, not a custodial portfolio balance.

## Compatibility and readiness

`deploy/check_e1_readonly_readiness.py` validates exact fixture fields, versions,
lane order, enums, retention constants, disabled credential ingress and the
absence of credential material. With `--production`, the keyless closure gate
also requires the KAIROS connector store to be absent or contain zero connectors
and zero events.

The gate performs no network requests, accepts no credentials and does not
create the connector store. A `GO` means the keyless read-only surface is
internally compatible; it does not authorize a testnet or production CEX key,
trading, withdrawal, transfer or custody change.
