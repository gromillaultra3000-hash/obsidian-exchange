# E4 unified action UX contracts

Status: design-only, non-executing foundation.

`wallet-action-preview.v1` is the first E4 boundary. Before any confirmation it
content-binds the selected private or external-CEX lane, BUY/SELL direction,
executor, custody before/during/after, KYC requirement and responsible party,
spend/receive amounts, every fee item and derived total, quote lifetime, bounded
risks and irreversibility.

The private lane names ObsidianExchange, no KYC and destination-wallet/bank
custody. The verified lane names the external CEX, its KYC and continuous CEX
custody; it remains `PLANNED`. The two contracts cannot be relabelled into one
another.

A preview is never confirmation: `confirmationAvailable:false`,
`executionEffect:NONE` and `actionAllowed:false` are invariant. Amounts are
canonical decimal strings, fee totals are derived, quote lifetime is at most 15
minutes and hidden fee types or mismatched asset direction fail closed.

Next E4 slice: a separate acknowledgement/challenge contract that requires the
user to acknowledge executor, custody, KYC, total fees and irreversibility for
the exact unexpired preview. It must use a second deliberate interaction and
still produce no money intent or execution.

`wallet-action-acknowledgement-challenge.v1` binds the exact preview and requires
five ordered acknowledgements: executor, custody, KYC, total fees and
irreversibility. It expires at the earlier of two minutes or the quote expiry,
requires at least 750 ms deliberation and a distinct second interaction.

`wallet-action-acknowledgement-receipt.v1` records the exact challenge and all
five acknowledgements. Missing/reordered acknowledgement, reused interaction,
short deliberation or expiry fails closed. The external-CEX lane remains
`LANE_NOT_AVAILABLE` while planned. Even an acknowledged private preview only
sets `confirmationEligible:true`; `moneyIntentAllowed`, execution effect and
action permission remain false.

Next E4 slice: a pure confirmation-intent draft that binds preview and
acknowledgement, uses a new idempotency key and explicit destination/account
summary, but remains unpersisted and non-executing until the existing money
workflow performs its own server-side authorization and state checks.

`wallet-action-confirmation-draft.v1` binds the exact acknowledged preview,
executor, lane, side, a hashed idempotency key and a minimized destination
summary. BUY requires a network plus wallet-address fingerprint; SELL requires a
bank-account fingerprint and forbids a crypto network. Raw destinations and
bank details are outside the contract.

The draft must be created after acknowledgement and before quote expiry. It is
always `DRAFT_ONLY`, unpersisted and explicitly lacks server authentication and
server state checks. It cannot be built from the planned external-CEX lane or a
NO_GO acknowledgement. Exact retry is stable, while key or destination drift
changes the draft identity. It still permits no money intent or execution.

Next E4 slice: a server-side adapter contract that maps only a validated private
draft into the existing buy/sell workflow after independently rechecking user
authentication, quote freshness, destination ownership/validation and current
provider availability. Keep this adapter dormant until route-level authorization
and persistence tests exist.

`private-action-server-check-evidence.v1` records one secret-free, raw-
destination-free result for the exact draft and server-derived principal. Six
independent checks cover authentication, quote freshness, destination validity,
principal authorization for that destination, provider availability and risk
policy. Evidence is bounded to 30 seconds with one second future skew.

`private-action-server-assessment.v1` requires one unique fresh PASS for every
check and maps BUY/SELL only to the names of the existing order-creation
workflows. Even a positive `SERVER_CHECKS_PASSED_OFFLINE` remains route-
disconnected, unpersisted and unable to create a money intent or action. Stale,
future, mixed-principal, duplicated, unavailable or failed evidence is NO_GO or
invalid.

Next E4 slice: repository-level idempotency reservation for the exact assessment
and draft, with rollback/fault/concurrency contracts. Do not connect HTTP/UI or
invoke existing money workflows until reservation and adapter authorization are
atomic at the server boundary.

`private-action-reservation-request.v1` content-binds the exact draft and
positive server assessment, principal, hashed idempotency key, workflow mapping,
payload hash and a maximum five-minute reservation window. It contains no raw
destination or execution permission.

The SQLite/PostgreSQL reservation repository has unique boundaries on both
`draft_id` and `(principal_ref,idempotency_key_sha256)`. Exact retry returns the
same reservation; any assessment, payload, workflow or expiry drift conflicts.
Expiry never frees the key for silent reuse. SQLite uses `BEGIN IMMEDIATE` and
fault injection proves an exception after INSERT rolls back completely; parallel
claims have one insert and one exact replay. PostgreSQL uses untargeted
`ON CONFLICT DO NOTHING` so either uniqueness boundary is safe. The rehearsal
schema is test-only and has not been added to production migrations.

Next E4 slice: run the PostgreSQL repository contract in a disposable isolated
PostgreSQL 17 fixture, including concurrent exact retry and drift conflict. Keep
production schema, flags, routes and workflows unchanged.

