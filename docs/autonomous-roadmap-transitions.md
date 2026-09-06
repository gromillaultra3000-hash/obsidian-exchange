# Autonomous canonical stage transitions

Owner decision: 2026-09-06, “включи переход к остальным этапам тоже”. This
supersedes the E4-only supervisor scope. The canonical product definition and
all E0–E5 gates remain in `ecosystem-master-roadmap.md`.

Finish the interrupted E4 browser-review slice first. Then choose exactly one
next canonical item. Every stage change requires a checked-in JSON artifact
with this contract; reference its path as `transition_evidence` and include it
in the receipt's `evidence_paths`:

- `schemaVersion`: `autonomy-route-transition.v1`.
- `fromStage`: the receipt's active stage, `E0` through `E5`.
- `toStage`: stage in `next_step`, or `COMPLETE` for entire-route completion.
- `roadmapSha256`: SHA-256 of the current canonical roadmap bytes.
- `reason`: concrete reason this next item follows the canonical route.
- `gateAssessments`: exactly six objects ordered E0, E1, E2, E3, E4, E5. Each
  has `stage`, `status` and nonempty `evidencePaths` referencing committed
  regular files in `docs/`. The transition artifact cannot cite itself as gate
  proof. Allowed statuses: `VERIFIED`, `IN_PROGRESS`, `NOT_STARTED`,
  `BLOCKED_OWNER`, `BLOCKED_EXTERNAL`.
- `basis` and `scope` follow one of the choices below.

| Basis | Required meaning | Scope |
|---|---|---|
| `RETURN_TO_EARLIEST` | Target is earlier than active stage and is the first unverified gate in E0–E5 order. | `EXISTING_AUTHORITY` |
| `VERIFIED_GATE_ADVANCE` | Target is later and every preceding mandatory stage is `VERIFIED`, supported by acceptance evidence. | `EXISTING_AUTHORITY` |
| `PREPARATION_UNDER_BLOCKER` | Earliest unmet stage is `BLOCKED_OWNER` or `BLOCKED_EXTERNAL`; target is later. Include a nonempty `blocker` and literal `productionAllowed: false`. | `KEYLESS_NONPRODUCTION` |
| `ROADMAP_COMPLETE` | All six mandatory stages are `VERIFIED`; target and receipt status are `COMPLETE`. | Terminal; no next iteration. |

For same-stage continuation, `transition_evidence` may be empty; the current
scope persists. A keyless preparation iteration does not regain production
authority merely by continuing in the same stage. The controller passes the
scheduled stage/scope into the next invocation, and a receipt naming another
active stage is rejected. The initial handoff remains scheduled E4.

An assessment is an evidence-backed report, not a waiver. Code, passing tests
or this JSON alone cannot close a production gate. Independent reviews must
check the claimed acceptance evidence and next item's dependencies. Unknown
readiness remains unverified. Existing credentials, money, signing, custody,
provider/legal and rollout/rollback requirements remain in force; full roadmap
scope grants no new money action or credential. 064A remains frozen without a
separate exact decision and fresh authorized ceremony.

The frozen E0.3/064A prerequisite and E1 credential lifecycle currently prevent
claiming ordinary production progression through all stages. Explicitly
labelled later preparation is allowed within the boundary above. If no useful
authorized code-first slice remains, report `BLOCKED`; do not run an endless
documentation or synthetic-contract loop. `COMPLETE` never means only E4 is
finished.
