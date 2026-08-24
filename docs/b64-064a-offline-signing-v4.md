# 064A v4 offline evidence-decision handoff

Status: exact candidate handoff only. This ceremony can accept bounded
read-only evidence only; it cannot authorize production mutation, 064B, 064D,
deployment, restart, Telegram delivery, retry, cutover or row disposition.

## Exact public inputs

Copy these public, secret-free files independently to both offline devices.
Compare raw-byte SHA-256 through a second trusted channel before any key or
signature operation:

- current decision candidate
  `docs/e0-3-bot-b5-3-064a-decision-candidate.v4.json`:
  `32d54d2bfaf555c7d795cc70b8b92561d7a6d9a19262eb1089eb3611aafd2316`;
- current source observation
  `docs/e0-3-bot-b5-3-064a-production-source-refresh.v4.json`:
  `99531224f6eac8d13ce07b14fdf6408f333fca2a10426e7876613ce3da812a80`;
- immutable prior candidate state
  `docs/e0-3-bot-b5-3-064a-decision-candidate.v3.json`:
  `771ce159032de810d8b09731be109af6a2bb317fc1b8b6e2f5a0d3fff9a08ddf`;
- active restrictive deferral
  `docs/e0-3-bot-b5-3-064a-owner-deferral.v3.json`:
  `c1cf8375efe84ce4a77302263f3450d661f732ee88dd30164dc711bc94a2f7e3`.

The v3 candidate and v3 deferral are prior-state bindings. The v4 candidate
must be supplied as `--decision-input`; do not substitute the prior candidate.
The source observation was recorded at `2026-08-22T03:25:06Z` and has a
maximum age of 86400 seconds. Expiry invalidates the handoff and never grants
permission; after expiry, obtain a new read-only observation and candidate.

## Independence and keyring

Use two genuinely independent offline devices and two human roles:
`INDEPENDENT_REVIEWER` and `ACCOUNTABLE_OWNER`. A second account, browser
profile, VM or key on the same device does not satisfy this requirement.

Generate private keys only on their originating devices. Exchange only the
public JSON entries, then build a `CANDIDATE_OFFLINE` keyring. Private keys,
passphrases, DSNs, `.env` files and production data never enter the repository
or server. Use the already-installed reviewed Python environment; do not
install dependencies from the network during the ceremony.

On the reviewer device, generate only the reviewer key; on the owner device,
generate only the owner key. The signer prompts locally for passphrases:

```bash
python scripts/b64_064a_offline_signer.py generate-key \
  --role INDEPENDENT_REVIEWER \
  --identity-id REVIEWER_ID \
  --trust-domain REVIEWER_TRUST_DOMAIN \
  --private-out /absolute/reviewer/reviewer.key \
  --public-out /absolute/reviewer/reviewer-public.json

python scripts/b64_064a_offline_signer.py generate-key \
  --role ACCOUNTABLE_OWNER \
  --identity-id OWNER_ID \
  --trust-domain OWNER_TRUST_DOMAIN \
  --private-out /absolute/owner/owner.key \
  --public-out /absolute/owner/owner-public.json
```

After independently comparing only the two public entries, build the candidate
keyring in the owner-controlled coordination directory:

```bash
python scripts/b64_064a_offline_signer.py build-keyring \
  --reviewer-public /absolute/coord/reviewer-public.json \
  --owner-public /absolute/coord/owner-public.json \
  --out /absolute/coord/keyring.json
```

## Create the exact statement

Use an owner-controlled `0700` coordination directory and `0600` files. Create
the statement once from the exact four inputs and transfer only the statement
and public keyring to the signing participants:

```bash
python scripts/b64_064a_offline_signer.py create-statement \
  --decision-input /absolute/coord/e0-3-bot-b5-3-064a-decision-candidate.v4.json \
  --source-observation /absolute/coord/e0-3-bot-b5-3-064a-production-source-refresh.v4.json \
  --prior-state /absolute/coord/e0-3-bot-b5-3-064a-decision-candidate.v3.json \
  --active-deferral /absolute/coord/e0-3-bot-b5-3-064a-owner-deferral.v3.json \
  --keyring /absolute/coord/keyring.json \
  --issued-at "$ISSUED_AT" \
  --expires-at "$EXPIRES_AT" \
  --out /absolute/coord/statement.json
```

Set `ISSUED_AT` to the current trusted epoch only after independently checking
that it falls between the source observation and its 86400-second expiry. Set
`EXPIRES_AT` to a short lifetime no greater than 24 hours. The signer
recomputes all four raw-byte hashes and rejects stale, replaced or semantically
inconsistent inputs.

## Review and countersign

The independent reviewer verifies the four exact hashes, the read-only restore
equality, the 4 PENDING and 14 SENDING source counts, the stale subset, every
false authority flag and the restrictive deferral. The reviewer then runs
`sign-reviewer` on the exact statement/keyring. The accountable owner performs
the same comparison and runs `sign-owner` over that exact reviewer envelope.
Neither role may reuse the other role's device, key, identity or trust domain.

The reviewer signs on the reviewer device:

```bash
python scripts/b64_064a_offline_signer.py sign-reviewer \
  --statement /absolute/coord/statement.json \
  --keyring /absolute/coord/keyring.json \
  --private-key /absolute/reviewer/reviewer.key \
  --out /absolute/coord/reviewer-envelope.json
```

The owner verifies the reviewer envelope and countersigns on the owner device:

```bash
python scripts/b64_064a_offline_signer.py sign-owner \
  --statement /absolute/coord/statement.json \
  --keyring /absolute/coord/keyring.json \
  --private-key /absolute/owner/owner.key \
  --reviewer /absolute/coord/reviewer-envelope.json \
  --out /absolute/coord/owner-envelope.json
```

Verification must use the v4 candidate and the same source, v3 prior candidate
and v3 deferral files:

```bash
python scripts/b64_064a_offline_signer.py verify \
  --decision-input /absolute/coord/e0-3-bot-b5-3-064a-decision-candidate.v4.json \
  --source-observation /absolute/coord/e0-3-bot-b5-3-064a-production-source-refresh.v4.json \
  --prior-state /absolute/coord/e0-3-bot-b5-3-064a-decision-candidate.v3.json \
  --active-deferral /absolute/coord/e0-3-bot-b5-3-064a-owner-deferral.v3.json \
  --statement /absolute/coord/statement.json \
  --reviewer /absolute/coord/reviewer-envelope.json \
  --owner /absolute/coord/owner-envelope.json \
  --keyring /absolute/coord/keyring.json \
  --now "$NOW"
```

Expected result remains `SYNTHETIC_VALID` at the protocol layer with
`replayProtectionVerified:false`, `boundedEvidenceAccepted:false`,
`productionExpandAuthorized:false`, `cutoverAuthorized:false` and
`actionAllowed:false` until authenticated registry enrollment, trusted time,
revocation and durable replay consumption exist. The handoff itself does not
clear `BLOCKED_OWNER`.

Never transfer private keys, passphrases, database archives, row manifests,
production payloads, credentials, shell history or unredacted logs.
