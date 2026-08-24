//! Narrow Swift/Kotlin boundary for non-signing wallet preview drafts.

#![forbid(unsafe_code)]

use obsidian_wallet_core::{
    ApprovalSignatureClaim as CoreApprovalSignatureClaim,
    CheckpointApprovalRequest as CoreCheckpointApprovalRequest,
    CheckpointArtifactRequest as CoreCheckpointArtifactRequest,
    HeaderChainRequest as CoreHeaderChainRequest, KeyLifecycleError as CoreLifecycleError,
    KeyRevocationRequest as CoreRevocationRequest, KeyRotationRequest as CoreRotationRequest,
    PreviewError as CoreError, PreviewInputRequest as CoreInputRequest,
    PreviewOutputRequest as CoreOutputRequest,
    TrustKeyCeremonyRequest as CoreTrustKeyCeremonyRequest,
    UtxoEvidenceRequest as CoreEvidenceRequest, build_signet_preview,
    checkpoint_signature_algorithm_selection, review_key_lifecycle,
};
use std::fmt;

uniffi::setup_scaffolding!();

/// FFI-safe epoch-two rotation proposal.
#[derive(Clone, Debug, Eq, PartialEq, uniffi::Record)]
pub struct KeyRotationRequest {
    /// Frozen schema.
    pub schema: String,
    /// Predecessor ceremony digest.
    pub predecessor_ceremony_sha256: String,
    /// Source epoch.
    pub from_epoch: u32,
    /// Destination epoch.
    pub to_epoch: u32,
    /// Existing key slots.
    pub old_key_ids: Vec<String>,
    /// Proposed new key slots.
    pub new_key_ids: Vec<String>,
    /// Proposed external key-material commitments.
    pub new_key_material_sha256: Vec<String>,
    /// Rotation participant identifiers.
    pub participant_ids: Vec<String>,
    /// Rotation transcript digests.
    pub transcript_sha256: Vec<String>,
    /// Future activation time.
    pub effective_at_epoch_ms: u64,
    /// Canonical proposal digest.
    pub content_sha256: String,
}

/// FFI-safe emergency revocation proposal.
#[derive(Clone, Debug, Eq, PartialEq, uniffi::Record)]
pub struct KeyRevocationRequest {
    /// Frozen schema.
    pub schema: String,
    /// Predecessor ceremony digest.
    pub predecessor_ceremony_sha256: String,
    /// Current epoch.
    pub epoch: u32,
    /// Proposed revoked key slots.
    pub revoked_key_ids: Vec<String>,
    /// Allowlisted reason code.
    pub reason_code: String,
    /// Independent observer identifiers.
    pub observer_ids: Vec<String>,
    /// Revocation evidence digests.
    pub evidence_sha256: Vec<String>,
    /// Proposal creation time.
    pub created_at_epoch_ms: u64,
    /// Proposal expiry.
    pub expires_at_epoch_ms: u64,
    /// Canonical proposal digest.
    pub content_sha256: String,
}

/// FFI-safe non-executing lifecycle review.
#[derive(Clone, Debug, Eq, PartialEq, uniffi::Record)]
#[allow(
    clippy::struct_excessive_bools,
    reason = "native UI receives explicit non-execution claims"
)]
pub struct KeyLifecycleReview {
    /// Frozen review schema.
    pub schema: String,
    /// Validated rotation digest.
    pub rotation_sha256: String,
    /// Validated revocation digest.
    pub revocation_sha256: String,
    /// Rotation content binding result.
    pub rotation_content_bound: bool,
    /// Revocation content binding result.
    pub revocation_content_bound: bool,
    /// Always false.
    pub execution_allowed: bool,
    /// Always false.
    pub keys_changed: bool,
    /// Always false.
    pub algorithm_selected: bool,
}

/// FFI-safe, inert checkpoint-signature algorithm selection.
#[derive(Clone, Debug, Eq, PartialEq, uniffi::Record)]
#[allow(clippy::struct_excessive_bools, reason = "explicit capability claims")]
pub struct CheckpointSignatureAlgorithmSelection {
    /// Frozen contract schema.
    pub schema: String,
    /// Exact algorithm profile.
    pub algorithm: String,
    /// Normative specification identifier.
    pub specification: String,
    /// Application message domain.
    pub message_domain: String,
    /// Locked direct dependency version.
    pub rust_bitcoin_version: String,
    /// Locked verification library version.
    pub rust_secp256k1_version: String,
    /// Locked native binding version.
    pub rust_secp256k1_sys_version: String,
    /// Encoded x-only key length.
    pub xonly_public_key_bytes: u32,
    /// Encoded signature length.
    pub signature_bytes: u32,
    /// Required message digest length.
    pub message_digest_bytes: u32,
    /// Whether official vectors gate implementation.
    pub official_test_vectors_required: bool,
    /// Whether verification code exists.
    pub verifier_implemented: bool,
    /// Whether verification is activated.
    pub verifier_enabled: bool,
    /// Whether trust keys are installed.
    pub trust_keys_installed: bool,
    /// Whether checkpoint trust is established.
    pub checkpoint_trusted: bool,
    /// Whether chain verification is established.
    pub chain_verified: bool,
    /// Whether signing is exposed.
    pub signing_available: bool,
}

