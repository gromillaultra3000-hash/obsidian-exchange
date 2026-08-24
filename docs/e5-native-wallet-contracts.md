# E5 native wallet contracts

Status: design-only, non-executing foundation.

`native-wallet-key-boundary.v1` freezes the first native-wallet trust boundary
without selecting a chain or implementing key generation, recovery or signing.
Keys originate in hardware-backed storage on the user's device and are
non-exportable. The native signing bridge may sign only after local user
authorization and must bind the signed preimage to the displayed network,
destination, amount and fee.

The remote server is explicitly untrusted for signing. It may prepare an
unsigned request and broadcast already-signed bytes, but it may never receive a
seed, private key, keystore export, biometric template or local-authenticator
secret. Server authorization alone is never sufficient for a signature.

The contract remains `DESIGN_ONLY`: network selection is undecided, recovery
and reproducible build provenance are required but unimplemented, and
production release, signing and money actions are all false. Content hashing
and canonical reconstruction make capability/readiness tampering fail closed.

Next safe E5 slice: define a pure signing-request/display contract that accepts
only canonical unsigned transaction summaries for one still-synthetic network
profile, binds local authorization to those exact displayed fields, and emits no
signature. Do not choose or integrate a mobile keystore SDK until the threat
model, recovery design and dependency/provenance review are separately approved.

`native-signing-display-request.v1` now fixes that synthetic boundary. It binds
the SHA-256 of one unsigned payload to the exact human-visible synthetic network,
destination, amount and fee. Decimal and address representations are canonical,
the request expires within two minutes and no production network is accepted.

`native-signing-consent-receipt.v1` requires a distinct second interaction,
at least 750 ms after display and before request expiry. It binds the exact
request/payload/display digests and stores only hashes of interaction IDs. This
is deliberately an offline consent record, not authenticator evidence:
`localAuthenticatorVerified`, `signingAllowed`, signature presence and every
production/action flag remain false.

Next safe E5 slice: freeze a pure local-authenticator evidence contract that
binds a hardware-backed authenticator assertion to this exact consent receipt,
with freshness, anti-replay and device-key identity requirements, but still no
transaction signature or platform SDK. Recovery and formal threat modeling
remain independent prerequisites.

`native-authenticator-evidence.v1` now freezes that boundary. It content-binds
the exact request and consent receipt to hashes of one device-key identity,
request challenge and synthetic authenticator assertion. The assertion must
follow consent, remain inside the request lifetime, be observed within 30
seconds (with one second future skew), and advance a caller-supplied monotonic
counter. A consumed evidence ID cannot be replayed.

Hardware backing and user verification remain evidence claims only:
platform attestation and local-authenticator verification are explicitly false.
No biometric data, key material, signature, SDK, storage, network or execution
surface exists, and all signing/production/action flags remain false.

Next safe E5 slice: define the recovery threat model and a pure recovery-policy
contract covering device loss, backup confidentiality, social-engineering and
rollback resistance. Do not select a recovery mechanism or mobile SDK yet.

The recovery threat model is now recorded in `e5-native-wallet-threat-model.md`.
The confirmed design permits a user-controlled offline seed and adds an
independent 2-of-3 guardian/device route. `native-wallet-recovery-policy.v1`
freezes both paths: the server cannot receive the seed, hold a recovery share,
act as guardian, override the threshold or bypass the 24-hour recovery delay.
The guardian path requires distinct trust domains, a newly attested device,
local user verification, notifications, active-device veto and single-use
approvals. Monotonic recovery epochs and prior-device revocation prevent an old
backup from restoring superseded authority.

This remains design-only. Cryptography, platform SDK and formal protocol are
undecided; no seed/share, storage, network, signing or recovery implementation
exists, and production/action flags remain false.

Next safe E5 slice: define a pure recovery-attempt state machine binding the new
device, recovery epoch, delay, guardian approvals and active-device veto. Keep
it synthetic and non-executing until cryptographic protocol and platform threat
models are approved.

`native-wallet-recovery-attempt.v1` now freezes that state machine. Every
attempt binds the wallet, active and target device identities, synthetic target
attestation, current epoch and exactly-next proposed epoch. Its hash-chained
events accept approvals only from distinct policy guardian domains and bind
each approval to the target device and epoch. Exact approval retry is unchanged;
evidence drift or a second event from the same guardian fails closed.