The atomic handoff store closes the gap between reservation and order creation.
Inside one database transaction it validates the exact positive assessment,
server-derived actor ID, preview amounts and raw-destination fingerprint; inserts
the reservation; creates either the canonical pending `orders` BUY row or
canonical pending `sell_orders` SELL row; then records immutable result kind/id
and commits. Exact retry returns that order. An existing incomplete or drifting
reservation conflicts rather than invoking a workflow.

The draft now embeds canonical preview amounts and quote expiry, allowing the
store to verify SQL payload without trusting a caller-supplied preview summary.
Faults after order INSERT or immediately before commit roll back both order and
reservation. Parallel handoff creates one order and returns one replay. Actor,
amount or raw-destination drift fails before the transaction.

The combined BUY/SELL handoff passed a disposable PostgreSQL 17 fixture with a
loopback-only port and no volume: parallel BUY produced one order plus one exact
replay, SELL exact replay preserved one result, and an injected failure after
order INSERT rolled back both tables. The fixture was removed afterward.

Next E4 slice: a test-only adapter invocation boundary that can call this store
only after revalidating the entire preview→acknowledgement→draft→server-
assessment→reservation chain. It must expose no HTTP route and must return a
bounded result without raw destination or payout details. Production schema,
flags and workflows remain unchanged.

`private-action-test-invocation-result.v1` is produced only through an explicit
`E4TestOnlyHandoffStore` fixture wrapper after the adapter revalidates the complete
chain and rebuilds the exact reservation request. The wrapper is an isolation
marker, not production authorization. A created or replayed result exposes only
kind/id and safe content IDs; raw wallet/bank/deposit fields are never returned.
Store timeout/error is normalized to bounded NO_GO without exception text.

The result honestly marks a created row as `TEST_DATABASE_WRITE`, while keeping
production invocation, route connection and action permission false. A non-test
store or any pre-store chain tamper fails before `handoff` is called. The
production-capable handoff stores do not expose a boolean test switch; the
invoker requires the explicit `E4TestOnlyHandoffStore` fixture wrapper. This
wrapper is isolation only, not production authorization. The module contains no
HTTP, provider, secret or logging surface.

Next E4 slice: freeze the production migration/ACL/feature-gate design and a
route-level authorization contract without applying or enabling either. The
test-only adapter must not be reused as a production endpoint.

The proposed migration lives outside the active migration sequence. Its table
allows only immutable `reserved` rows and the single `reserved → committed`
transition; a trigger rejects DELETE, immutable-field changes, repeated updates,
workflow/result-kind mismatch and result IDs missing from the correct BUY/SELL
table. The separate ACL proposal must run after the base ACL and gives the app
only SELECT/INSERT plus UPDATE of state/result kind/result ID. Read-only and
payout roles receive no access. Neither proposal has been applied.

`private-action-route-authorization.v1` binds the exact assessment/reservation,
server-derived web/actor/principal identities, hashed session and CSRF evidence,
five-minute authentication freshness and reservation expiry. Handoff and route
feature gates are independent and both default false. Even synthetic both-true
only produces `PRECONDITIONS_SATISFIED_OFFLINE`; migration, ACL, production
invocation, route connection and action remain false.

Next E4 slice: execute the proposal migration and ACL verifier only in a
disposable PostgreSQL 17 fixture, proving allowed insert/commit and denial of
immutable update, delete, invalid result, readonly and payout access. Keep the
active production migration sequence and runtime environment unchanged.

The proposal passed that isolated PostgreSQL 17 rehearsal. The app could insert
a reserved row and commit it to an existing BUY result. Column ACL/trigger checks
denied immutable-field update, repeated committed-row update, DELETE and a
missing result ID; read-only and payout roles could not read the table. The
fixture modeled the already-existing app SELECT rights on canonical order tables
needed by the validation trigger, then was removed without a volume.

Next E4 slice: define static production preflight requirements for promoting the
proposal into the active sequence: fresh full snapshot rehearsal, updated table/
ACL inventory, rollback boundary, both environment gates explicitly false, and
route absence. Do not promote or apply the migration yet.

`e4-promotion-preflight.v1` now freezes those requirements as a pure,
content-hashed offline contract. It requires fresh (at most 24-hour) snapshot,
table/ACL inventory and rollback-plan digests; both gates explicitly false; the
future route and active migration absent; and both proposal files present. Every
check independently blocks review. A complete synthetic proof means only
`PROMOTION_REVIEW_READY_OFFLINE`: promotion/application, ACL application, route
connection, feature-gate mutation and money action remain false with
`executionEffect=NONE`.

The workspace assertion still finds `025` only under `proposals/`, and finds no
future confirm route or E4 gates in the relay entrypoint/systemd template. No
production evidence has been collected by this pure contract, so it is not a
production GO record and does not authorize promotion.

Next E4 slice: define the read-only evidence collector and frozen manifest for a
fresh full-snapshot rehearsal. It must operate on an isolated PostgreSQL target,
record exact proposal/table/ACL/rollback digests, redact connection material and
emit NO-GO unless the runtime route and both feature gates remain absent/false.
Do not promote or apply the proposal.

