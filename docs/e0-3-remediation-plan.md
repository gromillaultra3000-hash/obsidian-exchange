# E0.3 remediation plan

The machine-readable authority for this bounded design slice is
`docs/e0-3-remediation-plan.v1.json`.

The owner-approved accountability map is now operationally bound to two
separate workstreams: splitting shared credential bundles and narrowing shared
PostgreSQL writer privileges. They are independently planable and may become
independently deployable/rollbackable only after their gates pass. Neither design
grants standing authority to copy or rotate secrets, change production ACLs,
restart services or deploy.

The secret migration is family-by-family. Unknown provider mutation or revoke
state disables the affected connector and moves it to reconciliation/MANUAL;
there is no blind retry. The database migration introduces one login role per
process and narrow transition functions, rehearses denials first, migrates
shadow/notifier before Relay and bot, and retains `obsidian_app` only as a
time-bounded rollback path before final `NOLOGIN`/revocation.

E0.3 remains `IN_PROGRESS`. Names-only environment observation and the first
disposable PostgreSQL 17 notifier ACL/function concurrency/fault rehearsal are
complete. Relay-shadow NOLOGIN/connection/money-SQL denials are also rehearsed,
including fail-closed ambient `PUBLIC` privilege tests. The next repository-only
slice is the exact Relay caller-to-repository/database capability graph;
production ACL, role, function and service changes remain unauthorized.
That static relation graph is complete and source-hash bound. The next slice is
exact Relay writer-column and transition-invariant classification before any ACL
proposal; the bot graph follows afterward.
That classification is now complete for all 26 PostgreSQL writer methods and is
source-hash bound. The next repository-only slice is a target Relay ACL/function
design derived from the matrix; it must remain proposal-only until a disposable
positive/adversarial rehearsal succeeds.
The writer authorization partition is now frozen with zero direct DML, but the
complete ACL correctly remains blocked on exact read columns, SQL signatures and
a measured connection limit. The next slice is the Relay read-method column
matrix; no SQL proposal or rehearsal is valid before it.
The 43-method read matrix is now complete. The immediate repository slice is to
replace two `payment_sessions` `SELECT *` calls and one payment-outbox
`RETURNING o.*` with the frozen explicit lists. Read-purpose grant partitioning
follows; table-wide SELECT remains forbidden.
Seven `COUNT(*)` sites are also explicit debt and cannot be silently treated as
covered by a neighboring column grant.
