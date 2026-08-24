# Database migration status

Production remains on SQLite. Two boundary passes reduced direct SQLite
openers in tracked active Python scope from 41 files to zero. Three tracked
source occurrences remain under an exact test-enforced allowlist: the
`db_runtime` implementation itself and two inactive legacy/one-shot files.
Untracked `gold_*`, venv and compatibility copies are excluded from release
inventory. Remaining
SQLite-specific SQL (`?`, `INSERT OR IGNORE`,
`BEGIN IMMEDIATE`, `last_insert_rowid()`, PRAGMA and `executescript`). Changing
only the connection string would corrupt the operational contract.

The extracted boundary is `relay/core/db_runtime.py`. It is used by the payout
worker, Telegram bot, FastAPI relay/auth, payout queue/discovery, notifier,
monitor, conversion/dispute watchers and alert throttling. It rejects
PostgreSQL configuration fail-closed
until a PostgreSQL store is selected explicitly. The PostgreSQL payout schema
and atomic `FOR UPDATE SKIP LOCKED` claim functions live in
`deploy/postgres/001_payout_core.sql`.

Migration order:

1. Payout worker/store: complete. Worker uses a stable repository contract;
   SQLite is deployed and PostgreSQL is verified against PostgreSQL 17.
   PostgreSQL activation additionally requires `PAYOUT_POSTGRES_ENABLED`.
2. Order/referral reconciliation and notification outbox: repository contract
   implemented and verified against SQLite and PostgreSQL 17. PostgreSQL
   selection is fail-closed and requires both `PAYOUT_POSTGRES_ENABLED` and
   `RECONCILIATION_POSTGRES_ENABLED`; production remains on SQLite.
3. FastAPI and Telegram write paths behind repositories: in progress. Web
   dashboard identities, sessions, password/TOTP mutations and Telegram linking
   use `web_auth_store`; PostgreSQL rehearsal requires the separate
   `WEB_AUTH_POSTGRES_ENABLED` gate. Order/payment state writers remain SQLite
   SQL and must move as whole transactional workflows. The two ordinary
   FastAPI buy-order creation paths now share `order_creation_store`, including
   the quote-in-the-same-INSERT invariant and Mini App recent-order dedup. Its
   PostgreSQL SQL is contract-tested but `ORDER_POSTGRES_ENABLED` must remain
   off until the canonical orders/payment schema is migrated.
   Verified payment confirmation is now behind `payment_transition_store` for
   all active FastAPI callbacks/polls and the bot TRC-20 watcher. One
   transaction performs `pending -> paid`, closes the matching active payment
   session, appends provider-class evidence, and inserts a unique customer
   notification outbox item. PostgreSQL activation requires
   `PAYMENT_POSTGRES_ENABLED` and remains disabled.
   The primary Telegram buy-order path and rate-lock lifecycle now use
   `bot_order_store`: replacing a lock, reading a live lock, creating the order,
   consuming the lock and falling back after a lost race are transactionally
   defined. PostgreSQL activation requires `BOT_ORDER_POSTGRES_ENABLED`.
   Promo capacity/one-use claiming is part of that same order transaction. If
   the last use is won by another request, the losing order is committed with
   its precomputed no-promo quote; `promo_uses` and `uses_count` cannot diverge.
   Gift issue and redemption use `gift_store`; payment confirmation promotes
   the linked voucher `pending -> paid` in the same transaction. Redemption is
   a single-winner `paid -> redeemed` claim plus paid recipient order.
   DCA schedule creation/cancellation and due execution use `dca_store`.
   `expected_next_run` is a compare-and-swap token: only one runner creates the
   order and advances `runs_total/next_run`. PostgreSQL implementation remains.
   Limit-order create/cancel/expire/trigger uses `limit_order_store`; expiry is
   the CAS token for one atomic `active -> triggered` plus quoted order.
4. Read-only reporting, monitoring and admin resources: repository extraction
   is complete for the identified residual tables.
   Customer address-book history/notes and payout-guard shadow decisions now
   use dedicated SQLite/PostgreSQL repositories. PostgreSQL selection is
   fail-closed behind `ADDRESS_BOOK_POSTGRES_ENABLED` and
   `SHADOW_PAYOUT_POSTGRES_ENABLED`; both real-PostgreSQL contracts pass.
   Physical payout-queue monitoring and risk-event access have PostgreSQL
   contracts. The post-change production snapshot rehearsal matches all 53
   migration tables by row count and canonical SHA-256.
5. Full authoritative cutover is still `NO-GO`: active runtime modules retain
   SQLite-only calls outside repositories. `cutover_preflight.py` inventories
   these paths and must report `GO` before the separately approved cutover.
   The operational sequence and rollback boundary are documented in
   `docs/postgresql-cutover-runbook.md`.

The first post-runbook cleanup moved monitor order/conversion/daily aggregates
into `reporting_store` and the legacy paid/sent notifier ledger plus gift
promotion into `status_notification_store`. PostgreSQL selection for the latter
is fail-closed behind `STATUS_NOTIFICATION_POSTGRES_ENABLED`. The static guard
now reports 19, rather than 21, active SQLite-only runtime modules.

The next cleanup moved receipt session/fraud reads and payout guard/circuit
metrics into `receipt_store` and `ops_store`; the unused direct dispute-watch
connection was removed. Existing `RECEIPT_POSTGRES_ENABLED` and
`OPS_POSTGRES_ENABLED` gates cover these paths. The static guard now reports 15
active SQLite-only runtime modules.

The operational read block is also complete: conversion/receipt watches,
staff/client payout queue, client trust counts and curated offering reserves use
`operational_read_store`, gated by `OPERATIONAL_READ_POSTGRES_ENABLED`.
Production old/new SQLite outputs matched exactly and SQLite/PostgreSQL 17
contracts pass. The static guard now reports 11 active SQLite-only modules.

RSPay client anti-fraud counters now use the same operational read repository,
reducing the static cutover guard to 10 modules. This code is deployed on the
SQLite path; RSPay itself remains disabled pending valid multi-cabinet API
credentials and successful signed read-only probes.

Never enable `DATABASE_URL=postgresql://...` in production until stages 1–4
have dialect contract tests. Never dual-write money state from application
code; use one authoritative transaction and an outbox/change stream.

The support bot uses two explicit roles: its reads from the exchange ledger use
the runtime boundary, while `support.db` uses `auxiliary_sqlite_connect` and is
not redirected by an exchange `DATABASE_URL` migration.