The frozen `e4-full-snapshot-rehearsal-manifest.v1` now content-binds the two
proposal files and rollback runbook, fixes the target to a disposable isolated
PostgreSQL instance, and forbids production networking, credentials and writes.
The pure read-only normalizer accepts only a strict, secret-free observation;
it records target, snapshot, table and ACL fingerprints without accepting a DSN.
Artifact drift is rejected against the manifest. Production contact, any write,
connection material, a non-isolated target, either non-false feature gate, a
present confirm route or an active `025` migration yields NO_GO.

Even a complete synthetic observation produces only
`PROMOTION_REVIEW_READY_OFFLINE` with no promotion, action or execution effect.
No rehearsal has been run and this normalizer does not probe a database.

Next E4 slice: define a separately authorized disposable rehearsal runner that
can produce these observations from a fresh full snapshot with read-only
post-load inspection and guaranteed teardown. Do not point it at production or
promote/apply `025`.

`e4-full-snapshot-rehearsal-runner-plan.v1` now freezes that runner workflow
without executing it. It accepts only a pre-existing encrypted immutable
snapshot copy, never contacts the production database, and fixes one disposable
isolated PostgreSQL target invocation. Eight preconditions require separate
owner approval, verified target absence/isolation, no production route or
credentials, exact snapshot/manifest digests and a verified teardown target.

The only bounded fixture writes are target creation and snapshot loading.
Post-load write capability is revoked before full-snapshot comparison and table,
ACL, route/gate and migration-absence measurements. Applying either `025`
proposal is forbidden. Evidence normalization precedes mandatory destruction of
the target and staged snapshot, followed by a final absence check; no step can
retry automatically.

The plan itself has no command, database, filesystem, network or credential
surface. Owner approval is required but absent, execution remains unauthorized,
and promotion/action/effect remain false.

Next E4 slice: freeze exact target-bound precondition evidence and a short-lived,
single-invocation owner-approval receipt for this plan. General continuation is
not approval to create a snapshot or disposable target.

`e4-rehearsal-runner-precondition-evidence.v1` now binds every required check to
the exact plan, opaque disposable-target reference and fingerprint, and encrypted
snapshot digest. Evidence is secret/connection-free, valid for at most ten
minutes and tolerates only one second of future clock skew.

The separate `e4-rehearsal-runner-owner-approval.v1` binds the same plan, target
and snapshot for at most fifteen minutes and exactly one invocation. Its scope
forbids production database/network contact, credentials, proposal application,
persistent targets, automatic retry, promotion and money action.

`e4-rehearsal-runner-authorization-receipt.v1` requires one unique current PASS
for all eight preconditions plus the exact current approval. Missing, duplicated,
failed, stale/future or mixed-binding evidence fails closed. A complete synthetic
set is only `ELIGIBLE` for the frozen isolated rehearsal; the receipt itself has
no execution effect. No real owner approval or authorization receipt exists.

Next E4 execution remains blocked until the owner separately names and approves
one exact disposable target and snapshot digest. Continue other offline roadmap
work rather than treating ordinary continuation as operational approval.

The owner later gave explicit conversational permission to use the running
`obsidian-postgres` source for one read-only snapshot acquisition. A custom
format dump of `obsidian_exchange` was encrypted with a newly generated
ephemeral key (the previously posted key was not used), loaded into a fresh
PostgreSQL 17 target with network `none`, read-only root, tmpfs-only data and
no published ports, and the target plus staged snapshot were destroyed after
inspection. `pg_restore` completed successfully; all 54 tables were present,
the proposed `025` objects were absent in both source and fixture, and no
production DML, migration, restart or route wiring occurred.

The evidence is deliberately `NO_GO_NON_AUTHORITATIVE` in
`docs/e4-full-snapshot-rehearsal.v1.json`: the live source changed after the
snapshot point, fixture ACLs differ by design because owner/privilege restore
was disabled, the operation has no machine-readable single-use authorization
receipt, and source contact occurred for snapshot acquisition. This is a
completed disposable restore/teardown diagnostic, not promotion evidence and
does not authorize applying `025` or connecting an action route.

The next code-bearing slice added
`relay/core/e4_rehearsal_runner_boundary.py`. It accepts only an `ELIGIBLE`
target-bound receipt and deterministic target-spec fingerprint, emits a pinned
PostgreSQL image with network `none`, read-only root, tmpfs-only data, no ports
or persistent volume, and requires final target/snapshot absence. Snapshot and
key inputs are opaque references rather than paths or values; DSNs,
production markers and secret-like references fail closed. The module is
deliberately non-executing and has no Docker, database, environment, HTTP or
secret-reading surface. Seven boundary tests pass; this does not authorize an
executor, migration, route or production action. Review:
`docs/e4-rehearsal-runner-boundary-review.v1.md`.
