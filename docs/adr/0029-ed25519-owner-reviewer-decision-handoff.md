# ADR 0029: Accountable-owner and independent-reviewer decision handoff

Date: 2026-08-22

Status: structural handoff frozen; authenticated acceptance blocked

The immutable decision-result envelope is evidence only. Before any future
selection decision could be consumed, an accountable owner and an independent
reviewer must address the exact result and context. This ADR defines the
closed, hash-only handoff shape without creating an owner, reviewer, key,
credential or acceptance authority.

The handoff binds the exact decision-result digest, context-handoff digest and
selection-scorecard digest. It carries separate accountable-owner and
independent-reviewer roles, identities, trust domains, decision values and
assertion digests. Owner and reviewer identities/domains must differ from each
other and from the reviewed subject domain; assertion digests must be distinct.
The handoff self-digest covers every other field.

Handoff IDs and caller nonces are single-use. Issue/expiry is bounded to 24
hours with one-second future skew. Extra or missing fields, context/result
drift, role or domain reuse, assertion reuse, stale/future/overlong timestamps
and replay fail closed. A conflicting owner/reviewer decision is retained as
evidence only and cannot become acceptance.

The current contract deliberately fixes owner authentication, independent
reviewer authentication, decision acceptance, production authorization,
selection, crypto calls and runtime integration to false. A structurally valid
synthetic handoff is therefore not consumable. Real authenticated owner and
reviewer evidence over an exact current envelope remains the owner-gated next
step.
