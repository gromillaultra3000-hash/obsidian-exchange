# Current ecosystem contracts and trust boundaries

As of `2026-08-15T07:27:30Z` the authoritative inventory is
`docs/ecosystem-contracts.v1.json`. This document is its human-readable view.
Superseded runtime states remain available through Git history and are not
mixed into the current contract.

## Runtime components

| Component | Boundary | Principal | Custody/money role |
|---|---|---|---|
| Wallet/Relay | `relay-fastapi.service`, public through nginx, app on loopback | `relay-svc` | logical Wallet reads/intents, but the shared process retains effective Exchange write capability; no user keys |
| Exchange | Relay workflows, Telegram bot and isolated payout worker | mixed: `relay-svc`, root bot, `obsidian-payout` signer | private non-KYC operational payout lane; money writer |
| KAIROS | loopback `kairos.service` | `kairos-svc` | external CEX custody; current Wallet execution is held, but deployed code contains dormant live-capable engine paths |
| LUMI | loopback `lumi.service` | `lumi-svc` | advisory only; no custody or money mutation |

The remaining root bot and the split ownership of money writers are recorded
gaps for E0.3. This E0.2 inventory does not pretend to assign their final owners.

## Current edges

- Client→Wallet authentication is route-specific. Telegram-only mutations
  validate initData and web proof mutations verify CSRF. Linked-web CEX
  disconnect derives the server-side owner and requires literal confirmation,
  but currently lacks an explicit CSRF check; this is a recorded security gap.
- Wallet↔Exchange is an explicit same-process/PostgreSQL trust boundary, not a
  network call. Read projections cannot implicitly invoke a money writer.
- Relay→KAIROS market is a bounded loopback public-quote GET with no customer,
  balance, credential or trade-intent data and fail-soft availability.
- Relay→KAIROS connector list/events/disconnect uses canonical Ed25519 service
  requests, timestamp, nonce/replay protection, exact scopes and a server-derived
  opaque principal. The browser sends no ownerRef, vaultRef or credential.
- Authenticated KAIROS connect and shadow-ingress endpoints exist but have no
  enabled product/UI producer; they are inventoried as dormant, not erased. A
  future connect producer would send bounded raw credentials across the signed
  loopback edge for immediate KAIROS vault sealing; shadow uses the shared Relay
  service identity with a separate exact scope, not a separate identity.
- KAIROS→LUMI is limited to two exact Bearer-authenticated POST paths and bounded
  host metadata/committee facts. Registration is a bounded audit mutation;
  conflict resolution is advisory-only. The service credential cannot reach
  scanner/sandbox/apply capabilities and cannot mutate money.
- External provider, dormant CEX engine, payment-provider and isolated signer/
  chain boundaries are inventoried explicitly, including their failure rules.
- KAIROS and LUMI operator control planes are protected separately from their
  narrow inter-service contract.

The current legacy LUMI bridge is advisory-only: on LUMI failure it preserves
the committee verdict, but the path has no execution effect. This is documented
truthfully rather than called HOLD; it is not the future E2 money-gating contract.

## Non-crossing rules

- No server component receives a user seed or wallet private key.
- CEX credentials belong only in the dedicated connector vault.
- LUMI receives no keys, account identifiers, wallet addresses or raw balances.
- Unknown or ambiguous effectful state is reconciled or held for review; it is
  not resubmitted blindly.
- Private Exchange and verified CEX custody remain separate even when displayed
  in one portfolio.

## Scope boundary

This closes only the current-contract inventory portion of E0. It does not close
the separate E0.3 owner/retention/backup registry or E0.4 surface inventory.
