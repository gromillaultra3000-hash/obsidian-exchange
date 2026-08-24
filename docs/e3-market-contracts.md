# E3 market-data contracts

Status: frozen keyless/offline foundation. No runtime route, credential,
network call, feature flag, persistence or trade execution is introduced.

`market-depth-snapshot.v1` normalizes one CEX order-book observation. Prices
and amounts use plain decimal strings with at most 18 fractional digits. Bids
must be strictly descending, asks strictly ascending, each side contains
1–200 unique price levels, and a crossed or locked book is rejected. The
content-addressed `snapshotId` covers source, market, observation time, all
levels and the non-executing safety fields.

`slippage-estimate.v1` deterministically walks a validated snapshot for a BUY
whose input is quote currency or a SELL whose input is base currency. It
reports gross/net output, fee, average price, midpoint slippage and levels
used. Insufficient depth is an error rather than a partial-fill promise.

Both contracts are pure projections and always contain:

- `executionEffect: NONE`;
- `actionAllowed: false`;
- for estimates, `projectionOnly: true`.

They are not order quotes, intents, approvals or evidence that an exchange
would accept a trade.

`market-source-comparison.v1` compares 2–8 unique validated snapshots for one
market at an explicit assessment time. A snapshot is `FRESH` through 5 seconds
old, `FUTURE` beyond 1 second of positive clock skew, and otherwise `STALE`.
Only fresh midpoints participate in the deterministic median reference. Fewer
than two fresh sources yields `INSUFFICIENT_FRESH_SOURCES`; maximum midpoint
deviation above 100 bps yields `DIVERGENT`; otherwise the result is
`CONSISTENT`. Stale/future/missing data is never represented as a zero price.

The comparison is content-addressed, ordering-independent and remains a pure
projection with `executionEffect:NONE` and `actionAllowed:false`. It does not
select a venue, quote a trade or authorize submission.

`paper-trade-ledger.v1` is an immutable synthetic balance snapshot with a
content-addressed genesis identity and a hash-chained sequence of
`paper-trade-entry.v1` records. Every transition recomputes the depth estimate,
debits the input asset, credits only net output after fees and returns a new
ledger value. Both assets must already exist and insufficient synthetic balance
fails closed.

Idempotency keys are stored only as account-bound hashes. Exact retry returns
the unchanged ledger; key reuse with different trade parameters is rejected.
Validation replays every balance transition from genesis, checks fee arithmetic,
request binding, entry hashes and the final ledger hash, so consistently
re-hashed balance forgery also fails. JSON round-trip preserves replay safety.
The ledger remains `simulationOnly:true`, `executionEffect:NONE` and
`actionAllowed:false`; it performs no I/O and is not the future persisted trade
intent or execution ledger.

`paper-risk-policy.v1` binds one synthetic account to 1–16 allowed markets and
immutable maximum order quote notional, UTC-day quote notional, trade count and
drawdown. It also freezes market age at 5 seconds with 1 second of tolerated
future clock skew. Decimal and integer boundaries are inclusive and malformed
usage/day inputs fail before a decision is produced.

`paper-risk-decision.v1` binds the exact ledger hash, market snapshot, policy,
fee, side, amount and account-scoped idempotency hash. BUY notional is quote
input; SELL notional is projected gross quote output. Ordered checks cover
account, symbol, freshness, order/day notional, day count, drawdown and both
paper assets/balance. Any failed check yields `HOLD`; all passing checks yield
only `PAPER_ALLOW`. Both outcomes remain `paperOnly:true`,
`executionEffect:NONE` and `actionAllowed:false`.

`paper-intent-state.v1` is a persisted-intent-shaped immutable projection with
hash-chained events and exact bindings to risk decision, ledger, snapshot,
policy, side, amount, fee and account-scoped idempotency hash. A `PAPER_ALLOW`
decision opens `READY`; a blocked decision opens terminal `HOLD`. Only `READY`
can project a paper fill, producing `FILLED` and an expected ledger hash.

