# Operational ownership registry

The authoritative E0.3 inventory is
`docs/operational-ownership.v1.json`. It records metadata and references only;
no secret value or customer row was inspected.

The registry assigns exactly one accountable operational role to every listed
datastore, secret-reference group and effectful writer. The project owner
accepted this map on 2026-08-15 and remains the sole accountable principal and
escalation authority until a written delegation names a person/team, scope and
acceptance. Workloads are not owners. `UNKNOWN`, `PARTIAL`, `OVERBROAD`, shared
DML and root-principal findings remain explicit.

## Current material gaps

- Relay and bot share `obsidian_app`, which has DML across the full PostgreSQL
  schema; repositories constrain code but the database role does not enforce
  logical writer ownership.
- Bot, notifier, monitor, support and Laravel admin still run as root.
- The shared `app.env` distributes unrelated bot, payment, relay and provider
  secret domains to four processes. `secret-reference-members.v1.json` now
  records the variable-name-only membership; splitting it remains open.
- Notifier is confirmed on broad `obsidian_app`, and the dormant shadow unit
  template inherits the same overpowered application credential.
- Most datasets lack approved retention, subject deletion, backup destination,
  restore cadence and expiry.
- KAIROS contains dormant CEX money capability, but no enabled product execution
  route or active user credential is evidenced.

## Verified metadata boundary

Point-in-time `systemctl show` and filesystem metadata confirmed only paths,
service consumers, Unix principals and modes. Secret values were not read.
Relay identity keys are `root:relay-svc 0640`; KAIROS vault/trust material is
`root:kairos-svc 0640`; primary Obsidian environment files are `root:root 0600`.
The read-only PostgreSQL verifier also reports the declared ACL matrix as a
match (54 tables, 29 sequences and two functions); this proves conformance, not
least privilege.

## Scope

This registry makes ownership and lifecycle gaps visible. Owner assignments are
accepted; coverage and control implementation remain `IN_PROGRESS`. It does not
remediate shared privileges, root services or unknown retention. E0.3 remains
`IN_PROGRESS` until coverage and deployed controls are independently validated
against runtime definitions; closing overall E0 additionally requires the later
control gaps and E0.4 surface inventory to be resolved.