/// Exposes the frozen selection without installing keys or enabling verification.
#[uniffi::export]
#[must_use]
pub fn checkpoint_signature_algorithm_selection_draft() -> CheckpointSignatureAlgorithmSelection {
    let selection = checkpoint_signature_algorithm_selection();
    CheckpointSignatureAlgorithmSelection {
        schema: selection.schema.to_owned(),
        algorithm: selection.algorithm.to_owned(),
        specification: selection.specification.to_owned(),
        message_domain: selection.message_domain.to_owned(),
        rust_bitcoin_version: selection.rust_bitcoin_version.to_owned(),
        rust_secp256k1_version: selection.rust_secp256k1_version.to_owned(),
        rust_secp256k1_sys_version: selection.rust_secp256k1_sys_version.to_owned(),
        xonly_public_key_bytes: selection.xonly_public_key_bytes,
        signature_bytes: selection.signature_bytes,
        message_digest_bytes: selection.message_digest_bytes,
        official_test_vectors_required: selection.official_test_vectors_required,
        verifier_implemented: false,
        verifier_enabled: false,
        trust_keys_installed: false,
        checkpoint_trusted: false,
        chain_verified: false,
        signing_available: false,
    }
}

/// FFI-safe immutable preview returned to native UI shells.
#[derive(Clone, Debug, Eq, PartialEq, uniffi::Record)]
pub struct PreviewDraft {
    /// Frozen schema identifier.
    pub schema: String,
    /// Always `BITCOIN_SIGNET` in this slice.
    pub network: String,
    /// Lowercase SHA-256 binding to unsigned bytes.
    pub unsigned_payload_sha256: String,
    /// Bitcoin transaction version; always two in this slice.
    pub transaction_version: i32,
    /// Consensus lock time.
    pub lock_time: u32,
    /// Canonically ordered validated input metadata.
    pub inputs: Vec<PreviewInputDraft>,
    /// Total value of selected inputs.
    pub total_input_sats: u64,
    /// Canonically ordered validated outputs.
    pub outputs: Vec<PreviewOutputDraft>,
    /// Fee derived from inputs minus outputs.
    pub fee_sats: u64,
    /// Preview expiry.
    pub expires_at_epoch_ms: u64,
    /// Honest validation level; validated drafts are still not signable.
    pub destination_validation: String,
    /// Always false.
    pub signing_allowed: bool,
    /// Always false.
    pub production_action_allowed: bool,
}

/// FFI-safe untrusted input request.
#[derive(Clone, Debug, Eq, PartialEq, uniffi::Record)]
pub struct PreviewInputRequest {
    /// Canonical lowercase previous transaction ID.
    pub previous_txid: String,
    /// Previous output index.
    pub previous_vout: u32,
    /// Selected input value in satoshis.
    pub amount_sats: u64,
    /// Consensus sequence value.
    pub sequence: u32,
    /// Content-bound external observation for this input.
    pub evidence: UtxoEvidenceRequest,
}

/// FFI-safe untrusted UTXO evidence request.
#[derive(Clone, Debug, Eq, PartialEq, uniffi::Record)]
pub struct UtxoEvidenceRequest {
    /// Exact allowlisted source contract.
    pub source: String,
    /// Observed Signet block height.
    pub block_height: u32,
    /// Canonical lowercase observed block hash.
    pub block_hash: String,
    /// Previous output scriptPubKey as lowercase hex.
    pub previous_script_pubkey_hex: String,
    /// Consensus-encoded `MerkleBlock` proof as lowercase hex.
    pub merkle_proof_hex: String,
    /// External checkpoint and bounded contiguous header chain.
    pub header_chain: HeaderChainRequest,
    /// Observation time.
    pub observed_at_epoch_ms: u64,
    /// Canonical evidence SHA-256.
    pub content_sha256: String,
}

