# PostgreSQL cutover and rollback runbook

Status: **NO-GO as of 2026-08-09**. This is an executable operational plan,
not authorization to switch production. `DATABASE_URL` and every PostgreSQL
feature flag must remain unset until the static guard reports `GO`, a fresh
54-table rehearsal matches, the critical user-progress invariant gate passes,
and the operator explicitly approves the window.

## Safety properties

- SQLite remains the sole authority until the final writer-start decision.
- There is no application-level dual-write for money state.
- The source copy is made while all exchange writers are stopped.
- PostgreSQL is not exposed to traffic until counts and canonical hashes match.
- The payout signer starts last, after queue and ledger checks.
- Once PostgreSQL accepts a production write, SQLite is stale. Do not perform
  the simple rollback below after that point; keep services stopped and run a
  separately reviewed PostgreSQL→SQLite recovery or repair-forward procedure.

## Required values

Set these only in the operator shell or root-owned `0600` environment files;
never paste credentials into this document, Git, terminal history, or logs.

```text
SQLITE=/var/lib/obsidian-exchange/exchange.db
SNAPSHOT=/var/lib/obsidian-exchange/cutover/exchange-pre-cutover.db
PG_DSN=postgresql://obsidian_app@127.0.0.1:5432/<production-db>
PG_MIGRATOR_DSN=postgresql://obsidian_migrator@127.0.0.1:5432/<production-db>
PG_READONLY_DSN=postgresql://obsidian_readonly@127.0.0.1:5432/<production-db>
PG_PAYOUT_DSN=postgresql://obsidian_payout@127.0.0.1:5432/<production-db>
PG_CLUSTER_ADMIN_DSN=postgresql://postgres@127.0.0.1:5432/postgres
PG_TARGET_ADMIN_DSN=postgresql://postgres@127.0.0.1:5432/<production-db>
```

Services in the write freeze:

```text
relay-fastapi.service
exchange-bot.service
obsidian-payout-worker.service
exchange-notifier.service
obsidian-monitor.service
admin-panel.service
support-bot.service
```

## Phase 0 — code and infrastructure preflight

1. Run the static guard. Any listed runtime SQLite access is a hard blocker for
   an authoritative cutover, even if it appears read-only: leaving it active
   would create split-brain after the first PostgreSQL write.

   ```bash
   /opt/obsidian-exchange/relay-venv/bin/python \
     deploy/postgres/cutover_preflight.py --root /opt/obsidian-exchange
   ```

2. Provision the PostgreSQL service from the tracked templates; do not
   improvise a mutable image tag or a public listener during the window.

   - `deploy/postgres/compose.production.yml` pins PostgreSQL 17.10 to an
     immutable image digest, publishes only `127.0.0.1:5432`, uses the durable
     `obsidian-postgres-data` volume and refuses an implicit image pull.
   - Provision a root-owned `0600`
     `/etc/obsidian-exchange/postgres/postgres-password` before first start.
     It is the one-time `initdb` bootstrap secret, not an application DSN.
     Replacing that file after initialization does **not** rotate the database
     password; use an authenticated `ALTER ROLE` procedure for rotation.
   - Validate the rendered definition before installation:

     ```bash
     docker pull postgres@sha256:742f40ea20b9ff2ff31db5458d127452988a2164df9e17441e191f3b72252193
     docker compose --project-name obsidian-postgres \
       --file deploy/postgres/compose.production.yml config --quiet
     ```

   - Install `deploy/systemd/obsidian-postgres.service` only after the secret,
     backup destination and restore procedure are ready. The unit keeps
     Compose attached, waits for the container healthcheck and stops PostgreSQL
     with a two-minute grace period.
   - Never run `docker compose down --volumes`, `docker volume rm`, or otherwise
     recreate `obsidian-postgres-data` as an operational restart procedure.

3. Require all of the following before scheduling the window:

   - guard result `GO` and contiguous migrations;
   - the reconciler supports `--critical-invariants` and this runbook requires
     it for both rehearsal and the frozen production snapshot;
   - PostgreSQL 17 reachable only on the intended private/loopback interface;
   - separate migration, application, read-only admin and payout-worker roles;
   - backups and restore test for the PostgreSQL cluster;
   - current application commit/image recorded;
   - zero unresolved `processing` or `review` payout/referral intents;
   - no `sending` notification outbox rows;
   - enough disk for SQLite snapshot plus PostgreSQL backup;
   - an operator and a second reviewer present for the decision points.

