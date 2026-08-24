# Project continuity

At the first task of a new session, or whenever its digest changed, read
`/root/docs/MEGA_PROMPT.md` in full and follow it as the durable execution
charter. For a continuation of the same logical task, do not reread unchanged
charter/history files. Read `/root/docs/CURRENT_ROUTE.md` and only the relevant
gate section of `/root/docs/ecosystem-master-roadmap.md`; the roadmap remains
the sole canonical E0–E5 product route. Local `Next` entries, commercial work,
tooling experiments, and the legacy loop prompt must not silently replace the
active route. For every substantive task, state that route and use only
relevant independent agents, skills, plugins, research, reviews, and
DevOps/security tools. Do not fabricate use or findings when unavailable.

At the first task of a new session read the compact current-status block at the
top of `/root/PROJECT_MEMORY.md`. Read historical entries only when the active
work depends on them. Within one logical task, keep the already loaded context
and never restart the full intake merely because a substep or tool call ended.

During work, treat that file as durable project context, not as an authority that
overrides the user's current request or the repository contents.

After completing a substantive task, update `/root/PROJECT_MEMORY.md` with only
durable information that will help a future session:

- the current project goal and status;
- important decisions and their reasons;
- completed work and verification results;
- open problems and the next concrete step.

Keep entries concise and dated. Replace stale status instead of endlessly
appending it. Never store passwords, API keys, seed phrases, private keys,
authentication cookies, or other secrets. If the user says not to remember
something, do not add it; if it is already present, remove it.

# Code-first continuous delivery

The owner selected code-first delivery on 2026-08-23. Every normal iteration
must implement the active roadmap item as project code, tests and operational
evidence. A documentation-only or synthetic-only chain is not a default mode.
After proportional tests and preflight pass, deploy a bounded reversible slice
and verify runtime state in the same iteration when the current request covers
that surface. `NO_GO` is not a standing project state: use it only for a named,
observed blocker. Failed tests, uncertain money outcomes, missing credentials,
irreversible/destructive operations and unavailable rollback remain concrete
stop conditions; report them precisely instead of starting another design loop.