/// FFI-safe untrusted bounded header-chain request.
#[derive(Clone, Debug, Eq, PartialEq, uniffi::Record)]
pub struct HeaderChainRequest {
    /// Exact unreviewed-checkpoint contract kind.
    pub checkpoint_kind: String,
    /// External checkpoint height.
    pub checkpoint_height: u32,
    /// Canonical external checkpoint hash.
    pub checkpoint_hash: String,
    /// One to 144 consensus headers as lowercase hex.
    pub headers_hex: Vec<String>,
    /// Content-bound independent-review claims.
    pub checkpoint_artifact: CheckpointArtifactRequest,
    /// Content-bound 2-of-3 approval proposal.
    pub checkpoint_approval: CheckpointApprovalRequest,
}

/// FFI-safe approval proposal without signature verification.
#[derive(Clone, Debug, Eq, PartialEq, uniffi::Record)]
pub struct CheckpointApprovalRequest {
    /// Frozen proposal schema.
    pub schema: String,
    /// Exact policy identifier.
    pub policy: String,
    /// Bound review artifact digest.
    pub checkpoint_artifact_sha256: String,
    /// Design-only trust-key ceremony proposal.
    pub trust_key_ceremony: TrustKeyCeremonyRequest,
    /// Three distinct sorted signer key identifiers.
    pub signer_key_ids: Vec<String>,
    /// Two distinct sorted signature digest claims.
    pub signature_claims: Vec<ApprovalSignatureClaim>,
    /// Proposal expiry.
    pub expires_at_epoch_ms: u64,
    /// Canonical proposal digest.
    pub content_sha256: String,
}

/// FFI-safe initial trust-key ceremony proposal without real keys.
#[derive(Clone, Debug, Eq, PartialEq, uniffi::Record)]
pub struct TrustKeyCeremonyRequest {
    /// Frozen ceremony schema.
    pub schema: String,
    /// Initial epoch.
    pub epoch: u32,
    /// Must remain `UNDECIDED`.
    pub algorithm: String,
    /// Three opaque key slot identifiers.
    pub key_ids: Vec<String>,
    /// Three external key-material commitments.
    pub key_material_sha256: Vec<String>,
    /// Three ceremony participant identifiers.
    pub participant_ids: Vec<String>,
    /// Two transcript digests.
    pub transcript_sha256: Vec<String>,
    /// Ceremony time.
    pub created_at_epoch_ms: u64,
    /// Empty in initial epoch.
    pub predecessor_keyset_sha256: String,
    /// Empty in initial epoch.
    pub revoked_key_ids: Vec<String>,
    /// Canonical ceremony digest.
    pub content_sha256: String,
}

/// FFI-safe opaque signature digest claim.
#[derive(Clone, Debug, Eq, PartialEq, uniffi::Record)]
pub struct ApprovalSignatureClaim {
    /// Opaque signer key identifier.
    pub signer_key_id: String,
    /// SHA-256 of external signature bytes.
    pub signature_sha256: String,
}

/// FFI-safe untrusted checkpoint review artifact.
#[derive(Clone, Debug, Eq, PartialEq, uniffi::Record)]
pub struct CheckpointArtifactRequest {
    /// Frozen artifact schema.
    pub schema: String,
    /// Exact network identifier.
    pub network: String,
    /// Bound checkpoint height.
    pub checkpoint_height: u32,
    /// Bound checkpoint hash.
    pub checkpoint_hash: String,
    /// Two distinct sorted source digests.
    pub source_sha256: Vec<String>,
    /// Two distinct sorted opaque reviewer identifiers.
    pub reviewer_ids: Vec<String>,
    /// Review timestamp.
    pub reviewed_at_epoch_ms: u64,
    /// Canonical artifact digest.
    pub content_sha256: String,
}

/// FFI-safe validated input displayed to the user.
#[derive(Clone, Debug, Eq, PartialEq, uniffi::Record)]
pub struct PreviewInputDraft {
    /// Canonical lowercase previous transaction ID.
    pub previous_txid: String,
    /// Previous output index.
    pub previous_vout: u32,
    /// Selected input value in satoshis.
    pub amount_sats: u64,
    /// Consensus sequence value.
    pub sequence: u32,
    /// Validated content binding, not chain verification.
    pub evidence: UtxoEvidenceDraft,
}

