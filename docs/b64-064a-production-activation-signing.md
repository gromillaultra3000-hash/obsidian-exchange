# 064A production activation v3 signing ceremony

Status: secret-free preparation for `E0/E0.3/B5.3/064A`. This runbook does
not create `launch.request`, does not start the launcher, and does not grant
authority without two fresh detached signatures over one exact v3 decision.

## Fixed boundaries

- Online coordination root:
  `/root/064A-activation-signing-active` (root-owned, mode `0700`).
- Production implementation: the exact commit pinned in
  `scripts/b64_064a_activation_ceremony.py` and all three installed systemd
  units.
- Signers: one `ACCOUNTABLE_OWNER` and one `INDEPENDENT_REVIEWER`, with the
  distinct public keys and trust domains in the pinned activation registry.
- Decision lifetime: exactly 15 minutes. Assembly requires at least five
  minutes remaining. Never reuse an expired plan, decision, signature, v2
  package, or evidence-only signature.
- Private keys and passphrases remain on their offline signer devices. They
  are never copied to the server, included in an archive, passed in argv, or
  written to a receipt.

## Static offline kit

Create the static kit only after the immutable release and installed units are
pinned and verified. The output parent must be a private `0700` directory and
the output must not already exist:

```bash
/opt/obsidian-exchange/relay-venv/bin/python -E \
  /opt/obsidian-exchange/releases/e0-e0.3-b5.3-064a/176893d808d348b8a8bbda0c017c28a2e7806065/scripts/b64_064a_activation_ceremony.py build-offline-kit \
  --out /root/064A-activation-handoff/obsidian-064a-activation-v3-offline-kit.tar
sha256sum \
  /root/064A-activation-handoff/obsidian-064a-activation-v3-offline-kit.tar
```

Transfer that secret-free kit to both signer devices before opening the short
decision window. Verify its SHA-256 out of band and verify `SHA256SUMS` after
extracting into a new private directory. The kit contains public profiles,
verification/signing code, the pinned trust registry and hardened plan; it
contains no private key, passphrase, database credential or runtime request.

## Fresh online request

Do not begin until both independent signer devices are ready. Create a new,
empty, root-only coordination root and run, without adding caller-controlled
time, target, nonce, hook or release arguments:

```bash
/opt/obsidian-exchange/relay-venv/bin/python -E \
  /opt/obsidian-exchange/releases/e0-e0.3-b5.3-064a/176893d808d348b8a8bbda0c017c28a2e7806065/scripts/b64_064a_activation_ceremony.py build-keyring
/opt/obsidian-exchange/relay-venv/bin/python -E \
  /opt/obsidian-exchange/releases/e0-e0.3-b5.3-064a/176893d808d348b8a8bbda0c017c28a2e7806065/scripts/b64_064a_activation_ceremony.py create-plan
/opt/obsidian-exchange/relay-venv/bin/python -E \
  /opt/obsidian-exchange/releases/e0-e0.3-b5.3-064a/176893d808d348b8a8bbda0c017c28a2e7806065/scripts/b64_064a_activation_ceremony.py create-unsigned-decision
/opt/obsidian-exchange/relay-venv/bin/python -E \
  /opt/obsidian-exchange/releases/e0-e0.3-b5.3-064a/176893d808d348b8a8bbda0c017c28a2e7806065/scripts/b64_064a_activation_ceremony.py export-signing-request \
  --out /root/064A-activation-handoff/obsidian-064a-activation-v3-request.tar
sha256sum \
  /root/064A-activation-handoff/obsidian-064a-activation-v3-request.tar
```

Transfer the same request archive and its out-of-band SHA-256 to both signers.
Each signer independently checks the request manifest, file checksums, target,
limits, authority, expiry, `decisionSha256`, keyring identities and the v3
activation signature domain.

## Offline detached signatures

Extract the static kit and the fresh request into separate new `0700`
directories. From the kit directory, each signer uses only their own encrypted
private key. Replace the example paths with absolute paths whose parent is mode
`0700` and whose private-key file is mode `0600`:

```bash
python scripts/b64_064a_activation_ceremony.py sign \
  --role ACCOUNTABLE_OWNER \
  --public-profile "$PWD/owner-public.json" \
  --keyring /absolute/request/keyring.json \
  --activation-plan /absolute/request/activation-plan.json \
  --decision /absolute/request/decision-unsigned.json \
  --confirm-decision-sha256 EXACT_DECISION_SHA256 \
  --private-key /absolute/owner-private.pem \
  --out /absolute/result/owner-signature.json
```

```bash
python scripts/b64_064a_activation_ceremony.py sign \
  --role INDEPENDENT_REVIEWER \
  --public-profile "$PWD/reviewer-public.json" \
  --keyring /absolute/request/keyring.json \
  --activation-plan /absolute/request/activation-plan.json \
  --decision /absolute/request/decision-unsigned.json \
  --confirm-decision-sha256 EXACT_DECISION_SHA256 \
  --private-key /absolute/reviewer-private.pem \
  --out /absolute/result/reviewer-signature.json
```

Return only the two detached signature JSON files and their SHA-256 values.

## Import and inert verification

Place each returned file in a root-only `0700` inbox, mode `0600`. Importing
performs exact binding and Ed25519 verification before publishing it to the
coordination root. Assembly invokes the verifier from the pinned immutable
release. It still does not create a runtime request or start the launcher:

```bash
/opt/obsidian-exchange/relay-venv/bin/python -E \
  /opt/obsidian-exchange/releases/e0-e0.3-b5.3-064a/176893d808d348b8a8bbda0c017c28a2e7806065/scripts/b64_064a_activation_ceremony.py import-signature \
  --role ACCOUNTABLE_OWNER \
  --signature /absolute/inbox/owner-signature.json
/opt/obsidian-exchange/relay-venv/bin/python -E \
  /opt/obsidian-exchange/releases/e0-e0.3-b5.3-064a/176893d808d348b8a8bbda0c017c28a2e7806065/scripts/b64_064a_activation_ceremony.py import-signature \
  --role INDEPENDENT_REVIEWER \
  --signature /absolute/inbox/reviewer-signature.json
/opt/obsidian-exchange/relay-venv/bin/python -E \
  /opt/obsidian-exchange/releases/e0-e0.3-b5.3-064a/176893d808d348b8a8bbda0c017c28a2e7806065/scripts/b64_064a_activation_ceremony.py assemble-decision
/opt/obsidian-exchange/relay-venv/bin/python -E \
  /opt/obsidian-exchange/releases/e0-e0.3-b5.3-064a/176893d808d348b8a8bbda0c017c28a2e7806065/scripts/b64_064a_activation_ceremony.py verify-decision
```

Expected status is `SIGNED_V3_DECISION_VERIFIED_NOT_DEPLOYED` with
`productionAuthorityComplete=true`, `runtimeRequestsCreated=false`,
`launcherStarted=false` and `actionAllowed=false`. Any expiry, target drift,
revocation/registry mismatch, missing five-minute remainder, unexpected file,
existing output, signature mismatch or immutable-verifier mismatch is a hard
stop. A later exact final preflight must still prove empty activation state,
healthy dormant reader, rollback readiness and explicit bounded launch
authority before any runtime request may be created.