The one-way outcomes are `PENDING_DELAY → ELIGIBLE_OFFLINE`, `VETOED` or
`EXPIRED`. Eligibility requires two guardians and the full 24-hour delay. The
active device may veto during that delay. Eligibility remains evidence only:
no authority is installed, no prior device is revoked, no recovery executes and
all production/action flags remain false.

Next safe E5 slice: define a pure recovery-completion proposal that requires an
eligible attempt plus independently verified new-device and revocation evidence,
but can emit only `COMPLETION_REVIEW_READY_OFFLINE`; do not install authority.

`native-wallet-recovery-completion-proposal.v1` now freezes that review
boundary. It accepts only an exact `ELIGIBLE_OFFLINE` attempt and two fresh,
content-hashed evidence records: verification of the target device and
verification that the prior device is the revocation subject. Both bind the
same wallet, attempt, target and exactly-next epoch. Their verifier identities
must be distinct from each other and from both device identities.

The result is only `COMPLETION_REVIEW_READY_OFFLINE`. It does not assert that
revocation already happened, install new authority, enable signing, execute
recovery or permit a production action. No storage, network, SDK or key
material exists in this contract.

Next safe E5 slice: freeze a pure completion-review decision and single-use
authorization envelope that can still only authorize a future isolated mobile
rehearsal, never install authority or enable production recovery.

`native-wallet-recovery-completion-review.v1` and
`native-wallet-recovery-rehearsal-authorization.v1` now freeze this boundary.
The review binds the canonical completion proposal to eight ordered checks and
emits either `REHEARSAL_REVIEW_READY` or explicit `NO_GO`. The authorization
then binds one current positive review to an exact disposable target, mobile
build digest and nonce for at most ten minutes and one invocation. Validation
rejects an authorization ID already present in a caller-supplied consumed-ID
snapshot.

Even the positive envelope permits only one isolated, non-production mobile
recovery rehearsal. Production networks, credentials and wallets, real key
material, authority installation, prior-device revocation, broadcasting,
automatic retry, signing and action remain forbidden with `executionEffect:
NONE`. The contract performs no I/O and is not a rehearsal runner.

Next safe E5 slice: define a pure rehearsal result/attestation contract that
binds this single-use authorization to synthetic observed steps and reports
PASS/FAIL without installing authority, touching a production wallet or
claiming on-device security.

`native-wallet-recovery-rehearsal-consumption.v1`, observation and result
contracts now freeze that evidence boundary. Consumption binds one invocation
inside the authorization lifetime to the exact nonce, disposable target and
mobile build. Ten ordered observations cover isolation, build identity,
single consumption, synthetic-only wallet/key use, absence of production
network and broadcast, no authority/revocation effect, and target teardown.
The result additionally requires a consumed-ID ledger snapshot containing the
exact authorization ID once. Missing, duplicate, time-invalid or
binding-drifted evidence fails closed.

The final attestor must be independent from the runner and observers. Complete
PASS evidence yields only `isolatedRehearsalPassed:true`; any failed step is
reported explicitly. On-device security and production readiness remain
unverified, while recovery, authority installation, prior-device revocation,
signing and action remain false. This is a pure evidence normalizer, not a
mobile runner or attestation verifier.

Next safe E5 slice: define a read-only E5 readiness proof that combines all
design contracts and this synthetic rehearsal result, but remains `NO_GO`
until a selected mobile stack, reproducible-build provenance, real platform
attestation verification, on-device backup/restore tests and explicit owner
approval exist independently.

`native-wallet-e5-readiness-proof.v1` now freezes this read-only gate. Seven
foundation checks are derived from canonical validation of the complete E5
contract/rehearsal chain. Eight separately supplied operational booleans cover
reviewed mobile stack and recovery protocol, reproducible build provenance,
real platform attestation and hardware backing, on-device backup/restore E2E,
abuse/fault testing and explicit owner production-release approval.

