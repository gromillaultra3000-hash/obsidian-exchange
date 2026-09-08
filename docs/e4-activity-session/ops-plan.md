# E4 activity payment-session runtime plan

2026-09-08 UTC. Active route: `E4 / ACTIVITY_PAYMENT_SESSION_STATE`.

The live Relay uses `/opt/obsidian-exchange/relay-fastapi/main.py` and imports
the adjacent `relay` modules during process initialization. A new Python read
module therefore requires a Relay restart. HTML is read on each `/webapp` GET.
Only `relay-fastapi.service` is restarted; bot, Nginx and PostgreSQL identities
must remain unchanged. The owner's explicit manual mode leaves the autopilot
failed/inactive with MainPID zero.

The checkout's `order_read_store.py` contains unrelated older changes absent
from production, affecting SQLite and PostgreSQL authorization and query bounds.
Its live bytes are preserved. The bounded release contains only `main.py`,
`webapp.html` and additive `repositories/activity_read_store.py`. The latter
reuses the existing repository classes, `_c()` policy and `_dict()` conversion.
It does not introduce schema, connection, credential or worker changes.

`ops-release-manifest.json` pins exact original/candidate digests and the recipe.
The baseline requires the new module to be absent. `bind` is one-time and local;
`rehearse` exercises atomic publication/restoration in disposable files;
`preflight` checks source compilation, bytes and unauthenticated public routes.
The recipe's 14 isolated tests cover interrupted publication, rollback ordering,
replay rejection and changed source/service/preimage/unknown-byte guards.

After exact input-bound tests, browser checks and two independent reviews pass,
the primary agent may invoke:

```sh
python3 /root/deploy/e4_activity_session_rollout.py deploy
```

Deployment saves private fsynced byte preimages and original ownership, mode,
mtime and xattrs before publication. It atomically installs the additive module,
main and HTML, journals restart intent, and submits one Relay-only restart.
GET `/webapp` must be 200 and match the deployed template after the existing bot
username substitution; POST must be 405. Unauthenticated GET `/api/history`
must remain 403 with only an error detail. No probe supplies a real user identity.
Service identity and unchanged-source checks follow restart.

The service's unchanged startup first validates schema without DDL, then resumes
its configured cleanup, notification and provider workers. A restart is therefore
not a claim that ordinary runtime writes or notifications cease. The deployment
does not call those actions or change their configuration.

After any command interruption, observe first:

```sh
python3 /root/deploy/e4_activity_session_rollout.py reconcile
```

Reconciliation never repeats publication or a restart. An interrupted deploy
may be explicitly rolled back with:

```sh
python3 /root/deploy/e4_activity_session_rollout.py rollback
```

Rollback verifies all preimages and accepts only known original/candidate bytes,
restores main and HTML, restarts Relay, verifies public behavior, then removes
only the exact additive module. Existing `PYTHONDONTWRITEBYTECODE=1` avoids new
bytecode; a normal `__pycache__` entry cannot substitute for an absent source.
Unknown bytes or changed preimages stop the operation. A rollback interrupted
after its journal begins requires independent inspection and manual completion
of the known remaining steps; both deployment and rollback replay are refused.
The final preimages remain available for audit. Production restart/rollback
execution is separate from the isolated rehearsal evidence.
