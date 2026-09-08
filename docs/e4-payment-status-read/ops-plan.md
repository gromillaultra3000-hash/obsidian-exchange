# E4 payment-status runtime read contract

2026-09-08 UTC. Active route: `E4 / PAYMENT_STATUS_RUNTIME_READ_CONTRACT`.

The deployed Relay calls read helpers absent from the installed shared stores:
`authorized_snapshot`, payment-session bearer/authorized lookups and receipt
`authorized_state`. The numeric payment page also imports an absent
`core/order_access.py`. Inspection of exact source plus unauthenticated public
requests reproduces HTTP 500 for `/api/order/0` and `/pay/0` before a repository
query. No real user, order, payment-session token or proof was supplied.

The release publishes only `repositories/payment_status_read_store.py`,
`core/order_access.py`, `relay-fastapi/main.py` and `relay/webapp.html`. Both new
modules must initially be absent. Existing order/session/receipt stores retain
their exact live bytes: checkout versions also contain unrelated authorization,
projection, worker-bound and SQLite receipt-writer changes. The new adapter uses
the installed order store's connection policy and fixed owner-scoped SELECTs.
The effective `RELAY_P3_AUTHORIZED_READ_FUNCTIONS_ENABLED` flag is absent/disabled;
the recipe binds that safe boolean observation before and after restart without
retaining other environment entries or any unrecognized value.

Status GET no longer polls a provider or initiates a payment transition.
Existing callbacks and background workers retain their configuration and code.
Receipt/session read failure returns 503; failed, unknown or obsolete session
instructions cannot be presented as a confirmed live payment route. The small
Mini App text adjustment describes unavailable requisites without inventing the
reason. These product claims require the actual handler and isolated database
test evidence in addition to operations checks.

The one-time release manifest binds all four candidates, original states and the
recipe. Thirteen existing direct/transitive source dependencies are separately pinned.
Required gates are tests, browser checks, acceptance/security reviews, an actual
isolated PostgreSQL rehearsal, exact-live-dependency rehearsal, and rollback
mechanics. Inputs use `{path, sha256}` records. Preflight verifies compilation,
exact baseline, public template GET200/POST405/history403 and the two observed
baseline failures. Binding, rehearsal and preflight do not mutate runtime.

The primary agent alone may run the gated deployment:

```sh
python3 /root/deploy/e4_payment_status_read_rollout.py deploy
```

It saves private, fsynced byte and metadata preimages, installs the two additive
modules followed by main and HTML, journals restart intent, and requests one
`relay-fastapi.service` restart. Bot, Nginx and PostgreSQL PID/start identities
must remain unchanged. Candidate `/api/order/0` and `/pay/0` must return 404
before SQL; the other public checks must remain unchanged. Restart resumes the
already configured ordinary background work; it is not evidence that existing
runtime writes or notifications cease.

After an interrupted command, observe before any further action:

```sh
python3 /root/deploy/e4_payment_status_read_rollout.py reconcile
```

`reconcile` never repeats publication or a restart. An interrupted deploy can
be explicitly rolled back with the recipe's `rollback` mode. Rollback accepts
only known original/candidate bytes, restores old main and HTML, restarts Relay,
then removes only the exact additive modules. It verifies preimages, metadata,
public behavior and service boundaries. `/api/order/0` returns the original 500.
Proofless `/pay/0` may return the original 500 or a safe 404 if a concurrent
request cached the proof module between old-main restart and file removal;
neither response enters SQL or exposes an order. This is recorded as an observed
rollback result, not a repaired-baseline claim.

An interrupted rollback requires independent inspection and manual completion
of the known remaining steps; deploy and rollback replay are both refused.
Unknown runtime bytes, changed preimages, active autopilot or a changed service
boundary stop the operation. Isolated source/command-boundary tests do not claim
that a real production restart or rollback was rehearsed.