The truthful current probe set leaves all eight operational checks false, so
the stage is `DESIGN_AND_SYNTHETIC_FOUNDATION_COMPLETE/NO_GO`. Even a synthetic
all-true proof permits only native-implementation review: selected stack and
network remain `UNDECIDED`, and production release, recovery execution,
authority installation, signing, runtime enable and action remain false. The
proof performs no host, device, network, file or service probes.

Next E5 work requires an explicit technology-selection task before choosing a
real mobile/cryptographic stack. Until then, continue safe cross-stage E0-E4
work rather than manufacturing operational E5 evidence.

The owner has now selected the architecture recorded in
`docs/adr/0001-native-wallet-stack.md`: native SwiftUI and Jetpack Compose
shells, a shared Rust/UniFFI core, Bitcoin Signet first, Bitcoin Core
libsecp256k1-family signing, hardware-backed wrapping and server-verified app
integrity risk signals. The key boundary is corrected to v2: Secure Enclave and
Android Keystore protect non-exportable wrapping/authentication keys, while the
Bitcoin secp256k1 wallet secret is ciphertext at rest and may exist only briefly
in bounded native-process memory after local authorization. It must be zeroized
after every success/failure and never reaches the server.

`native-wallet-technology-selection.v1` freezes this decision for a hermetic
scaffold while explicitly deferring seed generation, derivation, signing,
mainnet and additional chains. Next safe slice: create the dependency-minimal
Rust workspace and UniFFI boundary with a pinned, checksum-verified toolchain,
canonical Signet transaction-preview types and no cryptographic secret surface.

That Rust scaffold now exists under `native-wallet/`. Rust 1.97.1 was installed
from the official rustup binary after its published SHA-256 passed; the workspace
pins the same toolchain and UniFFI 0.32.0 with `Cargo.lock`. `wallet-core` and a
separate UniFFI adapter expose only a bounded Bitcoin Signet preview draft. The
core pins rust-bitcoin 0.32.102 with default features disabled, parses the full
address checksum, requires the Signet network, rejects non-canonical text and
exposes the exact destination scriptPubKey as lowercase hex. This validation
now feeds a bounded output-set contract: one to sixteen outputs must be strictly
ordered by scriptPubKey with no duplicate destination scripts, every amount is non-zero and
the sum is overflow-checked. The preview accepts only a bounded total input and
derives its fee as `total inputs - total outputs`; no caller-supplied fee is
trusted. This still cannot reach signing. Mainnet, real keys, storage, network
and broadcast APIs are absent; unsafe Rust is forbidden and strict Clippy is
enabled. The RustSec gate is now complete: pinned `cargo-audit` 0.22.2 scanned
the locked 92-crate graph against 1,211 advisories with `--deny warnings` and
returned clean.

The preview is now also bound to a canonical unsigned-transaction structure.
Only Bitcoin transaction version two is accepted; one to sixty-four input
outpoints must have canonical lowercase TXIDs, unique strict outpoint ordering,
bounded non-zero values and explicit sequences. A non-zero lock time requires
at least one non-final sequence. The core constructs the exact consensus
serialization with empty scriptSigs/witnesses and rejects the request unless
its SHA-256 equals the displayed unsigned-payload digest. Input values are
display/accounting metadata and are not falsely claimed to be authenticated
UTXO evidence. No signing or broadcast method is exposed.

Each input requires `native-signet-utxo-evidence.v1` from the exact
`BITCOIN_CORE_SIGNET_RPC_SNAPSHOT_V1` contract. Its canonical SHA-256 binds the
source, observed block height/hash/time, outpoint, amount, sequence and previous
scriptPubKey. Evidence must be no more than ten minutes old at preview creation;
unknown sources, zero/malformed blocks, non-canonical script/proof hex and any
field drift fail closed. The bounded consensus-encoded `MerkleBlock` is decoded
locally; its header hash must equal the observed block, its partial tree must
validate against the header Merkle root, and it must yield exactly the input's
previous TXID. The result is explicitly
`TX_INCLUSION_VERIFIED_CHAIN_AND_UTXO_STATE_NOT_VERIFIED`: inclusion is true,
while `chain_verified=false` because one header is not a trusted Signet header
chain and inclusion does not prove that the output remains unspent. No RPC or
network access occurs in the core.

