# ADR 0032: Independent audit checkpoints

Date: 2026-08-15

Status: envelope and rollback policy frozen; authentication unselected

ADR 0031 notes that a locally valid hash chain cannot prove it was not truncated
or replaced. This record freezes a closed independent checkpoint envelope. It
binds a consumer-selected chain and policy, exact audit sequence/head, previous
checkpoint, monotonic epoch, single-use caller nonce, ten-minute window and
exactly two external authentication-evidence digests.

The two witness domains must differ by identity, authentication root, recovery
authority, host failure domain and evidence digest. Neither may control the
audit store. Distinct strings remain only structural evidence; authenticated
control registries and the ADR 0027 conflict matrix are still required.

Validation is ordered and fail-closed: parse and bind chain/policy; authenticate
both domains; verify nonce and time; reject epoch/sequence rollback; require the
previous checkpoint digest; compare the local audit sequence/head; then atomically
consume the nonce and advance the highest accepted epoch, sequence and checkpoint.
Lower/equal sequence, lower epoch, wrong predecessor, local mismatch, future/
expired time or nonce reuse rejects. Same sequence with another head is explicit
equivocation and blocks gate `i09`.

Authentication candidates are dual independent DSSE witnesses, dual human
WebAuthn witnesses, and a supplemental split design with one DSSE witness plus
separately rooted transparency inclusion. None is selected. Checkpoints make
post-observation rollback detectable; they cannot prove that events omitted
before observation ever existed.

No witness, root, log, RP, nonce/high-water store, verifier or checkpoint exists.
Checkpoint acceptance, gate `i09`, issuer/verifier selection, crypto calls and
runtime/UniFFI integration remain false.
