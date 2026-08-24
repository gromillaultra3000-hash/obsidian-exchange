# E0.3 environment and database capability manifests

The authoritative repository-only artifacts are
`e0-3-unit-environment-allowlist.v1.json` and
`e0-3-db-capability-manifest.v1.json`. They contain names and capability metadata
only, authorize no production mutation, and keep E0.3 `IN_PROGRESS`.

The environment artifact now has a separate observed exact configured-name
snapshot in `e0-3-observed-environment-names.v1.json`. It covers the closed
systemd unit/drop-in and EnvironmentFile scope, not manager/PAM-injected process
variables. Desired authorization/target partitioning remains incomplete and
every such mapping stays `NO_GO`. The DB manifest deliberately
assesses only notifier and dormant relay-shadow: notifier can target three bounded
operations, while relay-shadow must have no DB credential until it stops launching
the full Relay application. A PostgreSQL 17 disposable rehearsal proves the three
proposal-only notifier functions plus direct DML, sequence, DDL and TEMP denials;
it does not authorize or claim production deployment. Relay and bot remain
explicitly unassessed. Twelve-caller single-winner tests and mid-function plus
caller-side fault injection prove atomic rollback for the proposal; relay-shadow
NOLOGIN/credential/membership/CONNECT/object denial is also proven in disposable
PostgreSQL. Ambient `PUBLIC CONNECT` or function `EXECUTE` makes the proposal
fail closed. The current full Relay shadow entrypoint remains `NO_GO` and is not
authorized to start.

The Relay relation-level graph is now generated from the authoritative FastAPI
AST and all imported repository modules. It binds 17 factories, 71 caller edges
and 23 relation objects; every imported repository is called, every edge has SQL
evidence, and the entrypoint has no direct SQL/connection site. This relation
graph alone is not least-privilege ACL evidence, and the bot graph is unassessed.

The follow-up PostgreSQL writer matrix now classifies all 26 unique write
methods. It records exact mutated columns (or explicit row deletion), transition
guards, locking/CAS/idempotency behavior and effect class, and is bound to the
canonical graph plus SHA-256 of all eleven writer repository files. It confirms
the current broad role is not an acceptable target ACL. No function/grant is
designed or deployed by the matrix.

The proposal-only ACL plan partitions all 26 writers into six ordered packages
and requires one reviewed `SECURITY DEFINER` function per writer, a NOLOGIN
owner and zero direct DML/sequence grants. It deliberately remains
`IN_PROGRESS`: all read columns and 43 current SQL signatures/return shapes are inventoried,
and the Relay connection budget is measured at nine runtime slots with proposed
`CONNECTION LIMIT 12`. The role envelope passed a disposable PostgreSQL 17
rehearsal with direct-access denials, concurrency and rollback evidence. All 43
read bodies and all 26 R1–R6 writer bodies are now rehearsed. This closes the
Relay function-body subplan only; no deployed role or SQL migration is claimed.

The first packages are now rehearsed: P7 runtime metadata, all four P1 public
aggregates, all twelve P2 customer-scoped reads, and three securely correlated
P3, P6, P4, five P5A reads and all six P5B embedded-writer reads (43/43 reads). Five order-id-only Relay paths were replaced with
atomic owner-or-session-token correlation; P3 is fully rehearsed at eight current methods.
Metadata validation uses `pg_catalog` because
`information_schema.columns` is privilege-filtered; its NOLOGIN owner retains
zero business-table privileges. P1 functions proved UTC semantics, a 64-row
reserve cap, exact owner-column grants and zero `PUBLIC` execution.
P2 proves 100-row histories, latest-500 support messages, cross-owner exclusion
and sensitive sell-destination returns restricted to the supplied owner. Receipt
lookup now joins `orders` and checks Telegram/web ownership inside the function;
the prior array-only signature could not enforce that boundary.

The exact Relay read matrix covers all 43 methods with `SELECT`, including
predicate/join/order/lock columns and writer read dependencies. It is bound to
sixteen repository hashes and the two schema migrations used to expand wildcard
results. Reachable `SELECT`/`RETURNING` wildcards are closed; broad grants remain
forbidden, and sensitive
columns are partitioned by purpose.
Seven `COUNT(*)` methods are separately marked because row-count authority is
not a normal column grant; each must use a non-null key count or remain inside a
bounded owner function.