Evidence now also carries one to 144 exact consensus headers from
`UNREVIEWED_EXTERNAL_SIGNET_CHECKPOINT_V1`. The offline core requires canonical
80-byte header encodings, exact checkpoint-height arithmetic, first-header
`prev_blockhash` equality, complete pairwise linkage and a final hash equal to
the Merkle-proof block. It emits
`LINKED_TO_UNREVIEWED_CHECKPOINT_NOT_CONSENSUS_VERIFIED`, with
`linkage_verified=true`, `checkpoint_trusted=false` and `chain_verified=false`.
This slice intentionally does not validate the Signet challenge solution,
difficulty transition schedule, accumulated work or checkpoint provenance.

The checkpoint review format is now frozen as
`native-signet-checkpoint-review.v1`. It binds `BITCOIN_SIGNET`, exact height and
hash, exactly two distinct sorted source SHA-256 values, exactly two distinct
sorted opaque reviewer IDs and review time into one canonical digest. Artifact
fields must match the header-chain checkpoint. This proves structural integrity
of independent-review claims only, not source authenticity or reviewer identity;
therefore `independent_review_claims_bound=true` still leaves
`checkpoint_trusted=false`. The capability decision is explicit:
`HEADER_LINKAGE_ONLY_NO_SIGNET_CHALLENGE_OR_DIFFICULTY`.

The offline approval proposal is now frozen as
`native-signet-checkpoint-approval-proposal.v1` with policy
`OFFLINE_2_OF_3_SIGNATURES_NOT_VERIFIED`. It binds the exact review-artifact
digest, three distinct sorted opaque signer-key IDs, exactly two distinct sorted
signature-byte SHA-256 claims and a maximum ten-minute expiry. Duplicate or
foreign signers, duplicate signature digests, artifact drift and expiry fail
closed. `approval_proposal_content_bound=true` but
`approval_signatures_verified=false`; no trust key or cryptographic verifier is
embedded and checkpoint/chain trust remain false.

The initial trust-key ceremony is now frozen as
`native-checkpoint-trust-key-ceremony.v1`. Epoch one requires three distinct
sorted key-slot IDs and external key-material SHA-256 commitments, three
distinct sorted participant IDs disjoint from the key slots, and two distinct
sorted transcript digests. Approval signers must equal the ceremony key slots.
The initial predecessor and revoked-key sets must be empty. Algorithm remains
`UNDECIDED`; `trust_key_ceremony_content_bound=true` while
`trust_keys_installed=false` and `trust_key_algorithm_selected=false`.

Epoch-two lifecycle proposals are now frozen separately from transaction
preview. `native-checkpoint-key-rotation-proposal.v1` binds epoch `1 → 2` to the
exact predecessor ceremony and key slots, three wholly new slots/material
commitments, three disjoint participants, two transcript digests and a future
activation within 24 hours. `native-checkpoint-key-revocation-proposal.v1`
allows only predecessor slots, bounded compromise/loss/ceremony-failure reasons,
two disjoint observers/evidence digests and a ten-minute expiry. UniFFI returns
`native-checkpoint-key-lifecycle-review.v1` with both content bindings true but
`execution_allowed=false`, `keys_changed=false` and
`algorithm_selected=false`.

Next implementation slice: freeze an algorithm-selection ADR/contract for
checkpoint signatures, including dependency provenance and test vectors. Real
key bytes, installation and lifecycle execution still require separate owner
authorization.

The selection is now frozen as
`native-checkpoint-signature-algorithm-selection.v1` using
`BIP340_SECP256K1_XONLY_SHA256` and domain
`OBSIDIAN_CHECKPOINT_APPROVAL_V1`. It records locked `bitcoin` 0.32.102,
`secp256k1` 0.29.1 and `secp256k1-sys` 0.10.1 provenance, plus exact 32-byte
x-only key, 64-byte signature and 32-byte digest sizes. Selection is not
implementation: official vectors are required, while verifier, key
installation, signing, checkpoint trust and chain verification remain false.

Next implementation slice: pin the official BIP340 CSV vectors by source
revision and SHA-256, then add a verification-only parser and negative/mutation
test harness. Do not install real key material or activate trust in that slice.

