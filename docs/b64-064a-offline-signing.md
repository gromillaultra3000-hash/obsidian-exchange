# 064A offline signing handoff

> **HISTORICAL V2 — DO NOT USE FOR A CURRENT DECISION.** This ceremony points
> to an expired, re-deferred candidate. The only current handoff is
> `docs/b64-064a-offline-signing-v3.md`. The commands below are retained solely
> to preserve historical evidence.

Status: candidate signing workflow only. It does not authorize production
mutation, 064B deployment, Telegram delivery, ambiguous-row disposition or
cutover.

## People and devices

- The project owner uses one offline device and role `ACCOUNTABLE_OWNER`.
- The selected independent person uses another offline device and role
  `INDEPENDENT_REVIEWER`.
- Private keys never leave their originating devices. Do not send them through
  chat, email, cloud storage or this repository.
- Use owner-controlled `0700` directories on encrypted storage. The current
  software uses encrypted PKCS#8 files but cannot prove hardware-backed custody,
  host cleanliness, memory zeroization or absence of swap/core-dump exposure.

Use a trusted, already-installed Python environment containing `cryptography`.
Do not install packages from the network during the ceremony.

## 1. Generate separate candidate identities

Reviewer, on the reviewer device:

```bash
install -d -m 0700 /absolute/private/reviewer-064a
python scripts/b64_064a_offline_signer.py generate-key \
  --role INDEPENDENT_REVIEWER \
  --identity-id reviewer_1 \
  --trust-domain reviewer_device_1 \
  --private-out /absolute/private/reviewer-064a/reviewer.key \
  --public-out /absolute/private/reviewer-064a/reviewer-public.json
```

Owner, on the owner device:

```bash
install -d -m 0700 /absolute/private/owner-064a
python scripts/b64_064a_offline_signer.py generate-key \
  --role ACCOUNTABLE_OWNER \
  --identity-id owner_1 \
  --trust-domain owner_device_1 \
  --private-out /absolute/private/owner-064a/owner.key \
  --public-out /absolute/private/owner-064a/owner-public.json
```

Each command asks for a passphrase without echo. Only the `*-public.json` files
may be returned to the coordinator. The `.key` files stay offline and separate.
Generated entries remain `CANDIDATE_OFFLINE`; generating them does not enroll a
production identity.

## 2. Build the candidate public keyring

In a fresh `0700` coordination directory, after receiving the two public files:

```bash
python scripts/b64_064a_offline_signer.py build-keyring \
  --reviewer-public /absolute/coord/reviewer-public.json \
  --owner-public /absolute/coord/owner-public.json \
  --out /absolute/coord/keyring.json
```

The command rejects equal keys, identities or trust domains. The keyring still
has no production trust until a separate authenticated enrollment ceremony pins
its digest.

## 3. Create the exact short-lived statement

Use UTC epoch seconds and an expiry no more than 24 hours later. Omitting
`--nonce` makes the tool generate a CSPRNG nonce internally.

```bash
python scripts/b64_064a_offline_signer.py create-statement \
  --decision-input /absolute/coord/e0-3-bot-b5-3-064a-decision-candidate.v2.json \
  --keyring /absolute/coord/keyring.json \
  --issued-at 1800000000 \
  --expires-at 1800003600 \
  --out /absolute/coord/statement.json
```

Replace the example times with the agreed signing window. The issued time must
also fall inside the candidate's frozen 24-hour source-observation window. Both
people must receive identical candidate, source-refresh evidence, keyring and
statement bytes. They independently compare the candidate SHA-256
`760ef8b1a6848ce782dea27c0e3da672ce79f264590b40b1fbd47b25c2dbc99e`
and all command receipts through a second trusted channel. The source evidence
must hash to the digest embedded in the candidate.

## 4. Reviewer signs first

```bash
python scripts/b64_064a_offline_signer.py sign-reviewer \
  --statement /absolute/reviewer/statement.json \
  --keyring /absolute/reviewer/keyring.json \
  --private-key /absolute/private/reviewer-064a/reviewer.key \
  --out /absolute/reviewer/reviewer-envelope.json
```

Reviewer returns only `reviewer-envelope.json`. The owner must receive the exact
same statement/keyring plus that envelope.

## 5. Owner countersigns the exact review

```bash
python scripts/b64_064a_offline_signer.py sign-owner \
  --statement /absolute/owner/statement.json \
  --keyring /absolute/owner/keyring.json \
  --reviewer /absolute/owner/reviewer-envelope.json \
  --private-key /absolute/private/owner-064a/owner.key \
  --out /absolute/owner/owner-envelope.json
```

Owner returns only `owner-envelope.json`.

## 6. Stateless cryptographic check

```bash
python scripts/b64_064a_offline_signer.py verify \
  --decision-input /absolute/coord/e0-3-bot-b5-3-064a-decision-candidate.v2.json \
  --statement /absolute/coord/statement.json \
  --reviewer /absolute/coord/reviewer-envelope.json \
  --owner /absolute/coord/owner-envelope.json \
  --keyring /absolute/coord/keyring.json \
  --now 1800000001
```

Expected candidate result is `SYNTHETIC_VALID` with
`replayProtectionVerified:false`, `boundedEvidenceAccepted:false`,
`productionExpandAuthorized:false`, `cutoverAuthorized:false` and
`actionAllowed:false`.

A production acceptance additionally requires authenticated public-key
enrollment, trusted time/revocation checks and an atomic durable replay ledger.
Those components do not exist yet, so this package cannot clear `BLOCKED_OWNER`.

## Never transfer

Never transfer private keys, passphrases, seeds, PINs, DSNs, `.env` files,
database dumps, row manifests, production payloads, credentials, container data,
shell history or unredacted logs. Public entries, the candidate keyring,
statement and signed envelopes contain no private key material.