Reconciliation independently validates an observed paper ledger. Exact hash
agreement produces terminal `RECONCILED`; mismatch produces terminal `REVIEW`.
Repeating the same terminal observation is idempotent, while observation drift
is rejected and never triggers an automatic retry. Event/state tamper, wrong
key, snapshot or pre-fill ledger binding fails closed. JSON round-trip models a
restart without weakening the chain. Every state remains
`simulationOnly:true`, `executionEffect:NONE` and `actionAllowed:false`.

`paper-daily-usage.v1` is content-addressed per synthetic account and UTC day.
Its hash-chained entries accept only a fully validated `RECONCILED` intent whose
decision, account and day bindings match. `HOLD`, `FILLED`, `REVIEW`, another
account/day and tampered state cannot increment usage. Exact replay of the same
intent returns the unchanged ledger; evidence drift fails closed.

Trade count and quote notional are replayed from entries and checked against
the aggregate on every validation. The risk wrapper accepts this validated
ledger and supplies its derived count/notional to the existing limit gate, so
callers can no longer choose those two values. The usage ledger remains
pure, `paperOnly:true`, `executionEffect:NONE` and `actionAllowed:false`.

`paper-admission-control.v1` is an account-bound immutable control with `OPEN`,
terminal `STOPPED` and terminal `TRIPPED` states. Emergency stop accepts only
frozen operator reasons and a hashed command identity. Circuit trip accepts
only reconciliation mismatch, market divergence, permission drift, rate limit
or unknown-state signals with bounded evidence. Exact terminal replay is
idempotent; reason/evidence drift and automatic reopen are rejected.

`paper-admission-decision.v1` monotonically composes the validated risk verdict
with control state. Only `PAPER_ALLOW + OPEN` yields `ADMIT_PAPER`; any risk
blocker, emergency stop or circuit trip yields `HOLD`. This admission is now a
mandatory binding for `open_paper_intent`, so risk approval alone cannot create
`READY`. Even `ADMIT_PAPER` is simulation-only and always
`executionEffect:NONE/actionAllowed:false`.

`paper-equity-valuation.v1` values every asset in a validated paper ledger in
one quote asset. Quote cash is priced at one; every other asset requires exactly
one matching validated snapshot no older than 5 seconds and no more than 1
second in the future. Missing, duplicate, extra, stale or future prices fail
closed. Component multiplication and total equity are replayed by validation.

`paper-equity-baseline.v1` content-binds the initial ledger and valuation.
`paper-drawdown.v1` compares a same-account/same-quote current valuation against
that immutable baseline, floors gains at zero drawdown and deterministically
reports quote loss and basis points. The derived-state risk wrapper now sources
both daily usage and drawdown from validated contracts; callers supply neither
count, notional nor drawdown.

All valuation artifacts remain pure, `paperOnly:true`,
`executionEffect:NONE` and `actionAllowed:false`.

`paper-pnl-reconciliation.v1` accepts only one exact `RECONCILED` intent and
replays its trade from the validated pre-ledger, original market snapshot and
account idempotency key. The observed post-ledger must contain exactly one new
entry and equal both expected and observed intent hashes. Pre/post equity is
rebuilt internally from the same valuation snapshots at the same assessment
time, preventing market movement from being mislabeled as execution P&L.

Fee is taken from the replayed ledger entry and converted through the common
output-asset mark. Net execution P&L is post-equity minus pre-equity; gross
execution P&L is net plus fee. BUY base-asset fees and SELL quote-asset fees are
therefore dimensionally comparable without summing raw asset amounts.

`paper-pnl-journal.v1` accepts only validated reconciliations with strict ledger
continuity, unique intents and a 10,000-entry bound. Exact retry is unchanged;
evidence drift and discontinuity fail closed. Fees, net/gross execution P&L,
count and both hash/ledger heads are fully replayed. All artifacts remain pure,
`paperOnly:true`, `executionEffect:NONE` and `actionAllowed:false`.