That verification-only slice is now complete. The official 19-row BIP340 CSV is
vendored at the pinned bitcoin/bips revision with a SHA-256 provenance check.
The test-only parser rejects header, field-count, verification-result and hex
drift; the frozen 32-byte message profile is checked through the locked
secp256k1 API, while the four arbitrary-size upstream messages remain outside
the application profile. Key, message, signature and length mutations fail
closed. This is conformance evidence only: no application verifier, trust-key
material, key installation, signing, checkpoint trust or UniFFI capability was
added.

Next safe E5 slice: freeze and implement the verification-only application
message-binding preimage for `native-checkpoint-approval-signature-message.v1`,
then test field/domain/length drift without accepting any approval or enabling
trust. Real key material and lifecycle execution remain separately blocked.

That message-binding slice is now complete as a test-only contract. It uses the
exact tagged SHA-256 construction and big-endian length/number encoding from
ADR 0003, binds approval/artifact/ceremony digests, epoch, signer and expiry,
rejects unsupported domains and malformed context, and proves that every bound
field changes the resulting message. The harness is not compiled into
`wallet-core` or UniFFI and cannot verify a signature, install keys, accept an
approval or enable checkpoint trust.

Next safe E5 slice: independently audit and finalize the existing
verification-only terminal decision matrix for a future approval verifier,
including failure precedence, epoch freshness, signer/quorum handling and an
explicit non-authoritative terminal outcome.

That matrix audit is now complete. The test-only decision function preserves the
declared failure precedence, treats fewer than two claims as insufficient
quorum, rejects more than two claims or duplicate active slots as malformed
binding, and keeps the quorum result explicitly non-authoritative. It contains
no key material, signature bytes, cryptographic verification, trust mutation or
UniFFI/runtime surface.

Next safe E5 slice: independently audit the existing active-key-set evidence
mapping contract, including ceremony-set equality, signer-to-key mapping,
commitment integrity and reviewer-claim non-authority.

That active-key-set audit is now complete as a test-only contract. It verifies
the exact three-slot ceremony set, canonical x-only public keys, sorted
signer-to-key mapping, commitment-set equality and content-digest binding. It
also rejects reviewer overlap with signer slots, duplicate slot order and
review-time drift. Reviewer identity remains an unauthenticated claim; key
installation, active authority, checkpoint trust and production action remain
false.

Next safe E5 slice: independently audit the existing keyset review-acceptance
bundle, including reviewer trust-domain separation, validity window, bound
mapping/algorithm/ceremony digests and non-authoritative outcome.

That review-acceptance audit is now complete as a test-only bundle. It enforces
allowlisted and distinct reviewer domains, sorted non-overlapping reviewer IDs,
strictly positive bounded validity windows, observation freshness and exact
ceremony/mapping/algorithm digest binding. The result remains
`REVIEW_CLAIMS_BOUND_NON_AUTHORITATIVE`; attestation hashes are not signatures,
and no key installation, active authority or checkpoint trust is possible.

Next safe E5 slice: independently audit the existing reviewer-identity policy
and attestation envelope boundary, including two-domain separation, credential
root/revocation freshness, single-use evidence and non-authoritative outcomes.

That reviewer-policy and human WebAuthn-envelope audit is now complete as
test-only evidence. The policy explicitly receives the active signer set and
rejects reviewer overlap, shared domains/roots/recovery authorities, replayed
evidence, stale/revoked roots, clock-window violations and double automation.
The envelope binds the exact expected evidence ID and challenge, origin, RP ID,
UP/UV and backup flags. Signature verification, enrollment authentication and
acceptance remain false.

Next safe E5 slice: independently audit the automated build-attestation
envelope, including subject/rebuild binding, DSSE/SLSA field exactness,
dependency and external-parameter canonicalization, and non-authoritative
provenance claims.

That automated build-attestation audit is now complete as a test-only envelope.
The review requires an independently supplied rebuild digest and checks exact
subject equality, DSSE/SLSA identifiers, builder/source, dependency ordering,
allowlisted external parameters and canonical digest fields. It remains
structural evidence only: no DSSE signature, credential root, builder identity
or reproducible-build claim is authenticated.

Next safe E5 slice: independently audit the existing DSSE PAE/parser limits and
closed semantic decision boundary, keeping malformed or unauthenticated input
non-authoritative.