/// FFI-safe validated evidence displayed without a chain-verification claim.
#[derive(Clone, Debug, Eq, PartialEq, uniffi::Record)]
pub struct UtxoEvidenceDraft {
    /// Frozen evidence schema.
    pub schema: String,
    /// Allowlisted source contract.
    pub source: String,
    /// Observed Signet block height.
    pub block_height: u32,
    /// Canonical lowercase observed block hash.
    pub block_hash: String,
    /// Previous output scriptPubKey as lowercase hex.
    pub previous_script_pubkey_hex: String,
    /// SHA-256 of the validated Merkle proof bytes.
    pub merkle_proof_sha256: String,
    /// Locally checked linkage with explicit trust limitations.
    pub header_chain: HeaderChainDraft,
    /// Observation time.
    pub observed_at_epoch_ms: u64,
    /// Recomputed canonical evidence SHA-256.
    pub content_sha256: String,
    /// Honest validation level for UI display.
    pub validation: String,
    /// True when the proof includes the exact previous TXID.
    pub transaction_inclusion_verified: bool,
    /// Always false in this offline slice.
    pub chain_verified: bool,
}

/// FFI-safe validated header linkage which does not establish chain trust.
#[derive(Clone, Debug, Eq, PartialEq, uniffi::Record)]
#[allow(
    clippy::struct_excessive_bools,
    reason = "native UI receives explicit independent trust claims"
)]
pub struct HeaderChainDraft {
    /// External checkpoint height.
    pub checkpoint_height: u32,
    /// Canonical external checkpoint hash.
    pub checkpoint_hash: String,
    /// Number of linked headers.
    pub header_count: u32,
    /// True when the sequence is contiguous and ends at the proof block.
    pub linkage_verified: bool,
    /// Always false until a reviewed checkpoint is pinned.
    pub checkpoint_trusted: bool,
    /// Honest limitation exposed to native UI.
    pub validation: String,
    /// Validated artifact content digest.
    pub checkpoint_artifact_sha256: String,
    /// True when two independent claims are structurally content-bound.
    pub independent_review_claims_bound: bool,
    /// Fixed current consensus capability.
    pub consensus_capability: String,
    /// Canonical approval proposal digest.
    pub checkpoint_approval_sha256: String,
    /// True when the proposal is structurally content-bound.
    pub approval_proposal_content_bound: bool,
    /// Always false until signatures are cryptographically verified.
    pub approval_signatures_verified: bool,
    /// Canonical trust-key ceremony digest.
    pub trust_key_ceremony_sha256: String,
    /// True when ceremony claims are structurally content-bound.
    pub trust_key_ceremony_content_bound: bool,
    /// Always false in this slice.
    pub trust_keys_installed: bool,
    /// Always false while algorithm is undecided.
    pub trust_key_algorithm_selected: bool,
}

/// FFI-safe untrusted output request.
#[derive(Clone, Debug, Eq, PartialEq, uniffi::Record)]
pub struct PreviewOutputRequest {
    /// Signet destination text.
    pub destination: String,
    /// Exact output value in satoshis.
    pub amount_sats: u64,
}

/// FFI-safe validated output displayed to the user.
#[derive(Clone, Debug, Eq, PartialEq, uniffi::Record)]
pub struct PreviewOutputDraft {
    /// Canonical Signet destination.
    pub destination: String,
    /// Exact destination scriptPubKey as lowercase hex.
    pub script_pubkey_hex: String,
    /// Exact output value in satoshis.
    pub amount_sats: u64,
}

/// Stable lifecycle validation error for Swift and Kotlin.
#[derive(Debug, uniffi::Error)]
pub enum KeyLifecycleDraftError {
    /// Proposal failed a frozen validation rule.
    Rejected {
        /// Stable reason without key material.
        reason: String,
    },
}

impl fmt::Display for KeyLifecycleDraftError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Rejected { reason } => write!(formatter, "key lifecycle rejected: {reason}"),
        }
    }
}

impl std::error::Error for KeyLifecycleDraftError {}

impl From<CoreLifecycleError> for KeyLifecycleDraftError {
    fn from(error: CoreLifecycleError) -> Self {
        Self::Rejected {
            reason: error.to_string(),
        }
    }
}

