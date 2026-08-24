# E4 v6 — offline owner signing

This is a public, non-authoritative handoff. It does not authorize Docker,
PostgreSQL, decryption or production contact.

## Exact payload

File: `e4-owner-decision-payload.v6.json`

SHA-256:

```text
2e7779db75a894be076753ab40ce5c2493bd22ca8895e75f8765c133dd14a0af  e4-owner-decision-payload.v6.json
```

The payload uses the existing encrypted snapshot and retains the ciphertext
after rehearsal. It uses the previously owner-selected target reference, which
has never been created, and a new single-use nonce/window. The old v5 claim
must not be reused.

## Offline owner steps

1. Copy the exact JSON file to the controlled offline Android/Termux device.
2. Verify the SHA-256 above and the owner public-key fingerprint:
   `SHA256:G4szs+1DvEQygs3LZS1LDNNRyBYLUHZuX0a7C/gRjII`.
3. Sign only this exact file with the existing offline owner key:

   ```bash
   ssh-keygen -Y sign \
     -f ~/e4-key/owner-signing \
     -n e4-owner@obsidian-exchange.local \
     e4-owner-decision-payload.v6.json
   ```

4. Do not edit, rename or regenerate the JSON after signing. Do not send the
   private key or passphrase.
5. Return only the public signature file and the verified payload SHA-256.

An independent reviewer must inspect this exact payload and owner signature,
then sign a separate reviewer envelope with the distinct reviewer key. A real
verifier must accept both signatures, trusted time, exact binding and a fresh
one-shot replay claim before any rehearsal can be considered eligible.

Stop if the file hash differs, a key would be overwritten, or any command asks
for private material in chat or on the server.