`paper-total-pnl-snapshot.v1` binds the immutable equity baseline, current
validated valuation and the complete P&L journal. Baseline ledger must equal
journal start; current valuation ledger must equal journal head; account and
quote must match across all three.

It reports total mark-to-market P&L, net/gross execution P&L, total fees and the
residual `marketAndHoldingPnlQuote`. The equations are independently replayed:
total equals current minus baseline, residual equals total minus execution net,
and gross-before-fees equals total plus fees. The contract explicitly sets
`classification:MARK_TO_MARKET_DECOMPOSITION` and `taxLotAccounting:false`; it
does not expose realized/unrealized fields.

`e3-readiness-proof.v2` orders fifteen exact boolean checks. The first six
cover the verified offline contract suite; the remaining checks cover E2,
production persistence, engine adapter, accepted independent-verifier/result
binding, restricted testnet account, proven withdrawal/transfer denial, runtime
reconciliation, runtime emergency stop and explicit owner approval. Current code
yields `OFFLINE_FOUNDATION_COMPLETE` and `NO_GO` with all nine operational
checks blocked.

Even synthetic all-true input yields only `eligibleForRuntimePreparation:true`;
`runtimeEnableAllowed`, `actionAllowed` and execution effect remain false/false/
`NONE`. The CLI is deterministic JSON stdout-only and does not probe, mutate or
enable runtime state.

The next safe slice is an isolated PostgreSQL schema/repository rehearsal for
E3 intents, events, usage, admission and P&L. It must not migrate production or
change the readiness proof until deployment and runtime acceptance are separate.

`024_e3_paper_evidence.sql` defines dormant append-only persistence for four
validated snapshot kinds: intent state, daily usage, admission control and P&L
journal. A server-side compare-and-append function locks the account/kind head,
requires exact sequence and previous hash, accepts exact head retry as a no-op,
rejects drift, and bounds JSON evidence at 1 MiB. Evidence update/delete and
direct head mutation are revoked; an update/delete trigger is fail-closed.

The KAIROS adapter validates each contract before opening a database connection
and invokes exactly one atomic server function. A disposable PostgreSQL 17
container with no published port or persistent volume rehearsed migration,
first append, exact retry, next append, mutation rejection, sequence-gap and
idempotency-drift rejection. It was removed afterward; production PostgreSQL
was not queried or migrated. Consequently `PRODUCTION_PERSISTENCE_READY`
correctly remains false.

`paper-engine-submission.v1` is derived only from a fully validated `READY`
paper intent and content-binds its state, account, ledger, market, policy,
side, amount, fee and idempotency hash. `paper-engine-receipt.v1` binds the
exact submission and admits only explicit `ACCEPTED/NONE` or
`REJECTED/<bounded reason>` outcomes. Transport responses are treated as
untrusted: extra fields, binding drift, live mode, invalid time and malformed
identifiers fail closed.

The adapter accepts only an injected `PaperEngineTransport`; it imports no CEX
SDK or network/runtime configuration and mutates neither the intent nor a
ledger. Both artifacts are content-addressed and fixed to
`PAPER_SIMULATION`, `simulationOnly:true`, `executionEffect:NONE` and
`actionAllowed:false`. This hermetic boundary does not satisfy the operational
`ENGINE_ADAPTER_READY` readiness check.

`paper-engine-fill-projection.v1` now requires an exact validated
`ACCEPTED/NONE` receipt before the engine path may project `READY → FILLED`.
The receipt must bind the canonical submission for that exact ready-state, and
time must be monotonic as `READY ≤ receipt ≤ FILLED`. The receipt ID is stored
as the fill event's hash-chain evidence; the content-addressed projection also
binds ready/filled state hashes and the expected ledger hash. Rejected,
cross-state, future, malformed or tampered evidence fails closed. Existing
ledger reconciliation remains unchanged.

This remains a pure projection. It does not make transport calls, persist
state, authorize an action or satisfy `ENGINE_ADAPTER_READY`.

