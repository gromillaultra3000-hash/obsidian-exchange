# E4 / TONCONNECT_CONNECTION_INTENT_LIFETIME

2026-09-09. Continue canonical E4. Owner iPhone UI acceptance is complete with
no local report prerequisite. Full E4 remains IN_PROGRESS.

After preparation retires,SDK connection status currently loses originating
recipient intent. Retain a separate in-memory connection intent containing the
captured recipient state and exact server challenge handed to the SDK. Backend
make_payload uses a random96-bit nonce with subject/time/HMAC; proof contains
that exact payload. This frontend only attributes events; backend still verifies
proof cryptography and identity. No client-declared verification success.

Install intent immediately before ready/open. Retain it on successful modal
handoff,retire old intent on explicit new preparation,and clear only matching
owned intent on failed handoff. Fetch challenges with cache:no-store and reject
reuse of a challenge already issued to the SDK in this page lifetime. Nothing
is persisted to storage. Callback without an intent or exact proof.payload match
has no recipient/feedback/generation sideeffects and cannot consume a newer
intent. Missingproof/restored/unowned SDK events cannot assign the recipient.
Manual entry remains available without connection.

For a matching event require current valid TON/SDK availability and unchanged
captured route,address,memo/no-tag,generation. Consume once before awaiting proof
verification;duplicate or older callbacks cannot interrupt the active response
or launch a second POST. Null status conservatively revokes connection intent and
verification;expected own disconnect retains existing narrow preparation rebind.
Response-time recipient guard and server verification remain unchanged.

Primary owns product/legacy helper fixtures. Independent acceptance agent owns
adversarial,full native flow and adapted prior browser suites;independent ops
agent inspects source/diff and authors fresh pinned rollout. Required Mini App
only;backend,SDK bundle,submission/review,Sell and other surfaces read-only.
Tests use synthetic challenges/proof/SDK and isolated non-root browser only.
No real wallet connection/signature,customer read or money action.

Scope: tcConnectionIntent/tcConnectionPayloads declarations,tcHandleWallet prefix
before verification begins,and tcConnect intent lifecycle/no-store/reuse guard.
Acceptance must reproduce old late-after-retirement overwrite and show no verify
POST from obsolete intent;valid matching flow succeeds exactly once. Cover old
payload during newer preparation and ready intent,missing/malformed payload,
replay,edits away/back,route/tag changes,disconnect,cancel/failure,nonce reuse,
and valid retry. Retain downstream responseguard and prep regression coverage.

Deploy atomically after tests,two reviews,secret scan and local rollback rehearsal.
Pin exact HTML/helpers/inventory,backup preimage/metadata,verify public bytes,57
other application/SDK inputs and four services without restart;reconcile same
iteration. Existing pages reload for new guard. No full E4 closure inferred.