/// Reviews lifecycle proposals without installing, revoking or rotating keys.
///
/// # Errors
///
/// Returns [`KeyLifecycleDraftError`] when either proposal violates its frozen
/// content, ordering, independence, epoch or timing contract.
#[uniffi::export]
#[allow(clippy::needless_pass_by_value, reason = "UniFFI owns foreign values")]
pub fn review_key_lifecycle_draft(
    predecessor_ceremony_sha256: String,
    predecessor_key_ids: Vec<String>,
    rotation: KeyRotationRequest,
    revocation: KeyRevocationRequest,
    now_epoch_ms: u64,
) -> Result<KeyLifecycleReview, KeyLifecycleDraftError> {
    let core_rotation = CoreRotationRequest {
        schema: rotation.schema,
        predecessor_ceremony_sha256: rotation.predecessor_ceremony_sha256,
        from_epoch: rotation.from_epoch,
        to_epoch: rotation.to_epoch,
        old_key_ids: rotation.old_key_ids,
        new_key_ids: rotation.new_key_ids,
        new_key_material_sha256: rotation.new_key_material_sha256,
        participant_ids: rotation.participant_ids,
        transcript_sha256: rotation.transcript_sha256,
        effective_at_epoch_ms: rotation.effective_at_epoch_ms,
        content_sha256: rotation.content_sha256,
    };
    let core_revocation = CoreRevocationRequest {
        schema: revocation.schema,
        predecessor_ceremony_sha256: revocation.predecessor_ceremony_sha256,
        epoch: revocation.epoch,
        revoked_key_ids: revocation.revoked_key_ids,
        reason_code: revocation.reason_code,
        observer_ids: revocation.observer_ids,
        evidence_sha256: revocation.evidence_sha256,
        created_at_epoch_ms: revocation.created_at_epoch_ms,
        expires_at_epoch_ms: revocation.expires_at_epoch_ms,
        content_sha256: revocation.content_sha256,
    };
    let review = review_key_lifecycle(
        &predecessor_ceremony_sha256,
        &predecessor_key_ids,
        &core_rotation,
        &core_revocation,
        now_epoch_ms,
    )?;
    Ok(KeyLifecycleReview {
        schema: review.schema.to_owned(),
        rotation_sha256: review.rotation_sha256,
        revocation_sha256: review.revocation_sha256,
        rotation_content_bound: review.rotation_content_bound,
        revocation_content_bound: review.revocation_content_bound,
        execution_allowed: false,
        keys_changed: false,
        algorithm_selected: false,
    })
}

/// Stable error surface for Swift and Kotlin.
#[derive(Debug, uniffi::Error)]
pub enum PreviewDraftError {
    /// The request failed a frozen validation rule.
    Rejected {
        /// Stable human-readable validation reason; contains no request secrets.
        reason: String,
    },
}

impl fmt::Display for PreviewDraftError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Rejected { reason } => write!(formatter, "preview request rejected: {reason}"),
        }
    }
}

impl std::error::Error for PreviewDraftError {}

impl From<CoreError> for PreviewDraftError {
    fn from(error: CoreError) -> Self {
        Self::Rejected {
            reason: error.to_string(),
        }
    }
}

