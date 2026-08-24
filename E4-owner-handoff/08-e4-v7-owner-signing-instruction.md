# E4 v7 — offline owner signing

This is a public, non-authoritative handoff. It does not authorize Docker,
PostgreSQL, decryption or production contact.

## Exact payload

File: `e4-owner-decision-payload.v7.json`

SHA-256:

```text
2440b60f8a0c62fcd093b5ad51c515d4f01373915a3ba339003e79f967e4c480  e4-owner-decision-payload.v7.json
```

Approval window: `2026-08-23T00:55:21.759Z` through
`2026-08-23T01:10:21.759Z` (15 minutes). The payload uses the existing
encrypted snapshot, retains its ciphertext after rehearsal, and uses the
previously owner-selected target reference, which has never been created.
The expired v6 payload and its nonce must not be reused.

## Copy to the offline Android/Termux device

Run in Termux after the payload has been placed on the server:

```bash
mkdir -p "$HOME/e4-key"
chmod 700 "$HOME/e4-key"
scp root@185.236.228.19:/root/E4-owner-handoff/e4-owner-decision-payload.v7.json \
  "$HOME/e4-key/"
cd "$HOME/e4-key"
sha256sum e4-owner-decision-payload.v7.json
```

The expected hash is the exact SHA-256 above.

## Offline owner steps

1. Verify the exact hash and owner public-key fingerprint
   `SHA256:G4szs+1DvEQygs3LZS1LDNNRyBYLUHZuX0a7C/gRjII`.
2. Sign only the exact JSON file with the existing offline owner key:

   ```bash
   ssh-keygen -Y sign \
     -f "$HOME/e4-key/owner-signing" \
     -n e4-owner@obsidian-exchange.local \
     "$HOME/e4-key/e4-owner-decision-payload.v7.json"
   ```

3. Verify that the signature file is
   `$HOME/e4-key/e4-owner-decision-payload.v7.json.sig`.
4. Upload only the public signature back to the server:

   ```bash
   scp "$HOME/e4-key/e4-owner-decision-payload.v7.json.sig" \
     root@185.236.228.19:/root/E4-owner-handoff/
   ```

Never send the private key or passphrase. Do not edit, rename or regenerate
the JSON after signing. An independent reviewer must inspect this exact
payload and owner signature, then sign a separate reviewer envelope with the
distinct reviewer key. A real verifier must accept both signatures, trusted
time, exact binding and a fresh one-shot replay claim before any rehearsal can
be considered eligible.

Stop if the hash differs, a key would be overwritten, or any command asks for
private material in chat or on the server.
