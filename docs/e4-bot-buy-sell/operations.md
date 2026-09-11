# E4 Telegram buy/sell operations

Production scope: `/opt/obsidian-exchange/bot/action_review.py` (new),
`main_bot.py` (existing). Baseline captures 62 inputs; 60 unrelated file hashes
and relay/nginx/PostgreSQL process identities must remain unchanged. The
inactive/failed autopilot must have PID zero. Exactly one bot process must match
the systemd MainPID; no application import or Telegram requests in preflight.

Run from `/root` with `python3 docs/e4-bot-buy-sell/rollout.py`:

```
prepare --plan docs/e4-bot-buy-sell/plan.json
apply --plan docs/e4-bot-buy-sell/plan.json --backup /var/lib/obsidian-exchange/deployment-preimages/e4-bot-buy-sell-20260911
reconcile --plan docs/e4-bot-buy-sell/plan.json --backup /var/lib/obsidian-exchange/deployment-preimages/e4-bot-buy-sell-20260911
rollback --plan docs/e4-bot-buy-sell/plan.json --backup /var/lib/obsidian-exchange/deployment-preimages/e4-bot-buy-sell-20260911
```

Prepare pins source/live hashes, compiles into temporary storage, and captures
single-process health without customer/provider calls. Apply stores/fsyncs the
preimage and exact plan before replacing the helper then the entry point;
restarts only `exchange-bot.service` once after both files are ready. Existing
bot code continues in memory during publication. Reconcile does not restart.
Startup verification checks active/running and stable single PID across two
seconds; this proves process health, not a real Telegram money flow.

Rollback tolerates either baseline/candidate bytes per target and a failed bot,
restores `main_bot.py` before removing the new helper, then restarts only the
bot. Backup hashes/metadata and unrelated inputs/processes remain required.
The `order_review_` callback namespace must remain absent in the baseline:
stale review buttons are inert after rollback. In-process review receipts expire
on restart; Redis-backed FSM state may remain but must not authorize a receipt
absent from process memory. Users restart an expired review from the menu.

`python3 docs/e4-bot-buy-sell/check-rollout.py` rehearses apply, reconcile,
failed-bot rollback, partial publication, tampered inputs/preimages, and metadata
preservation in temporary files with mocked systemd/process responses. It never
restarts production or imports bot code.
