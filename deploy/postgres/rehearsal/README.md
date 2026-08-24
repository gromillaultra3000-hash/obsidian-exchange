# 064B EXPAND disposable rehearsal bundle

This directory is a non-production rehearsal artifact for `E0/E0.3/B5.3/064B`.
It is intentionally separate from `deploy/postgres/proposals/`: the proposal
files mix EXPAND, backfill, producer/dispatcher fencing, governance, and
cutover concerns and are not an ordered 064B migration.

The bundle does only the additive EXPAND slice on a disposable clone of the
legacy `023_bot_notification_jobs` schema:

- adds nullable `lifecycle_version` and v2 job columns;
- adds `NOT VALID` conditional checks, leaving the legacy state check intact;
- adds token/evidence tables and two versioned, ungranted functions;
- creates the new indexes with `CONCURRENTLY` outside a transaction;
- verifies that old-column inserts and the old pending→sending→sent DML still
  work while v2 columns remain `NULL`;
- rolls back only before any v2 submit/attempt/evidence exists.

`064C`/`064D` producer and dispatcher fences, recipient backfill, governance,
manual/quarantine states, grants, credentials, and production authority are
deliberately absent. The field names and function surface remain a reviewable
064B candidate, not an accepted production contract. Do not run these files
against a production database.