`paper-engine-attempt.v1` wraps one hermetic invocation in immutable terminal
evidence. A valid response produces `RECEIVED` bound to its receipt. Timeout,
transport failure or malformed response produces `UNKNOWN` with only a frozen
reason class; exception text is not retained. Every attempt fixes
`retryAllowed:false` and `automaticResubmitAllowed:false`. Unknown attempts
require manual review and contain no receipt, so they cannot enter the
receipt-gated fill projection.

Supplying a previous validated attempt is exact replay: its submission and
optional receipt are revalidated and returned without calling the injected
transport. Any attempt/receipt drift fails before transport. Times are explicit
inputs and a received receipt must fall within the attempt interval. The module
contains no clock, network, SDK or runtime configuration access and still does
not satisfy `ENGINE_ADAPTER_READY`.

`paper-engine-attempt-resolution.v1` resolves only a validated immutable
`UNKNOWN` attempt. Exactly one branch is permitted: an independently recovered
receipt bound to the original submission, or a bounded manual disposition
(`AMBIGUOUS`, `ENGINE_UNAVAILABLE`, `NOT_FOUND`, `OPERATOR_ESCALATED`). The
resolution binds a lowercase SHA-256 evidence reference and cannot predate the
attempt. It never rewrites the attempt and always fixes retry and automatic
resubmit to false.

A recovered accepted receipt alone makes `fillEligible:true`; a recovered
rejection and every manual disposition remain false. The UNKNOWN-specific fill
entry point revalidates the resolution and recovered receipt before delegating
to the existing receipt-gated projection. Exact resolution replay is unchanged;
receipt or resolution drift fails closed. This is still pure code without an
engine query, storage, clock, network or runtime authority.

`paper-engine-evidence-bundle.v1` is the self-contained persistence unit for
engine evidence. It jointly revalidates the canonical READY intent, submission,
attempt, optional receipt/resolution, and optional filled intent/projection.
Received, unresolved UNKNOWN, manually resolved UNKNOWN and recovered-receipt
shapes are explicit; partial fill pairs, smuggled receipts and ineligible fills
fail closed. Sequence and previous bundle hash are part of the content hash.

The dormant PostgreSQL evidence store now admits `ENGINE_EVIDENCE` only after
bundle validation and requires its `previousBundleHash` to equal the database
continuity argument before opening a connection. The same atomic server
function supplies exact retry/no-op, sequence/head locking, gap/drift rejection,
1 MiB bounds and append-only mutation guards.

A disposable PostgreSQL 17 container with no published port or volume verified
first append, exact retry, next append, gap/drift/mutation rejection and the
final head, then was removed. Production PostgreSQL was not queried or migrated;
`PRODUCTION_PERSISTENCE_READY` and `ENGINE_ADAPTER_READY` remain false.

`testnet-capability-observation.v1` is a secret-free, content-addressed record
for one permission inventory or one withdrawal/transfer denial observation. It
is fixed to `TESTNET/SPOT_PAPER`, bounded to 15 minutes with 1 second of future
skew, contains only a lowercase evidence hash (never a key or credential
identifier), and cannot authorize an action.

`restricted-testnet-account-evidence.v1` requires exactly one inventory plus
both denial observations for the same provider/account. It requires market and
balance reads plus spot create/cancel, no margin/derivatives/withdrawal/transfer
grants, explicit denial of every forbidden scope, and explicit denied outcomes
for withdrawal and transfer. Missing, duplicated, mixed-account, stale/future,
unavailable or permissive evidence is `NO_GO` or invalid.

Even perfect evidence yields only `OFFLINE_ELIGIBLE` with
`runtimeVerified:false` and `readinessCheckSatisfied:false`. The contract is
pure and does not perform the observations itself, contain secrets, access a
clock/network/config or change either readiness check.

`testnet-capability-verifier-request.v1` requests only existing secret-free
evidence for the three frozen observation types. It is fixed to
`FETCH_EXISTING_EVIDENCE`, `activeProbeAllowed:false`, `TESTNET/SPOT_PAPER` and
cannot authorize an action. The hermetic adapter accepts only an injected
source; it contains no network, SDK, secret, clock or active permission probe.