4. Bootstrap the fixed role boundary before loading data. Run the
   cluster step as `postgres`, assign all four passwords only from separate
   root-owned secret files, then run schema migrations as the non-elevated
   owner. `bootstrap_roles.sql` contains no passwords.

   ```bash
   psql "$PG_CLUSTER_ADMIN_DSN" -v ON_ERROR_STOP=1 \
     -f deploy/postgres/bootstrap_roles.sql
   psql "$PG_TARGET_ADMIN_DSN" -v ON_ERROR_STOP=1 \
     -f deploy/postgres/prepare_database.sql
   ```

   `verify_runtime_privileges.py` must report 54 tables, 29 sequences, two
   functions and zero violations. The matrix is deliberately narrow:

   - `obsidian_app`: ordinary DML on all 54 tables and sequence `USAGE`, but no
     DDL, `TRUNCATE`, `REFERENCES`, `TRIGGER` or claim-function execution;
   - `obsidian_readonly`: `SELECT` on all 54 tables for Laravel, monitor and
     support-bot, with transaction-level read-only enforcement and no sequence,
     function or write rights;
   - `obsidian_payout`: `SELECT` on the two intent tables, updates to only the
     seven claim/result columns and execution of only the two claim functions;
   - `PUBLIC`: no database, schema, table, sequence or function privileges.

   The Laravel exchange connection is intentionally read-only at cutover.
   Review/support/block mutations must fail closed until they have a separately
   reviewed repository/API write boundary; the order payout action already
   calls the relay rather than writing an order directly.

5. Validate the content-addressed migration profile, apply only its exact
   `production-cutover` entries to an empty staging database, load a fresh
   SQLite backup, and require reconciliation exit 0. Repository migration 024
   is listed separately as post-cutover dormant; its production disposition is
   unknown until independently re-observed and it must not be selected by a
   wildcard:

   ```bash
   mapfile -t production_migrations < <(
     /opt/obsidian-exchange/relay-venv/bin/python \
       deploy/postgres/migration_profile.py --root "$PWD" \
       --profile production-cutover --paths
   )
   test "${#production_migrations[@]}" -eq 23 || exit 1
   for migration in "${production_migrations[@]}"; do
     psql "$PG_MIGRATOR_DSN" -v ON_ERROR_STOP=1 -f "$migration" || exit 1
   done
   psql "$PG_MIGRATOR_DSN" -v ON_ERROR_STOP=1 \
     -f deploy/postgres/runtime_privileges.sql
   /opt/obsidian-exchange/relay-venv/bin/python \
     deploy/postgres/verify_runtime_privileges.py \
       --postgres "$PG_MIGRATOR_DSN"
   /opt/obsidian-exchange/relay-venv/bin/python \
     deploy/postgres/load_sqlite_snapshot.py --sqlite "$SNAPSHOT" --postgres "$PG_MIGRATOR_DSN"
   /opt/obsidian-exchange/relay-venv/bin/python \
     deploy/postgres/reconcile_snapshot.py --sqlite "$SNAPSHOT" \
       --postgres "$PG_MIGRATOR_DSN" --critical-invariants
   ```

   In addition to all table hashes, the critical gate requires exact equality
   of both user-progress views:

   - the number of `sent`/`completed` orders for every `user_id`;
   - every `user_vip_volume` `user_id` and `total_rub`, compared at the
     PostgreSQL `NUMERIC(20,2)` storage scale. Never rebuild VIP volume from
     orders during cutover.

   The same report includes `referral_bonuses` row/value zero checks and the
   `paid`/`pending` order counts for operator visibility. These are explicitly
   informational and do not affect the semantic invariant status.