/// Creates a display draft only; no key, signing, storage or network exists.
///
/// # Errors
///
/// Returns [`PreviewDraftError`] when the request violates a wallet-core
/// validation rule.
#[uniffi::export]
#[allow(
    clippy::needless_pass_by_value,
    clippy::too_many_lines,
    reason = "UniFFI owns foreign values and maps the complete explicit trust record"
)]
pub fn create_signet_preview_draft(
    unsigned_payload_sha256: String,
    transaction_version: i32,
    lock_time: u32,
    inputs: Vec<PreviewInputRequest>,
    outputs: Vec<PreviewOutputRequest>,
    created_at_epoch_ms: u64,
    expires_at_epoch_ms: u64,
) -> Result<PreviewDraft, PreviewDraftError> {
    let core_inputs = inputs
        .into_iter()
        .map(|input| CoreInputRequest {
            previous_txid: input.previous_txid,
            previous_vout: input.previous_vout,
            amount_sats: input.amount_sats,
            sequence: input.sequence,
            evidence: CoreEvidenceRequest {
                source: input.evidence.source,
                block_height: input.evidence.block_height,
                block_hash: input.evidence.block_hash,
                previous_script_pubkey_hex: input.evidence.previous_script_pubkey_hex,
                merkle_proof_hex: input.evidence.merkle_proof_hex,
                header_chain: CoreHeaderChainRequest {
                    checkpoint_kind: input.evidence.header_chain.checkpoint_kind,
                    checkpoint_height: input.evidence.header_chain.checkpoint_height,
                    checkpoint_hash: input.evidence.header_chain.checkpoint_hash,
                    headers_hex: input.evidence.header_chain.headers_hex,
                    checkpoint_artifact: CoreCheckpointArtifactRequest {
                        schema: input.evidence.header_chain.checkpoint_artifact.schema,
                        network: input.evidence.header_chain.checkpoint_artifact.network,
                        checkpoint_height: input
                            .evidence
                            .header_chain
                            .checkpoint_artifact
                            .checkpoint_height,
                        checkpoint_hash: input
                            .evidence
                            .header_chain
                            .checkpoint_artifact
                            .checkpoint_hash,
                        source_sha256: input
                            .evidence
                            .header_chain
                            .checkpoint_artifact
                            .source_sha256,
                        reviewer_ids: input.evidence.header_chain.checkpoint_artifact.reviewer_ids,
                        reviewed_at_epoch_ms: input
                            .evidence
                            .header_chain
                            .checkpoint_artifact
                            .reviewed_at_epoch_ms,
                        content_sha256: input
                            .evidence
                            .header_chain
                            .checkpoint_artifact
                            .content_sha256,
                    },
                    checkpoint_approval: CoreCheckpointApprovalRequest {
                        schema: input.evidence.header_chain.checkpoint_approval.schema,
                        policy: input.evidence.header_chain.checkpoint_approval.policy,
                        checkpoint_artifact_sha256: input
                            .evidence
                            .header_chain
                            .checkpoint_approval
                            .checkpoint_artifact_sha256,
                        trust_key_ceremony: CoreTrustKeyCeremonyRequest {
                            schema: input
                                .evidence
                                .header_chain
                                .checkpoint_approval
                                .trust_key_ceremony
                                .schema,
                            epoch: input
                                .evidence
                                .header_chain
                                .checkpoint_approval
                                .trust_key_ceremony
                                .epoch,
                            algorithm: input
                                .evidence
                                .header_chain
                                .checkpoint_approval
                                .trust_key_ceremony
                                .algorithm,
                            key_ids: input
                                .evidence
                                .header_chain
                                .checkpoint_approval
                                .trust_key_ceremony
                                .key_ids,
                            key_material_sha256: input
                                .evidence
                                .header_chain
                                .checkpoint_approval
                                .trust_key_ceremony
                                .key_material_sha256,
                            participant_ids: input
                                .evidence
                                .header_chain
                                .checkpoint_approval
                                .trust_key_ceremony
                                .participant_ids,
                            transcript_sha256: input
                                .evidence
                                .header_chain
                                .checkpoint_approval
                                .trust_key_ceremony
                                .transcript_sha256,
                            created_at_epoch_ms: input
                                .evidence
                                .header_chain
                                .checkpoint_approval
                                .trust_key_ceremony
                                .created_at_epoch_ms,
                            predecessor_keyset_sha256: input
                                .evidence
                                .header_chain
                                .checkpoint_approval
                                .trust_key_ceremony
                                .predecessor_keyset_sha256,
                            revoked_key_ids: input
                                .evidence
                                .header_chain
                                .checkpoint_approval
                                .trust_key_ceremony
                                .revoked_key_ids,
                            content_sha256: input
                                .evidence
                                .header_chain
                                .checkpoint_approval
                                .trust_key_ceremony
                                .content_sha256,
                        },
                        signer_key_ids: input
                            .evidence
                            .header_chain
                            .checkpoint_approval
                            .signer_key_ids,
                        signature_claims: input
                            .evidence
                            .header_chain
                            .checkpoint_approval
                            .signature_claims
                            .into_iter()
                            .map(|claim| CoreApprovalSignatureClaim {
                                signer_key_id: claim.signer_key_id,
                                signature_sha256: claim.signature_sha256,
                            })
                            .collect(),
                        expires_at_epoch_ms: input
                            .evidence
                            .header_chain
                            .checkpoint_approval
                            .expires_at_epoch_ms,
                        content_sha256: input
                            .evidence
                            .header_chain
                            .checkpoint_approval
                            .content_sha256,
                    },
                },
                observed_at_epoch_ms: input.evidence.observed_at_epoch_ms,
                content_sha256: input.evidence.content_sha256,
            },
        })
        .collect::<Vec<_>>();
    let core_outputs = outputs
        .into_iter()
        .map(|output| CoreOutputRequest {
            destination: output.destination,
            amount_sats: output.amount_sats,
        })
        .collect::<Vec<_>>();
    let preview = build_signet_preview(
        &unsigned_payload_sha256,
        transaction_version,
        lock_time,
        &core_inputs,
        &core_outputs,
        created_at_epoch_ms,
        expires_at_epoch_ms,
    )?;
    Ok(PreviewDraft {
        schema: preview.schema.to_owned(),
        network: "BITCOIN_SIGNET".to_owned(),
        unsigned_payload_sha256: preview.unsigned_payload_sha256,
        transaction_version: preview.transaction_version,
        lock_time: preview.lock_time,
        inputs: preview
            .inputs
            .into_iter()
            .map(|input| PreviewInputDraft {
                previous_txid: input.previous_txid,
                previous_vout: input.previous_vout,
                amount_sats: input.amount_sats,
                sequence: input.sequence,
                evidence: UtxoEvidenceDraft {
                    schema: input.evidence.schema.to_owned(),
                    source: input.evidence.source.to_owned(),
                    block_height: input.evidence.block_height,
                    block_hash: input.evidence.block_hash,
                    previous_script_pubkey_hex: input.evidence.previous_script_pubkey_hex,
                    merkle_proof_sha256: input.evidence.merkle_proof_sha256,
                    header_chain: HeaderChainDraft {
                        checkpoint_height: input.evidence.header_chain.checkpoint_height,
                        checkpoint_hash: input.evidence.header_chain.checkpoint_hash,
                        header_count: input.evidence.header_chain.header_count,
                        linkage_verified: input.evidence.header_chain.linkage_verified,
                        checkpoint_trusted: input.evidence.header_chain.checkpoint_trusted,
                        validation: input.evidence.header_chain.validation.to_owned(),
                        checkpoint_artifact_sha256: input
                            .evidence
                            .header_chain
                            .checkpoint_artifact_sha256,
                        independent_review_claims_bound: input
                            .evidence
                            .header_chain
                            .independent_review_claims_bound,
                        consensus_capability: input
                            .evidence
                            .header_chain
                            .consensus_capability
                            .to_owned(),
                        checkpoint_approval_sha256: input
                            .evidence
                            .header_chain
                            .checkpoint_approval_sha256,
                        approval_proposal_content_bound: input
                            .evidence
                            .header_chain
                            .approval_proposal_content_bound,
                        approval_signatures_verified: input
                            .evidence
                            .header_chain
                            .approval_signatures_verified,
                        trust_key_ceremony_sha256: input
                            .evidence
                            .header_chain
                            .trust_key_ceremony_sha256,
                        trust_key_ceremony_content_bound: input
                            .evidence
                            .header_chain
                            .trust_key_ceremony_content_bound,
                        trust_keys_installed: input.evidence.header_chain.trust_keys_installed,
                        trust_key_algorithm_selected: input
                            .evidence
                            .header_chain
                            .trust_key_algorithm_selected,
                    },
                    observed_at_epoch_ms: input.evidence.observed_at_epoch_ms,
                    content_sha256: input.evidence.content_sha256,
                    validation: input.evidence.validation.to_owned(),
                    transaction_inclusion_verified: input.evidence.transaction_inclusion_verified,
                    chain_verified: input.evidence.chain_verified,
                },
            })
            .collect(),
        total_input_sats: preview.total_input_sats,
        outputs: preview
            .outputs
            .into_iter()
            .map(|output| PreviewOutputDraft {
                destination: output.destination,
                script_pubkey_hex: output.script_pubkey_hex,
                amount_sats: output.amount_sats,
            })
            .collect(),
        fee_sats: preview.fee_sats,
        expires_at_epoch_ms: preview.expires_at_epoch_ms,
        destination_validation: preview.destination_validation.to_owned(),
        signing_allowed: false,
        production_action_allowed: false,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ffi_exposes_inert_algorithm_selection() {
        let selection = checkpoint_signature_algorithm_selection_draft();
        assert_eq!(selection.algorithm, "BIP340_SECP256K1_XONLY_SHA256");
        assert!(selection.official_test_vectors_required);
        assert!(!selection.verifier_implemented);
        assert!(!selection.verifier_enabled);
        assert!(!selection.trust_keys_installed);
        assert!(!selection.checkpoint_trusted);
        assert!(!selection.chain_verified);
        assert!(!selection.signing_available);
    }

    #[test]
    #[allow(
        clippy::too_many_lines,
        reason = "complete deterministic FFI trust fixture"
    )]
    fn ffi_result_preserves_non_signing_capabilities() {
        let result = create_signet_preview_draft(
            "3b61ab4494bb01c1cc705f171545724d78ca87e12fa5a0f4f6abb65ca3605cac".to_owned(),
            2,
            0,
            vec![PreviewInputRequest {
                previous_txid: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
                    .to_owned(),
                previous_vout: 0,
                amount_sats: 10_100,
                sequence: 0xffff_fffd,
                evidence: UtxoEvidenceRequest {
                    source: "BITCOIN_CORE_SIGNET_RPC_SNAPSHOT_V1".to_owned(),
                    block_height: 1,
                    block_hash: "32170001af096b6812895658107761d21f2be218f6c33e1885b8b6a534d3494e"
                        .to_owned(),
                    previous_script_pubkey_hex: "00140000000000000000000000000000000000000000"
                        .to_owned(),
                    merkle_proof_hex: "01000000ccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa01000000ffff7f20000000000100000001aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa0101".to_owned(),
                    header_chain: HeaderChainRequest {
                        checkpoint_kind: "UNREVIEWED_EXTERNAL_SIGNET_CHECKPOINT_V1".to_owned(),
                        checkpoint_height: 0,
                        checkpoint_hash: "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc".to_owned(),
                        headers_hex: vec!["01000000ccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa01000000ffff7f2000000000".to_owned()],
                        checkpoint_artifact: CheckpointArtifactRequest {
                            schema: "native-signet-checkpoint-review.v1".to_owned(),
                            network: "BITCOIN_SIGNET".to_owned(),
                            checkpoint_height: 0,
                            checkpoint_hash: "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc".to_owned(),
                            source_sha256: vec!["1".repeat(64), "2".repeat(64)],
                            reviewer_ids: vec!["reviewer_alpha".to_owned(), "reviewer_bravo".to_owned()],
                            reviewed_at_epoch_ms: 1,
                            content_sha256:
                                "e1946b84770f64bc105d3d3bbd8f2fb8707aaccb19ba4d69b7378ce32090f2d5"
                                    .to_owned(),
                        },
                        checkpoint_approval: CheckpointApprovalRequest {
                            schema: "native-signet-checkpoint-approval-proposal.v1".to_owned(),
                            policy: "OFFLINE_2_OF_3_SIGNATURES_NOT_VERIFIED".to_owned(),
                            checkpoint_artifact_sha256:
                                "e1946b84770f64bc105d3d3bbd8f2fb8707aaccb19ba4d69b7378ce32090f2d5"
                                    .to_owned(),
                            trust_key_ceremony: TrustKeyCeremonyRequest {
                                schema: "native-checkpoint-trust-key-ceremony.v1".to_owned(),
                                epoch: 1,
                                algorithm: "UNDECIDED".to_owned(),
                                key_ids: vec![
                                    "signer_alpha".to_owned(),
                                    "signer_bravo".to_owned(),
                                    "signer_charlie".to_owned(),
                                ],
                                key_material_sha256: vec![
                                    "5".repeat(64),
                                    "6".repeat(64),
                                    "7".repeat(64),
                                ],
                                participant_ids: vec![
                                    "participant_alpha".to_owned(),
                                    "participant_bravo".to_owned(),
                                    "participant_charlie".to_owned(),
                                ],
                                transcript_sha256: vec!["8".repeat(64), "9".repeat(64)],
                                created_at_epoch_ms: 1,
                                predecessor_keyset_sha256: String::new(),
                                revoked_key_ids: Vec::new(),
                                content_sha256:
                                    "77e20719307f70e005a4dd88f3adbeb3ee66f90ff160c78578f45040b2322a4c"
                                        .to_owned(),
                            },
                            signer_key_ids: vec![
                                "signer_alpha".to_owned(),
                                "signer_bravo".to_owned(),
                                "signer_charlie".to_owned(),
                            ],
                            signature_claims: vec![
                                ApprovalSignatureClaim {
                                    signer_key_id: "signer_alpha".to_owned(),
                                    signature_sha256: "3".repeat(64),
                                },
                                ApprovalSignatureClaim {
                                    signer_key_id: "signer_bravo".to_owned(),
                                    signature_sha256: "4".repeat(64),
                                },
                            ],
                            expires_at_epoch_ms: 2,
                            content_sha256:
                                "8cc049544c41b1aa4fed675be659a7102f8d7c1f37ffa8725e9f53610a76cac1"
                                    .to_owned(),
                        },
                    },
                    observed_at_epoch_ms: 1,
                    content_sha256:
                        "ed187a14d823d4989ffef7f650df1598588459c54beac73db27d2a180cecd0c0"
                            .to_owned(),
                },
            }],
            vec![PreviewOutputRequest {
                destination: "tb1qrp33g0q5c5txsp9arysrx4k6zdkfs4nce4xj0gdcccefvpysxf3q0sl5k7"
                    .to_owned(),
                amount_sats: 10_000,
            }],
            1_000,
            2_000,
        );
        assert!(result.is_ok());
        let Ok(result) = result else {
            return;
        };
        assert_eq!(result.network, "BITCOIN_SIGNET");
        assert_eq!(result.fee_sats, 100);
        assert_eq!(result.outputs.len(), 1);
        assert!(result.inputs[0].evidence.transaction_inclusion_verified);
        assert!(!result.inputs[0].evidence.chain_verified);
        assert!(result.inputs[0].evidence.header_chain.linkage_verified);
        assert!(!result.inputs[0].evidence.header_chain.checkpoint_trusted);
        assert!(
            result.inputs[0]
                .evidence
                .header_chain
                .independent_review_claims_bound
        );
        assert_eq!(
            result.inputs[0].evidence.validation,
            "TX_INCLUSION_VERIFIED_CHAIN_AND_UTXO_STATE_NOT_VERIFIED"
        );
        assert!(!result.signing_allowed);
        assert!(!result.production_action_allowed);
    }
}