That DSSE boundary audit is now complete as test-only policy. Parser limits now
cover the explicit ASCII requirements for payload type and optional `keyid`,
while canonical Base64 and exact public PAE vectors remain enforced. The
semantic matrix proves invalid signatures short-circuit all later payload and
policy checks, and every terminal result remains non-authoritative.

Next safe E5 slice: audit the existing DSSE source-provenance and corpus-manifest
boundary, including pinned revisions/hashes, no-private-fixture policy and
two-reviewer provenance requirements.

That source-provenance and corpus-manifest audit is now complete as metadata-only
policy. The pinned raw sources require immutable revisioned HTTPS URLs and
canonical hashes; the derived PAE fixture is byte-hash checked and explicitly
contains no signatures or key material. Supplemental policy closes schema gaps
for unique case IDs, independent reviewer/result domains, sealed expectations,
offline generators, corpus-hash agreement and disabled authority flags.

Next safe E5 slice: audit the isolated strict attestation parser rehearsal and
dependency/provenance boundary, keeping its parser and symbolic oracle outside
wallet runtime and production authority.

That strict-parser and dependency-boundary audit is now complete as isolated
rehearsal evidence. The metadata-only policy binds each profile's lock SHA-256,
registry count and exact direct versions to `RESULTS.json`; every profile remains
an empty standalone Cargo workspace with no path/git dependency, and the native
wallet workspace does not include any rehearsal root. The minimal parser passes
11 offline tests covering lexical limits, duplicate/unknown fields, canonical
payload/signature shape, PAE and closed semantic policy; the schema comparison
profile compiles offline. No external source was fetched or executed, no
signature or key was verified/selected, and no trust root, runtime authority or
UniFFI surface was added.

Next safe E5 slice: audit the existing Ed25519 corpus independent-review gate,
including issuer authentication, reviewer/result binding and non-authoritative
outcomes.

That independent-review audit is now complete as a test-only boundary. The
closed response/pair policy binds the exact request, review timestamp,
assertion-envelope digest, reviewer/domain and authentication window; it
rejects generator identities, malformed responses, expired/future evidence and
cross-review reuse of evidence, credential roots, recovery authorities or
assertion envelopes. The challenge and pair checks remain structural only:
reviewer authentication, cryptographic verification, trust installation and
runtime integration are false.

Next safe E5 slice: audit the existing Ed25519 reviewer-result authentication
handoff boundary, keeping issuer selection and authenticated result acceptance
blocked until real independent roots and recovery evidence exist.

That reviewer-result handoff audit is now complete as a test-only boundary. The
closed result contract now binds the review request, assertion, challenge,
credential/revocation context, verifier identity/build/policy, caller nonce and
bounded issue/expiry window. The helper rejects extra fields, digest/context
drift, caller-supplied replay snapshots, replay-window violations and timestamps
outside the result lifetime.
The result remains unauthenticated external evidence: no issuer/root is
selected, no verifier build is trusted, no credential is enrolled and no
reviewer or Ed25519 acceptance is enabled.

Next safe E5 slice: audit the existing independence-evidence issuer
authentication challenge and pair-separation boundary; keep issuer selection,
real roots and authenticated acceptance blocked.

That independence-evidence issuer boundary audit is now complete as a test-only
contract. The challenge order is closed and binds the exact schema, scorecard,
evidence record, issuer/trust context, consumer-selected root, recovery epoch,
caller nonce and bounded timestamps. The context rejects root drift, stale or
future timestamps, epoch rollback and nonce replay. Pair validation now covers
all schema-declared cross-review separation fields, within-record root/recovery/
builder reuse, closed shape, decision and lifetime. Issuer enrollment, real
authentication, evidence acceptance, selection, crypto calls and runtime
integration remain false.

Next safe E5 slice: audit the supporting-evidence bundle and control-conflict
matrix boundary, including exact artifact binding, expiry coverage and
non-waivable separation decisions.