6. Prove a PostgreSQL 17 custom-format backup can be restored into a guarded
   scratch database. The tool refuses a target name without `restore_smoke`,
   `rehearsal`, `staging` or `contract`, refuses an existing target, never logs
   credentials, reapplies the ACL matrix and removes the scratch database. It
   compares SHA-256 table content, columns, constraints, indexes, sequence
   state, functions and the full privilege matrix:

   ```bash
   install -d -m 0700 /var/lib/obsidian-exchange/cutover
   /opt/obsidian-exchange/relay-venv/bin/python \
     deploy/postgres/backup_restore_smoke.py \
       --source "$PG_MIGRATOR_DSN" \
       --admin "$PG_CLUSTER_ADMIN_DSN" \
       --pg-dump deploy/postgres/container_pg_dump.sh \
       --pg-restore deploy/postgres/container_pg_restore.sh \
       --restore-database "obsidian_restore_smoke_$(date -u +%Y%m%d)" \
       --json-out /var/lib/obsidian-exchange/cutover/pg-restore-smoke.json
   ```

   The tracked wrappers use the PostgreSQL 17 client inside
   `obsidian-postgres`, because no host client is assumed. They connect through
   the container-local socket and never place a password in `docker exec`
   arguments. Set `OBSIDIAN_POSTGRES_CONTAINER` only for an isolated rehearsal.

   Require `status=match`, PostgreSQL/`pg_dump`/`pg_restore` major 17,
   inventory `54/29/2`, no differences and privilege status `match`.

`load_sqlite_snapshot.py` remains rehearsal-only and deliberately refuses
other names. Production uses the separate initial-empty loader below; never
weaken or reuse the rehearsal loader's destructive `TRUNCATE` path.

## Phase 1 — production write freeze and snapshot

Announce maintenance, reject new public writes at the edge, then stop all
services in the list above. Confirm every unit is inactive and no process has
the SQLite file open. If either check fails, abort.

Create a restricted directory and use SQLite's online backup command against
the now-quiescent database. Record hashes without printing database contents:

```bash
install -d -m 0700 /var/lib/obsidian-exchange/cutover
sqlite3 "$SQLITE" ".backup '$SNAPSHOT'"
chmod 0600 "$SNAPSHOT"
sqlite3 "$SNAPSHOT" 'PRAGMA quick_check;'
sha256sum "$SNAPSHOT" > /var/lib/obsidian-exchange/cutover/SHA256SUMS
```

Require `quick_check=ok`. Record queue counts for payout intents, referral
intents, reconciliation ledgers and both outboxes. Abort on any in-flight or
uncertain item; do not requeue it to make the check green.

## Phase 2 — load and reconcile

Apply migrations to the empty production database with the migration role.
Load the frozen snapshot only through the exact production guard. It requires
all seven writers inactive, no process holding the authoritative SQLite file,
the exact root-owned `0600` snapshot path, all 54 source/target tables and a
still-empty target under `ACCESS EXCLUSIVE` locks. It has no truncate/overwrite
mode and repeats the freeze/hash check immediately before commit:

```bash
/opt/obsidian-exchange/relay-venv/bin/python \
  deploy/postgres/load_production_snapshot.py \
    --sqlite /var/lib/obsidian-exchange/cutover/exchange-pre-cutover.db \
    --postgres "$PG_MIGRATOR_DSN" \
    --initial-empty-load \
    --confirm-frozen FROZEN_INITIAL_LOAD_OBSIDIAN_EXCHANGE \
    --json-out /var/lib/obsidian-exchange/cutover/production-load.json
```

Require `status=loaded`, `mode=frozen_initial_empty_load`, `tables=54` and an
empty `source_missing` list. Then immediately run
`reconcile_snapshot.py --critical-invariants` for all 54 tables and retain
its JSON report in the restricted cutover directory. Every table must report
`match`, `cutover_invariants.status` must be `match`, and both entries under
`cutover_invariants.critical` must be `match`. Review and record the
informational referral and `paid`/`pending` counts, but do not turn them into a
separate semantic blocker.

Before traffic, verify PostgreSQL constraints, serial sequences, application
role grants, connection limits and statement/lock timeouts. Run repository
contract smoke tests using non-production test rows in a separate schema or
database—not in the loaded production schema.

Reapply `runtime_privileges.sql` after the final restore and retain a fresh
zero-violation `verify_runtime_privileges.py` JSON report. New database objects
receive no automatic runtime rights; every future migration must update and
re-run this explicit matrix.

Decision point A: if any load, hash, critical user-progress invariant, schema,
grant or smoke check fails, drop the unpublished target database if policy
permits, return to Phase 4 rollback, and keep SQLite authoritative.

## Phase 3 — configure and start

Write `DATABASE_URL=$PG_DSN` and all reviewed gates below to the appropriate
root-owned `/etc/obsidian-exchange/*.env` files using an atomic replacement;
keep permissions `0600`:

```text
ADDRESS_BOOK_POSTGRES_ENABLED=1
ADMIN_CONFIG_POSTGRES_ENABLED=1
ALERT_POSTGRES_ENABLED=1
BOT_ORDER_POSTGRES_ENABLED=1
BOT_NOTIFICATION_POSTGRES_ENABLED=1
DCA_POSTGRES_ENABLED=1
ENGAGEMENT_POSTGRES_ENABLED=1
GIFT_POSTGRES_ENABLED=1
LEGACY_RUNTIME_POSTGRES_ENABLED=1
LIMIT_ORDER_POSTGRES_ENABLED=1
OPS_POSTGRES_ENABLED=1
OPERATIONAL_READ_POSTGRES_ENABLED=1
ORDER_POSTGRES_ENABLED=1
ORDER_READ_POSTGRES_ENABLED=1
ORDER_LIFECYCLE_POSTGRES_ENABLED=1
ORDER_WORKFLOW_POSTGRES_ENABLED=1
PAYMENT_POSTGRES_ENABLED=1
PAYMENT_SESSION_POSTGRES_ENABLED=1
PAYOUT_POSTGRES_ENABLED=1
PROMO_ADMIN_POSTGRES_ENABLED=1
PROVIDER_HEALTH_POSTGRES_ENABLED=1
RECEIPT_POSTGRES_ENABLED=1
RECONCILIATION_POSTGRES_ENABLED=1
REPORTING_POSTGRES_ENABLED=1
SELL_ORDER_POSTGRES_ENABLED=1
SELL_SETTLEMENT_POSTGRES_ENABLED=1
SHADOW_PAYOUT_POSTGRES_ENABLED=1
STATUS_NOTIFICATION_POSTGRES_ENABLED=1
SUPPORT_POSTGRES_ENABLED=1
SWAP_POSTGRES_ENABLED=1
USER_PROFILE_POSTGRES_ENABLED=1
WALLET_STORE_POSTGRES_ENABLED=1
WEB_AUTH_POSTGRES_ENABLED=1
```

For Laravel set `EXCHANGE_DB_CONNECTION=pgsql` and
`EXCHANGE_DATABASE_URL` to its read-only PostgreSQL DSN. Clear Laravel's config
cache before starting it.

The installed units have `runtime-paths.conf` drop-ins that reset the complete
`EnvironmentFile` list. PostgreSQL activation must therefore use a
lexicographically later `zz-postgres.conf`; a plain `postgres.conf` is silently
discarded by that reset and causes SQLite split-brain. Before opening ingress,
inspect `/proc/$MainPID/environ` for the expected key names (never values) and
require `fuser /var/lib/obsidian-exchange/exchange.db` to return no process.

Start read-only/admin health surfaces first, then relay and bot with the edge
still closed. Verify startup logs, public read endpoints, authentication and
one rollback-safe read for every repository. Keep the payout worker stopped.

Decision point B (last simple rollback point): if any check fails, start no
writers and execute Phase 4. If all checks pass, open ingress and start the
payout worker last. Record the UTC timestamp of the first accepted PostgreSQL
write; after that timestamp simple SQLite rollback is forbidden.

For the first real payout, observe the complete sequence `pending → processing
→ succeeded → sent` and outbox delivery. Any `processing`, `review`, ambiguous
TXID, or `sending` state requires manual reconciliation, never blind retry.

## Phase 4 — simple rollback before any PostgreSQL write

Close ingress and stop all listed services. Atomically restore the previous env
files (with no `DATABASE_URL`, no PostgreSQL gates, Laravel exchange driver
`sqlite`), clear Laravel config cache, and verify the original SQLite file hash
and `PRAGMA quick_check`. Restart relay/bot read paths first, then admin,
notifier, monitor and support bot; start the payout worker last. Reopen ingress
only after health checks and queue counts match the preflight record.

## Rollback after PostgreSQL has accepted writes

There is intentionally no one-command rollback. SQLite no longer contains the
new transactions. Keep ingress closed and application services stopped;
preserve both databases and logs; determine the last committed PostgreSQL
transaction; then either repair forward on PostgreSQL or execute a separately
reviewed reverse reconciliation/import. Never copy the old SQLite snapshot over
live state and never dual-write to catch it up.

## Acceptance and observation

For at least 24 hours monitor service restarts, PostgreSQL locks/connections,
payment transitions, both payout intent queues, both reconciliation ledgers,
notification outboxes, provider health and error-rate deltas. Keep the SQLite
snapshot read-only for the agreed rollback-retention period. Delete it only
after a PostgreSQL backup restore has been proven and the retention decision is
recorded.