`testnet-capability-verifier-result.v1` embeds a fully validated capability
assessment when the response is well formed. A permissive but valid assessment
is explicit `CAPABILITY_BLOCKED`; timeout, source error and malformed or
secret-bearing responses are `NO_GO` without retaining exception text. Exact
replay validates and returns prior evidence without invoking the source.

Even `VERIFIED_OFFLINE` fixes `independentDeploymentVerified:false` and
`readinessCheckSatisfied:false`; it does not satisfy either testnet readiness
check.

The next safe E3 slice is a pure independent-verifier deployment acceptance
contract covering service identity, least privilege, secret absence, immutable
artifact provenance and bounded result freshness. It must remain NO_GO without
real deployment evidence and must not install, start or configure a service.

`independent-verifier-deployment-observation.v1` freezes five secret-free,
content-addressed evidence classes: service identity, least privilege, secret
absence, immutable artifact provenance and result freshness. Observations are
pass/fail/unavailable, share one opaque deployment identity, permit no active
probe and are bounded to 15 minutes with one second of future skew.

`independent-verifier-deployment-acceptance.v1` requires exactly one fresh PASS
for every class. Missing, duplicated, mixed-deployment, stale, future, failed,
unavailable, secret-bearing or tampered evidence fails closed. Complete evidence
is only `ACCEPTED_OFFLINE`: runtime readiness and runtime enablement remain false
and the contract performs no install, service, network, configuration or secret
operation.

The next safe E3 slice is a pure binding between the accepted independent
deployment evidence and one validated capability-verifier result, preserving
freshness and identity while still leaving restricted-testnet readiness false.

`independent-verifier-capability-binding.v1` validates the deployment
acceptance, verifier request and capability result together. The deployment
assessment and request must share the exact assessment time, while its
`RESULT_FRESHNESS` evidence SHA-256 must bind the exact validated result.
Deployment rejection, result-digest drift or a non-verified capability result
is explicit `NO_GO`.

The positive state is only `BOUND_OFFLINE`. It confirms that one offline
capability result belongs to one accepted verifier identity, but keeps
restricted-testnet readiness, runtime enablement and actions false. The module
has no service, network, credential, configuration or persistence surface.

The next safe E3 slice is to extend the read-only readiness proof with this
binding as a required operational evidence input, without making a synthetic
binding satisfy real runtime deployment, reconciliation, emergency-stop or
owner-approval gates.

The inactive independent-verifier artifact is now specified without deploying
it. `e3_independent_verifier.py` consumes one bounded local secret-free evidence
bundle, invokes the hermetic adapter exactly once and emits deterministic JSON;
invalid or oversized input becomes a bounded `NO_GO` without echoing content.
It contains no provider SDK, network client, environment-secret or active action
surface.

`kairos-independent-verifier.service` is a deliberately non-enableable oneshot
template for a dedicated non-login identity. It has no `WantedBy`, environment
file or writable path; private networking, `AF_UNIX` only, empty capabilities
and strict filesystem/home/device/kernel protections are mandatory. The
content-addressed artifact manifest fixes the exact script and unit SHA-256 and
explicitly records that installation and runtime enablement are unauthorized.
No service, user, state directory or input evidence has been created.

The next safe E3 slice is a pure artifact-acceptance contract that validates
this manifest shape and turns independently measured file digests, identity and
sandbox evidence into deployment observations. It must not treat the checked-in
template itself as proof that production deployment occurred.

`independent-verifier-artifact-measurement.v1` is a content-addressed input from
an independent measurement boundary. It fixes the opaque deployment identity,
artifact/version and exact sorted file digests, dedicated non-login service
identity, ten explicit sandbox properties and a secret-scan verdict. It carries
no secret, active probe or action permission.