That supporting-evidence and control-conflict audit is now complete as a
test-only contract. The closed bundle validator binds the independence,
scorecard, issuer-challenge and review-domain digests/identity, requires all
fourteen unique canonical artifact records, `COMPLETE` status, external hash-only
bytes, bounded issuance/lifetime and artifact expiry coverage. The conflict
matrix now rejects missing, extra, duplicate or invalid cells and requires the
exact transitive-control relationship set; only `SEPARATE_WITH_EVIDENCE` passes,
with waivers, majority scores and compensating controls explicitly forbidden.
No real artifact, evidence acceptance, issuer authentication, selection, crypto
call or runtime integration is enabled.

Next safe E5 slice: audit the issuer-selection scorecard handoff, including
exact bundle/matrix/challenge digest bindings, conjunctive gate evidence and
non-authoritative `NOT_EVALUATED` state.

That issuer-selection scorecard handoff audit is now complete as a test-only
contract. The scorecard declares a closed six-field handoff for scorecard,
independence, bundle, conflict-matrix and issuer-challenge digests plus the
review domain. Cross-contract checks prevent drift in those names. The evaluator
requires the exact common/option-specific gate inventories, canonical digest
evidence for every gate, minimum evidence cardinality and conjunctive `PASS`;
omitted/extra gates, invalid states or missing evidence fail closed. The frozen
state remains `NOT_EVALUATED`, no candidate is selected, and no issuer,
authentication, crypto or runtime authority exists.

Next safe E5 slice: audit the final non-authoritative issuer-selection decision
boundary, including tie-rule handling, immutable `selected_option:null` and
prevention of synthetic all-pass state from granting capability.

That final issuer-selection decision boundary is now complete as a test-only
contract. It exposes only four non-authoritative outcomes: `NOT_EVALUATED`,
single-candidate review required, tie requiring a separate ADR, or blocked
invalid state. Automatic selection is forbidden; selected-option, current-state
and capability-flag drift fail closed, and synthetic all-pass input never grants
issuer authentication, crypto calls or runtime integration.

Next safe E5 slice: audit the immutable non-authoritative result envelope for
this decision, including outcome/context digest binding and replay/freshness
limits before any future owner decision can be consumed.

That immutable decision-result envelope audit is now complete as a test-only
contract. The closed schema binds the canonical result self-digest, exact
scorecard handoff/context and all source digests, enforces outcome/candidate
rules with `selected_option:null`, and rejects extra/missing fields, context or
digest drift, stale/future/overlong timestamps and replayed decision IDs or
caller nonces. The envelope remains non-authoritative with selection, issuer,
crypto and runtime flags false.

Next safe E5 slice: audit the explicit owner/independent-reviewer decision
handoff boundary, keeping the result envelope evidence-only and production
selection blocked.

That owner/reviewer decision handoff audit is now complete as the final keyless
preparation slice. The closed handoff binds the exact immutable decision-result,
context and scorecard digests; separates accountable-owner and independent-
reviewer identities, trust domains and assertion digests; and enforces distinct
roles, 24-hour freshness, future skew, single-use handoff ID/nonce and immutable
self-digest. Structural validity is explicitly separate from consumability:
conflicting decisions and even synthetic `ACCEPT` pairs remain evidence-only
because owner/reviewer authentication and every authority flag are false.

Next canonical item: obtain a real authenticated accountable-owner plus
independent-reviewer decision over the exact current envelope. This is
`BLOCKED_OWNER`; no further design-only selection or production action is
authorized until that evidence exists.

The owner/reviewer item is now under the restrictive deferral
`docs/e5-issuer-selection-owner-reviewer-deferral.v1.json`. The deferral binds
the exact decision-result schema, owner/reviewer handoff schema and scorecard
by SHA-256, keeps every authority flag false, and permits only keyless,
read-only, non-production documentation/tests. Conversation context is not an
authenticated owner or reviewer decision.

The bounded keyless continuation has now completed the persistence/fault
boundary in ADR-0030 and the retention/deletion boundary in ADR-0031. Together
they freeze atomic audit/state commits, compare-and-set, single invocation of
uncertain external effects, `UNKNOWN_REVIEW` recovery, hash-only retention,
content-bound deletion receipts, single-use receipt ID/caller nonce, complete
inventory and independent witness requirements. Partial/unknown outcomes and
missing checkpoint or physical-erasure proof remain blocking; no store,
deletion effect, crypto call or runtime authority exists. The E5
owner/reviewer decision remains the canonical production-selection blocker.
