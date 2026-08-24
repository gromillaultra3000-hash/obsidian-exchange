# 064A production-authenticated evidence signing

Status: prepared, awaiting two independent public keys and signatures.

This ceremony accepts only the exact disposable rehearsal evidence used by the
dormant production supervisor. It cannot authorize `LOGIN`, credential
issuance, customer-row reads, dump/restore execution, refresh, mutation,
migration, money actions, retries or any other action. All eight authority
fields in the signed payload are `false`.

The signing roles must use separate people, devices, identities, trust domains
and Ed25519 keys:

- `ACCOUNTABLE_OWNER`;
- `INDEPENDENT_REVIEWER`.

Do not reuse the E4 keys implicitly. Generate dedicated 064A keys unless the
owner explicitly approves a cross-scope trust decision. Private keys and
passphrases never enter the server, repository, chat, shell history or shared
coordination directory.

## 1. Generate one key on each offline device

Create a new `0700` directory on each device. Run only the command for that
device; choose stable ASCII identifiers containing letters, digits, `_` or
`-`. The tool prompts locally for a passphrase of at least 16 bytes and writes
both files as `0600` without overwriting an existing path.

Reviewer device:

```bash
python3 scripts/b64_064a_evidence_acceptance.py generate-key \
  --role INDEPENDENT_REVIEWER \
  --identity-id REVIEWER_ID \
  --trust-domain REVIEWER_DEVICE_DOMAIN \
  --private-out /absolute/reviewer-064a/reviewer.key \
  --public-out /absolute/reviewer-064a/reviewer-public.json
```

Owner device:

```bash
python3 scripts/b64_064a_evidence_acceptance.py generate-key \
  --role ACCOUNTABLE_OWNER \
  --identity-id OWNER_ID \
  --trust-domain OWNER_DEVICE_DOMAIN \
  --private-out /absolute/owner-064a/owner.key \
  --public-out /absolute/owner-064a/owner-public.json
```

Transfer only `owner-public.json` and `reviewer-public.json` to the production
coordinator. Compare their raw-byte SHA-256 values through a second trusted
channel.

## 2. Build a fresh pinned revocation-aware keyring

The coordinator initializes an explicit empty revocation snapshot only after
both roles confirm that neither new key is revoked. Any known prior revoked
064A key must instead be listed with `keyId`, `revokedAtEpoch` and a tokenized
`reasonCode` before building the keyring.

```bash
python3 scripts/b64_064a_evidence_acceptance.py init-revocations \
  --out /absolute/coord/revocations.json

python3 scripts/b64_064a_evidence_acceptance.py build-keyring \
  --owner-public /absolute/coord/owner-public.json \
  --reviewer-public /absolute/coord/reviewer-public.json \
  --revocations /absolute/coord/revocations.json \
  --registry-version 1 \
  --issued-at "$KEYRING_ISSUED_EPOCH" \
  --expires-at "$KEYRING_EXPIRES_EPOCH" \
  --out /absolute/coord/keyring.json
```

The keyring lifetime cannot exceed seven days. Record its reported
`keyringSha256` independently; final assembly and production deployment require
that external digest as a separate input.

## 3. Create the exact unsigned acceptance

Create this only when both signing devices are ready. Its lifetime cannot
exceed 24 hours and must fit completely inside the keyring window. A short
two-hour window is preferred.

```bash
python3 scripts/b64_064a_evidence_acceptance.py create-acceptance \
  --keyring /absolute/coord/keyring.json \
  --issued-at "$ACCEPTANCE_ISSUED_EPOCH" \
  --expires-at "$ACCEPTANCE_EXPIRES_EPOCH" \
  --evidence-root /root \
  --rehearsal-root /opt/obsidian-exchange/releases/e0-e0.3-b5.3-064a/abb22afc99e504cee29881d5e4b19ba15c0f343d \
  --out /absolute/coord/acceptance-unsigned.json
```

The tool recomputes and binds these exact values:

- evidence SHA-256:
  `d9e690aa77b0e58887417da718c2f5786c0616c7c9291937a4adb5c34bd87dfc`;
- plan SHA-256:
  `14d38a9fc0cc7c78014d16230553359939aad7d7a15abaf7c7cc8672c3c8d0c6`;
- immutable rehearsal commit:
  `abb22afc99e504cee29881d5e4b19ba15c0f343d`;
- 16-artifact closure SHA-256:
  `e4d0a3d35702895c434b0ed647ad8a20278d104aaadd18281f28138762216122`.

Transfer only `keyring.json` and `acceptance-unsigned.json` to each offline
device. Each role independently confirms the hashes, validity window, nonce,
decision `ACCEPT_EXACT_DISPOSABLE_REHEARSAL_EVIDENCE_ONLY`, and that every
authority value is exactly boolean `false`.

## 4. Produce two detached signatures

Reviewer device:

```bash
python3 scripts/b64_064a_evidence_acceptance.py sign \
  --role INDEPENDENT_REVIEWER \
  --keyring /absolute/reviewer-064a/keyring.json \
  --acceptance /absolute/reviewer-064a/acceptance-unsigned.json \
  --private-key /absolute/reviewer-064a/reviewer.key \
  --out /absolute/reviewer-064a/reviewer-signature.json
```

Owner device:

```bash
python3 scripts/b64_064a_evidence_acceptance.py sign \
  --role ACCOUNTABLE_OWNER \
  --keyring /absolute/owner-064a/keyring.json \
  --acceptance /absolute/owner-064a/acceptance-unsigned.json \
  --private-key /absolute/owner-064a/owner.key \
  --out /absolute/owner-064a/owner-signature.json
```

Return only the two `*-signature.json` files. The coordinator assembles and
verifies them against the independently recorded keyring digest. Deployment is
non-activating and is permitted only while the package is fresh and the
production reader remains `NOLOGIN` with no credential.
