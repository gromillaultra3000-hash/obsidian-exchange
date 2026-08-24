# E0.3 accountability-map owner decision

Decision date: 2026-08-15 UTC
Decision authority: project owner
Status: ACCEPTED

The project owner explicitly accepts the accountable-role labels in
`docs/operational-ownership.v1.json` and
`docs/secret-reference-members.v1.json`.

Until a separate written delegation is recorded, the project owner is the sole
accountable principal and escalation/decision authority for every accepted
role. Service accounts, Unix users, applications, agents and automated workers
are technical consumers or executors; they are not accountable owners.

Future delegation must identify the person or team, date, exact role/scope and
explicit acceptance. Delegation does not weaken custody, safety, legal,
least-privilege, audit or owner-approval requirements.

This decision accepts accountability. It does not assert that retention,
rotation, revocation, backup, deletion or least-privilege controls are already
implemented, and it does not authorize production deployment or restart.
