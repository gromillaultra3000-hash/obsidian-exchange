# 064A v3 offline evidence-decision handoff

Status: exact candidate signing workflow only. It cannot authorize production
mutation, 064B, 064D, deployment, restart, Telegram delivery or cutover.

## Exact public inputs

Transfer these four public, secret-free files independently to both offline
devices and compare their raw-byte SHA-256 through a second trusted channel:

- decision candidate `e0-3-bot-b5-3-064a-decision-candidate.v3.json`:
  `771ce159032de810d8b09731be109af6a2bb317fc1b8b6e2f5a0d3fff9a08ddf`;
- source observation `e0-3-bot-b5-3-064a-production-source-refresh.v3.json`:
  `280e0b0de3c76992ef1674ef76495a0136138c9ee6ab114ff794f8377437d104`;
- prior candidate `e0-3-bot-b5-3-064a-decision-candidate.v2.json`:
  `760ef8b1a6848ce782dea27c0e3da672ce79f264590b40b1fbd47b25c2dbc99e`;
- active restrictive deferral `e0-3-bot-b5-3-064a-owner-deferral.v2.json`:
  `e5d76a90c4f750ef936eb125eda011678a91ae7c76e794cd9dae634a46973ffb`.

The v2 candidate is prior-state evidence only. It must never be supplied as
`--decision-input`. The source freshness window starts conservatively at
`2026-08-19T02:34:54Z` and ends at `2026-08-20T02:34:54Z`; expiry blocks and
never grants permission.

The current v3 restrictive re-deferral is a separate governance record at
`docs/e0-3-bot-b5-3-064a-owner-deferral.v3.json`. It supersedes the v2
deferral context without changing immutable candidate bytes. No new statement
or signature may be created from the re-deferral conversation.

## Isolated identities and keyring

Use two separate encrypted offline devices and owner-controlled `0700`
directories. The roles are `INDEPENDENT_REVIEWER` and `ACCOUNTABLE_OWNER`.
Private keys and passphrases never leave their originating devices. Generate
candidate keys with `generate-key`, exchange only the public JSON entries, and
use `build-keyring`. The keyring remains `CANDIDATE_OFFLINE`; it has no
production trust or enrollment.

Use only an already-installed reviewed Python environment with `cryptography`.
Do not install anything from the network during the ceremony.

## Create the exact statement

All four input files must be in the same owner-controlled `0700` coordination
directory with mode `0600`. Replace the example epoch values with a time inside
the frozen source window and a short expiry:

```bash
python scripts/b64_064a_offline_signer.py create-statement \
  --decision-input /absolute/coord/e0-3-bot-b5-3-064a-decision-candidate.v3.json \
  --source-observation /absolute/coord/e0-3-bot-b5-3-064a-production-source-refresh.v3.json \
  --prior-state /absolute/coord/e0-3-bot-b5-3-064a-decision-candidate.v2.json \
  --active-deferral /absolute/coord/e0-3-bot-b5-3-064a-owner-deferral.v2.json \
  --keyring /absolute/coord/keyring.json \
  --issued-at 1787107000 \
  --expires-at 1787110600 \
  --out /absolute/coord/statement.json
```

`create-statement` recomputes all four file hashes and cross-checks source
bindings, restore/cleanup state, prior candidate, active deferral and bounded
blockers before producing a statement. Any missing, replaced or semantically
inconsistent input fails closed.

## Review and countersign

The independent reviewer verifies the four exact files, the bounded equality
claim, the one PENDING plus 13 SENDING blockers, and every false authority flag,
then runs `sign-reviewer` over the exact statement/keyring. The owner separately
performs the same checks and runs `sign-owner` with the exact reviewer envelope.
Neither role may reuse the other role's device, key, identity or trust domain.

Run `verify` with `--decision-input` pointing only to the v3 candidate and the
same mandatory `--source-observation`, `--prior-state` and `--active-deferral`
files. Verification recomputes the length-prefixed four-file evidence-bundle
digest before checking signatures. Expected offline result remains
`SYNTHETIC_VALID` with
`replayProtectionVerified:false`, `boundedEvidenceAccepted:false`,
`productionExpandAuthorized:false`, `cutoverAuthorized:false` and
`actionAllowed:false`.

A real evidence decision still requires authenticated key enrollment, trusted
time/revocation and atomic durable replay acceptance. Those are absent. Signing
or verification cannot clear `BLOCKED_OWNER` by itself.

## Never transfer

Never transfer keys, passphrases, DSNs, `.env` files, database archives, row
manifests, production payloads, credentials, container data, shell history or
unredacted logs. The production archive used for this refresh was deleted.
