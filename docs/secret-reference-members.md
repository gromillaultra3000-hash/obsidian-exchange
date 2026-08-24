# E0.3 secret-reference member inventory

`secret-reference-members.v1.json` is the authoritative metadata-only snapshot. It records variable names, file references, consumers and sanitized PostgreSQL role names; it contains no credential values.

The snapshot is deliberately `IN_PROGRESS`. Accountable-role labels remain proposals, the shared `app.env` exposes unrelated provider credentials to several processes, notifier still receives the broad `obsidian_app` role, and rotation/revocation/expiry evidence is mostly unknown. Active and staged PostgreSQL bindings are explicit so staged copies cannot disappear from lifecycle accounting.

`LUMI_KAIROS_TOKEN` is one logical two-endpoint credential, not two independently owned secrets. KAIROS request signing and LUMI response signing remain separate custody domains. Public verification keyrings are trust material, not secrets.

This artifact advances E0.3 but does not verify it. Verification still requires complete coverage, accepted human/team accountability, lifecycle decisions, and independent runtime/grant evidence.
