# E4 website SWAP operations

The production scope is `relay-fastapi/main.py`, `swap_review.py`,
`templates/dashboard_swap.html`, and `templates/dashboard_swap_review.html`.
The inventory retains hashes for 57 other inputs and process identities for the
bot, nginx and PostgreSQL. Autopilot must be inactive/failed with PID zero.

Use `/opt/obsidian-exchange/relay-venv/bin/python` to run `rollout.py`:

```
rollout.py prepare --plan docs/e4-website-swap/plan.json
rollout.py apply --plan docs/e4-website-swap/plan.json --backup /var/lib/obsidian-exchange/deployment-preimages/e4-website-swap-20260911
rollout.py reconcile --plan docs/e4-website-swap/plan.json --backup /var/lib/obsidian-exchange/deployment-preimages/e4-website-swap-20260911
rollout.py rollback --plan docs/e4-website-swap/plan.json --backup /var/lib/obsidian-exchange/deployment-preimages/e4-website-swap-20260911
```

Prepare compiles Python into a temporary directory and parses candidate Jinja;
it does not import application code or write into production. Apply stores
fsynced preimages, checks exact pinned inputs/metadata, replaces bounded files,
and restarts only relay. It installs Python and the new review template, restarts
relay, then replaces the entry form: the quote-only label cannot reach the old
creating handler. Rollback restores the entry form first. Both quote POST
(`/dashboard/swap/quote`) and confirm/edit POST (`/dashboard/swap/confirm`) use
new URLs absent in the baseline backend, so both stale forms fail with 404
after rollback. Public unauthenticated SWAP/Buy/Sell GETs must remain
302 to `/login`; this does not prove an authenticated money operation.

The quote-review cache is process-local: a relay restart invalidates pending
reviews. The production command is a single direct `main.py` process with one
Uvicorn worker. A failed apply is not permission to retry creation; rollback
accepts the expected partial baseline/candidate file mixture, restores original
bytes/metadata, removes both new files and restarts relay. Rollback works when
relay itself failed; unrelated process drift still stops the action.

`check-rollout.py` uses temporary files and fake process/public responses for
apply, reconcile, interrupted apply and failed-relay rollback. It does not
restart production or access customer data.
