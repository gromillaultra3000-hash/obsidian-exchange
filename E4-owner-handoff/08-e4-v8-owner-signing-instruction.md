# E4 v8 — offline owner signing

This public payload is non-authoritative. It does not authorize Docker,
PostgreSQL, decryption or production contact.

Payload: `e4-owner-decision-payload.v8.json`

SHA-256:

```text
251c8a8851c688701905fd99a6a744d25bc636d8fb380896cd84c77a94cb7ac1  e4-owner-decision-payload.v8.json
```

Approval window: `2026-08-23T01:08:43.203Z` through
`2026-08-23T01:23:43.203Z` UTC. The expired v6/v7 payloads must not be signed
or reused.

After downloading the exact file to Termux:

```bash
mkdir -p "$HOME/e4-key"
chmod 700 "$HOME/e4-key"
cd "$HOME/e4-key"
sha256sum e4-owner-decision-payload.v8.json

ssh-keygen -Y sign \
  -f "$HOME/e4-key/owner-signing" \
  -n e4-owner@obsidian-exchange.local \
  "$HOME/e4-key/e4-owner-decision-payload.v8.json"

scp -O "$HOME/e4-key/e4-owner-decision-payload.v8.json.sig" \
  root@185.236.228.19:/root/E4-owner-handoff/
```

Expected owner fingerprint:
`SHA256:G4szs+1DvEQygs3LZS1LDNNRyBYLUHZuX0a7C/gRjII`.
Return only the public signature and payload SHA-256. Never send the private
key or passphrase. An independent reviewer must create a separate envelope
and signature before any verifier can consider the rehearsal eligible.