`independent-verifier-artifact-acceptance.v1` compares that measurement with the
frozen manifest and emits exactly four deployment observations: identity, least
privilege, secret absence and provenance. Each dimension fails independently.
It deliberately cannot emit `RESULT_FRESHNESS`; feeding its otherwise perfect
observations into deployment acceptance remains `NO_GO` with
`RESULT_FRESHNESS_MISSING`. Artifact acceptance is therefore not evidence that
installation occurred and cannot satisfy deployment, readiness or runtime gates.

The next safe E3 slice is a pure result-attestation contract for an independently
measured invocation. It may create `RESULT_FRESHNESS` only when it binds the
exact validated verifier result, artifact acceptance/deployment identity and a
fresh bounded measurement; it must still perform no service or network action.

`independent-verifier-result-attestation.v1` revalidates the artifact
acceptance, measurement, verifier request and result. It emits the fifth
`RESULT_FRESHNESS` observation for the same opaque deployment identity with the
exact canonical result SHA-256. A rejected artifact produces only a failed
freshness observation. A valid but capability-blocked result can be attested as
fresh, but the separate capability binding remains `NO_GO`.

Combining the four artifact observations with this exact fifth observation can
produce deployment `ACCEPTED_OFFLINE` and capability `BOUND_OFFLINE`; neither
artifact nor attestation itself claims deployment verification, readiness or
runtime enablement. The contract performs no file, clock, service, network,
credential or persistence action.

The next safe E3 slice is an end-to-end pure acceptance bundle that jointly
revalidates manifest, independent measurement, artifact acceptance, request,
result, attestation, deployment acceptance and capability binding as one
content-addressed chain, while keeping the readiness operational probe false
until a real separately authorized deployment supplies the evidence.

`independent-verifier-acceptance-bundle.v1` revalidates that entire chain and
requires the deployment acceptance to contain the exact four artifact
observations plus the exact result attestation under one deployment identity.
Any inner hash, identity, observation or verdict drift invalidates the bundle.

A complete chain is only `EVIDENCE_CHAIN_VALIDATED_OFFLINE` and eligible for
operational review. The bundle invariantly keeps production deployment proof,
the readiness probe, runtime enablement and actions false. Consequently test
fixtures and repository artifacts cannot flip the E3 operational gate.

The next safe E3 slice is a separate operational acceptance design for a real,
explicitly authorized deployment rehearsal. It must distinguish measured host
state from repository fixtures, use no CEX secret, keep the service disabled by
default and require owner approval before any installation or invocation.

`independent-verifier-rehearsal-plan.v1` freezes a non-executing workflow for a
disposable isolated non-production host only. Six mandatory preconditions
include explicit owner approval, verified isolation, absence of production data
and credentials, manifest verification and a checked rollback target. Eleven
ordered non-retrying steps verify absence/digests, create a non-login identity,
install the bounded artifacts and secret-free input, verify sandboxing, invoke
the oneshot once, collect a secret-free measurement, remove everything and
verify final absence.

The plan itself fixes production, credentials, network, persistent install,
execution authorization, runtime enablement and actions to false. It contains no
commands or execution/filesystem/network surface and therefore cannot perform
the rehearsal or serve as owner approval.

The next safe E3 slice is a pure rehearsal-authorization receipt contract that
requires all six independently evidenced preconditions and explicit bounded
owner approval for this exact plan/manifest/target. Creating such a contract
must still not execute the plan or authorize production deployment.

`verifier-rehearsal-precondition-evidence.v1` content-binds each required check
to the exact plan and disposable target. `verifier-rehearsal-owner-approval.v1`
is separately bound to the same pair, permits one isolated non-production
rehearsal for at most 15 minutes and forbids production, credentials, network
and persistence.

`verifier-rehearsal-authorization-receipt.v1` requires one unique PASS for all
six checks and a current exact approval. A positive receipt is only `ELIGIBLE`
for one rehearsal invocation; it still has no execution effect or action
surface and cannot satisfy E3 readiness. No real approval or receipt has been
created by the test fixtures.

The next safe boundary is execution itself, which is intentionally blocked
until the owner separately approves a specific disposable isolated target. Do
not create host state or reinterpret general continuation as that approval.
