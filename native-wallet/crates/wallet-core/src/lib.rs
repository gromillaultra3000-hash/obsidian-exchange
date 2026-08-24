//! Pure native-wallet domain core. No I/O, storage, keys, signing or network.

#![forbid(unsafe_code)]

use core::fmt;
use std::str::FromStr;

use bitcoin::absolute::LockTime;
use bitcoin::address::NetworkUnchecked;
use bitcoin::block::Header;
use bitcoin::consensus::{deserialize, serialize};
use bitcoin::hashes::{Hash, sha256};
use bitcoin::hex::FromHex;
use bitcoin::transaction::Version;
use bitcoin::{
    Address, Amount, BlockHash, MerkleBlock, Network as BitcoinNetwork, OutPoint, ScriptBuf,
    Sequence, Transaction, TxIn, TxOut, Txid, Witness,
};

const MAX_PREVIEW_LIFETIME_MS: u64 = 120_000;
const MAX_BTC_SUPPLY_SATS: u64 = 2_100_000_000_000_000;
const MAX_PREVIEW_OUTPUTS: usize = 16;
const MAX_PREVIEW_INPUTS: usize = 64;
const MAX_UTXO_EVIDENCE_AGE_MS: u64 = 600_000;
const UTXO_EVIDENCE_SCHEMA: &str = "native-signet-utxo-evidence.v1";
const UTXO_EVIDENCE_SOURCE: &str = "BITCOIN_CORE_SIGNET_RPC_SNAPSHOT_V1";
const HEADER_CHAIN_CHECKPOINT_KIND: &str = "UNREVIEWED_EXTERNAL_SIGNET_CHECKPOINT_V1";
const MAX_HEADER_CHAIN_LENGTH: usize = 144;
const CHECKPOINT_ARTIFACT_SCHEMA: &str = "native-signet-checkpoint-review.v1";
const CHECKPOINT_APPROVAL_SCHEMA: &str = "native-signet-checkpoint-approval-proposal.v1";
const CHECKPOINT_APPROVAL_POLICY: &str = "OFFLINE_2_OF_3_SIGNATURES_NOT_VERIFIED";
const TRUST_KEY_CEREMONY_SCHEMA: &str = "native-checkpoint-trust-key-ceremony.v1";
const KEY_ROTATION_SCHEMA: &str = "native-checkpoint-key-rotation-proposal.v1";
const KEY_REVOCATION_SCHEMA: &str = "native-checkpoint-key-revocation-proposal.v1";
const CHECKPOINT_SIGNATURE_ALGORITHM_SCHEMA: &str =
    "native-checkpoint-signature-algorithm-selection.v1";

/// Frozen, verification-only algorithm selection for future checkpoint approvals.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
#[allow(clippy::struct_excessive_bools, reason = "explicit capability claims")]
pub struct CheckpointSignatureAlgorithmSelection {
    /// Frozen contract schema.
    pub schema: &'static str,
    /// Exact algorithm profile.
    pub algorithm: &'static str,
    /// Normative specification identifier.
    pub specification: &'static str,
    /// Application message domain.
    pub message_domain: &'static str,
    /// Locked direct dependency version.
    pub rust_bitcoin_version: &'static str,
    /// Locked verification library version.
    pub rust_secp256k1_version: &'static str,
    /// Locked native binding version.
    pub rust_secp256k1_sys_version: &'static str,
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

/// Returns the inert checkpoint-signature algorithm contract.
#[must_use]
pub const fn checkpoint_signature_algorithm_selection() -> CheckpointSignatureAlgorithmSelection {
    CheckpointSignatureAlgorithmSelection {
        schema: CHECKPOINT_SIGNATURE_ALGORITHM_SCHEMA,
        algorithm: "BIP340_SECP256K1_XONLY_SHA256",
        specification: "BIP-0340",
        message_domain: "OBSIDIAN_CHECKPOINT_APPROVAL_V1",
        rust_bitcoin_version: "0.32.102",
        rust_secp256k1_version: "0.29.1",
        rust_secp256k1_sys_version: "0.10.1",
        xonly_public_key_bytes: 32,
        signature_bytes: 64,
        message_digest_bytes: 32,
        official_test_vectors_required: true,
        verifier_implemented: false,
        verifier_enabled: false,
        trust_keys_installed: false,
        checkpoint_trusted: false,
        chain_verified: false,
        signing_available: false,
    }
}

/// The only network admitted by the initial scaffold.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Network {
    /// Bitcoin's public test network with production-like consensus behavior.
    BitcoinSignet,
}

/// Untrusted output supplied by the native shell for validation.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PreviewOutputRequest {
    /// Signet destination text.
    pub destination: String,
    /// Exact output value in satoshis.
    pub amount_sats: u64,
}

/// Canonical output bound into the immutable display preview.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PreviewOutput {
    /// Canonical, checksum-validated Signet destination.
    pub destination: String,
    /// Lowercase hex encoding of the exact destination scriptPubKey.
    pub script_pubkey_hex: String,
    /// Exact output value in satoshis.
    pub amount_sats: u64,
}

/// Untrusted input metadata supplied by the native shell for validation.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PreviewInputRequest {
    /// Canonical lowercase previous transaction ID.
    pub previous_txid: String,
    /// Previous output index.
    pub previous_vout: u32,
    /// Exact value of the selected previous output in satoshis.
    pub amount_sats: u64,
    /// Consensus sequence value.
    pub sequence: u32,
    /// Offline content-bound observation for this exact previous output.
    pub evidence: UtxoEvidenceRequest,
}

/// Untrusted, externally observed UTXO evidence supplied to the offline core.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct UtxoEvidenceRequest {
    /// Exact allowlisted observation source contract.
    pub source: String,
    /// Signet block height at observation time.
    pub block_height: u32,
    /// Canonical lowercase block hash at observation time.
    pub block_hash: String,
    /// Previous output scriptPubKey as canonical lowercase hex.
    pub previous_script_pubkey_hex: String,
    /// Consensus-encoded `MerkleBlock` proof as canonical lowercase hex.
    pub merkle_proof_hex: String,
    /// Bounded external checkpoint and contiguous header sequence.
    pub header_chain: HeaderChainRequest,
    /// Observation time supplied by the native shell.
    pub observed_at_epoch_ms: u64,
    /// SHA-256 of the frozen canonical evidence fields.
    pub content_sha256: String,
}

/// Untrusted bounded header chain anchored to an external checkpoint.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct HeaderChainRequest {
    /// Exact contract kind; it deliberately states that trust is not established.
    pub checkpoint_kind: String,
    /// External checkpoint height.
    pub checkpoint_height: u32,
    /// Canonical lowercase external checkpoint block hash.
    pub checkpoint_hash: String,
    /// One to 144 contiguous consensus-encoded headers as lowercase hex.
    pub headers_hex: Vec<String>,
    /// Content-bound independent-review claims for the external checkpoint.
    pub checkpoint_artifact: CheckpointArtifactRequest,
    /// Offline approval proposal; signature authenticity is not verified.
    pub checkpoint_approval: CheckpointApprovalRequest,
}

/// Untrusted review artifact; validity does not imply reviewer authenticity.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CheckpointArtifactRequest {
    /// Frozen artifact schema.
    pub schema: String,
    /// Must be exactly `BITCOIN_SIGNET`.
    pub network: String,
    /// Checkpoint height bound by this artifact.
    pub checkpoint_height: u32,
    /// Checkpoint hash bound by this artifact.
    pub checkpoint_hash: String,
    /// Exactly two distinct sorted source-document SHA-256 digests.
    pub source_sha256: Vec<String>,
    /// Exactly two distinct sorted opaque reviewer identifiers.
    pub reviewer_ids: Vec<String>,
    /// Review timestamp supplied by the native shell.
    pub reviewed_at_epoch_ms: u64,
    /// SHA-256 of the canonical artifact fields.
    pub content_sha256: String,
}

/// Content-bound 2-of-3 approval proposal without embedded trust keys.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CheckpointApprovalRequest {
    /// Frozen approval proposal schema.
    pub schema: String,
    /// Exact policy identifier.
    pub policy: String,
    /// Review artifact digest being proposed for approval.
    pub checkpoint_artifact_sha256: String,
    /// Design-only trust-key ceremony proposal bound to this approval.
    pub trust_key_ceremony: TrustKeyCeremonyRequest,
    /// Exactly three distinct sorted opaque signer key identifiers.
    pub signer_key_ids: Vec<String>,
    /// Exactly two distinct sorted signature claims from the signer set.
    pub signature_claims: Vec<ApprovalSignatureClaim>,
    /// Proposal expiry supplied by the native shell.
    pub expires_at_epoch_ms: u64,
    /// SHA-256 of the canonical approval proposal fields.
    pub content_sha256: String,
}

/// Initial 3-key ceremony proposal with no real public keys or algorithm selected.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TrustKeyCeremonyRequest {
    /// Frozen ceremony schema.
    pub schema: String,
    /// Initial key-set epoch; must be one in this slice.
    pub epoch: u32,
    /// Must remain `UNDECIDED` until a separate algorithm decision.
    pub algorithm: String,
    /// Exactly three distinct sorted opaque key slot identifiers.
    pub key_ids: Vec<String>,
    /// Three distinct sorted SHA-256 commitments to external key material.
    pub key_material_sha256: Vec<String>,
    /// Exactly three distinct sorted ceremony participant identifiers.
    pub participant_ids: Vec<String>,
    /// Exactly two distinct sorted ceremony transcript SHA-256 values.
    pub transcript_sha256: Vec<String>,
    /// Ceremony timestamp.
    pub created_at_epoch_ms: u64,
    /// Empty for the initial epoch; future rotation binds its predecessor here.
    pub predecessor_keyset_sha256: String,
    /// Empty for the initial epoch; future revocation names old key slots here.
    pub revoked_key_ids: Vec<String>,
    /// SHA-256 of the canonical ceremony fields.
    pub content_sha256: String,
}

/// Opaque signature digest claim; no signature verification occurs in this slice.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ApprovalSignatureClaim {
    /// Opaque signer key identifier from the 3-key policy set.
    pub signer_key_id: String,
    /// SHA-256 of externally held signature bytes.
    pub signature_sha256: String,
}

/// Validated content binding; this is deliberately not chain verification.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct UtxoEvidence {
    /// Frozen schema identifier.
    pub schema: &'static str,
    /// Allowlisted source contract.
    pub source: &'static str,
    /// Signet block height at observation time.
    pub block_height: u32,
    /// Canonical lowercase block hash.
    pub block_hash: String,
    /// Previous output scriptPubKey as canonical lowercase hex.
    pub previous_script_pubkey_hex: String,
    /// SHA-256 of the validated consensus-encoded proof bytes.
    pub merkle_proof_sha256: String,
    /// Validated header linkage metadata without checkpoint trust.
    pub header_chain: HeaderChainEvidence,
    /// Observation time.
    pub observed_at_epoch_ms: u64,
    /// Recomputed canonical evidence digest.
    pub content_sha256: String,
    /// Honest validation level for UI display.
    pub validation: &'static str,
    /// True only when the proof includes the exact previous TXID.
    pub transaction_inclusion_verified: bool,
    /// Always false: the offline core does not query or verify the chain.
    pub chain_verified: bool,
}

/// Locally validated header linkage which does not establish Signet consensus trust.
#[derive(Clone, Debug, Eq, PartialEq)]
#[allow(
    clippy::struct_excessive_bools,
    reason = "explicit independent trust claims prevent UI capability conflation"
)]
pub struct HeaderChainEvidence {
    /// External checkpoint height.
    pub checkpoint_height: u32,
    /// Canonical external checkpoint hash.
    pub checkpoint_hash: String,
    /// Number of contiguous headers ending at the inclusion block.
    pub header_count: u32,
    /// True when every header links to its predecessor and the proof block.
    pub linkage_verified: bool,
    /// Always false until an independently reviewed checkpoint is pinned.
    pub checkpoint_trusted: bool,
    /// Honest limitation exposed to the UI.
    pub validation: &'static str,
    /// Canonical artifact digest whose claims were structurally validated.
    pub checkpoint_artifact_sha256: String,
    /// True when two distinct source and reviewer claims are content-bound.
    pub independent_review_claims_bound: bool,
    /// Fixed current consensus capability; linkage only.
    pub consensus_capability: &'static str,
    /// Canonical approval proposal digest.
    pub checkpoint_approval_sha256: String,
    /// True when a structurally valid 2-of-3 proposal is content-bound.
    pub approval_proposal_content_bound: bool,
    /// Always false until actual signatures are verified against approved keys.
    pub approval_signatures_verified: bool,
    /// Canonical design-only trust-key ceremony digest.
    pub trust_key_ceremony_sha256: String,
    /// True when ceremony roles/transcripts/key commitments are content-bound.
    pub trust_key_ceremony_content_bound: bool,
    /// Always false: no real keys are accepted or installed in this slice.
    pub trust_keys_installed: bool,
    /// Always false while algorithm remains `UNDECIDED`.
    pub trust_key_algorithm_selected: bool,
}

/// Canonical input bound into the immutable display preview.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PreviewInput {
    /// Canonical lowercase previous transaction ID.
    pub previous_txid: String,
    /// Previous output index.
    pub previous_vout: u32,
    /// Exact selected input value in satoshis.
    pub amount_sats: u64,
    /// Consensus sequence value.
    pub sequence: u32,
    /// Content-bound external observation, not chain verification.
    pub evidence: UtxoEvidence,
}

/// Immutable, human-display-bound preview. This is not a signable transaction.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TransactionPreview {
    /// Frozen schema identifier.
    pub schema: &'static str,
    /// Selected network.
    pub network: Network,
    /// Lowercase SHA-256 of externally prepared unsigned bytes.
    pub unsigned_payload_sha256: String,
    /// Bitcoin transaction version, restricted to version two.
    pub transaction_version: i32,
    /// Consensus lock time.
    pub lock_time: u32,
    /// Canonically ordered previous outpoints with amounts and sequences.
    pub inputs: Vec<PreviewInput>,
    /// Total value of all selected transaction inputs.
    pub total_input_sats: u64,
    /// Canonically ordered, checksum/network/script-validated outputs.
    pub outputs: Vec<PreviewOutput>,
    /// Fee derived exclusively as total inputs minus total outputs.
    pub fee_sats: u64,
    /// Creation time supplied by the trusted native shell.
    pub created_at_epoch_ms: u64,
    /// Hard expiry, no more than two minutes after creation.
    pub expires_at_epoch_ms: u64,
    /// Explicitly communicates the validation level.
    pub destination_validation: &'static str,
    /// Always false in the scaffold.
    pub signing_allowed: bool,
    /// Always false in the scaffold.
    pub production_action_allowed: bool,
}

/// Fail-closed preview validation errors exposed across the FFI boundary.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PreviewError {
    /// Digest is not canonical lowercase SHA-256 text.
    InvalidPayloadDigest,
    /// Destination cannot be parsed or its checksum is invalid.
    InvalidDestination,
    /// Destination is valid for another Bitcoin network, not Signet.
    InvalidDestinationNetwork,
    /// Destination text is not the parser's canonical representation.
    NonCanonicalDestination,
    /// Amount is zero or outside Bitcoin's total supply.
    InvalidAmount,
    /// Output count is zero or exceeds the bounded preview limit.
    InvalidOutputCount,
    /// Input count is zero or exceeds the bounded preview limit.
    InvalidInputCount,
    /// Input TXID is malformed or non-canonical.
    InvalidInputTxid,
    /// UTXO evidence source, block, script, time or digest is invalid.
    InvalidUtxoEvidence,
    /// Inputs are duplicated or not in canonical outpoint order.
    NonCanonicalInputs,
    /// Transaction version or lock-time/sequence relationship is invalid.
    InvalidTransactionPolicy,
    /// Outputs are duplicated or not in canonical script order.
    NonCanonicalOutputs,
    /// Inputs do not strictly exceed outputs or arithmetic overflowed.
    InvalidInputTotal,
    /// Timestamp or preview lifetime is invalid.
    InvalidLifetime,
}

impl fmt::Display for PreviewError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(match self {
            Self::InvalidPayloadDigest => "invalid unsigned payload digest",
            Self::InvalidDestination => "invalid Bitcoin destination",
            Self::InvalidDestinationNetwork => "destination is not valid for Bitcoin Signet",
            Self::NonCanonicalDestination => "destination is not canonical",
            Self::InvalidAmount => "invalid amount",
            Self::InvalidOutputCount => "invalid output count",
            Self::InvalidInputCount => "invalid input count",
            Self::InvalidInputTxid => "invalid input transaction id",
            Self::InvalidUtxoEvidence => "invalid UTXO evidence",
            Self::NonCanonicalInputs => "inputs are not canonical",
            Self::InvalidTransactionPolicy => "invalid transaction policy",
            Self::NonCanonicalOutputs => "outputs are not canonical",
            Self::InvalidInputTotal => "invalid input total",
            Self::InvalidLifetime => "invalid preview lifetime",
        })
    }
}

impl std::error::Error for PreviewError {}

/// Design-only epoch-two key rotation proposal.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct KeyRotationRequest {
    /// Frozen proposal schema.
    pub schema: String,
    /// Exact predecessor ceremony digest.
    pub predecessor_ceremony_sha256: String,
    /// Must be one.
    pub from_epoch: u32,
    /// Must be exactly two.
    pub to_epoch: u32,
    /// Exact predecessor key slots.
    pub old_key_ids: Vec<String>,
    /// Three new distinct sorted key slots.
    pub new_key_ids: Vec<String>,
    /// Three new distinct sorted external key-material commitments.
    pub new_key_material_sha256: Vec<String>,
    /// Three distinct sorted rotation participant identifiers.
    pub participant_ids: Vec<String>,
    /// Two distinct sorted rotation transcript digests.
    pub transcript_sha256: Vec<String>,
    /// Future proposed activation time.
    pub effective_at_epoch_ms: u64,
    /// Canonical proposal digest.
    pub content_sha256: String,
}

/// Design-only emergency revocation proposal for epoch one.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct KeyRevocationRequest {
    /// Frozen proposal schema.
    pub schema: String,
    /// Exact predecessor ceremony digest.
    pub predecessor_ceremony_sha256: String,
    /// Must be one.
    pub epoch: u32,
    /// One to three sorted predecessor key slots proposed for revocation.
    pub revoked_key_ids: Vec<String>,
    /// Allowlisted bounded reason code.
    pub reason_code: String,
    /// Two distinct sorted observer identifiers.
    pub observer_ids: Vec<String>,
    /// Two distinct sorted evidence digests.
    pub evidence_sha256: Vec<String>,
    /// Proposal creation time.
    pub created_at_epoch_ms: u64,
    /// Short proposal expiry.
    pub expires_at_epoch_ms: u64,
    /// Canonical proposal digest.
    pub content_sha256: String,
}

/// Pure lifecycle review with no execution authority.
#[derive(Clone, Debug, Eq, PartialEq)]
#[allow(
    clippy::struct_excessive_bools,
    reason = "explicit independent non-execution claims"
)]
pub struct KeyLifecycleReview {
    /// Frozen review schema.
    pub schema: &'static str,
    /// Canonical rotation digest.
    pub rotation_sha256: String,
    /// Canonical revocation digest.
    pub revocation_sha256: String,
    /// True when epoch-two rotation is structurally bound.
    pub rotation_content_bound: bool,
    /// True when emergency revocation is structurally bound.
    pub revocation_content_bound: bool,
    /// Always false in this design-only slice.
    pub execution_allowed: bool,
    /// Always false in this design-only slice.
    pub keys_changed: bool,
    /// Always false while algorithm is undecided.
    pub algorithm_selected: bool,
}

/// Stable lifecycle proposal validation error.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum KeyLifecycleError {
    /// Rotation proposal violates the frozen contract.
    InvalidRotation,
    /// Revocation proposal violates the frozen contract.
    InvalidRevocation,
}

impl fmt::Display for KeyLifecycleError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(match self {
            Self::InvalidRotation => "invalid key rotation proposal",
            Self::InvalidRevocation => "invalid key revocation proposal",
        })
    }
}

impl std::error::Error for KeyLifecycleError {}

fn canonical_rotation_digest(rotation: &KeyRotationRequest) -> String {
    let canonical = format!(
        "{KEY_ROTATION_SCHEMA}|{}|1|2|{}|{}|{}|{}|{}|{}",
        rotation.predecessor_ceremony_sha256,
        rotation.old_key_ids.join(","),
        rotation.new_key_ids.join(","),
        rotation.new_key_material_sha256.join(","),
        rotation.participant_ids.join(","),
        rotation.transcript_sha256.join(","),
        rotation.effective_at_epoch_ms,
    );
    sha256::Hash::hash(canonical.as_bytes()).to_string()
}

fn canonical_revocation_digest(revocation: &KeyRevocationRequest) -> String {
    let canonical = format!(
        "{KEY_REVOCATION_SCHEMA}|{}|1|{}|{}|{}|{}|{}|{}",
        revocation.predecessor_ceremony_sha256,
        revocation.revoked_key_ids.join(","),
        revocation.reason_code,
        revocation.observer_ids.join(","),
        revocation.evidence_sha256.join(","),
        revocation.created_at_epoch_ms,
        revocation.expires_at_epoch_ms,
    );
    sha256::Hash::hash(canonical.as_bytes()).to_string()
}

/// Validates design-only epoch-two rotation and emergency-revocation proposals.
///
/// # Errors
///
/// Returns [`KeyLifecycleError`] when either proposal drifts from its frozen
/// predecessor, ordering, independence, timing or content-digest contract.
pub fn review_key_lifecycle(
    predecessor_ceremony_sha256: &str,
    predecessor_key_ids: &[String],
    rotation: &KeyRotationRequest,
    revocation: &KeyRevocationRequest,
    now_epoch_ms: u64,
) -> Result<KeyLifecycleReview, KeyLifecycleError> {
    let rotation_valid = rotation.schema == KEY_ROTATION_SCHEMA
        && is_canonical_sha256(predecessor_ceremony_sha256)
        && rotation.predecessor_ceremony_sha256 == predecessor_ceremony_sha256
        && rotation.from_epoch == 1
        && rotation.to_epoch == 2
        && rotation.old_key_ids == predecessor_key_ids
        && rotation.new_key_ids.len() == 3
        && !rotation
            .new_key_ids
            .windows(2)
            .any(|pair| pair[0] >= pair[1])
        && rotation
            .new_key_ids
            .iter()
            .all(|value| is_canonical_opaque_id(value) && !predecessor_key_ids.contains(value))
        && rotation.new_key_material_sha256.len() == 3
        && !rotation
            .new_key_material_sha256
            .windows(2)
            .any(|pair| pair[0] >= pair[1])
        && rotation
            .new_key_material_sha256
            .iter()
            .all(|value| is_canonical_sha256(value))
        && rotation.participant_ids.len() == 3
        && !rotation
            .participant_ids
            .windows(2)
            .any(|pair| pair[0] >= pair[1])
        && rotation.participant_ids.iter().all(|value| {
            is_canonical_opaque_id(value)
                && !predecessor_key_ids.contains(value)
                && !rotation.new_key_ids.contains(value)
        })
        && rotation.transcript_sha256.len() == 2
        && !rotation
            .transcript_sha256
            .windows(2)
            .any(|pair| pair[0] >= pair[1])
        && rotation
            .transcript_sha256
            .iter()
            .all(|value| is_canonical_sha256(value))
        && rotation.effective_at_epoch_ms > now_epoch_ms
        && rotation.effective_at_epoch_ms <= now_epoch_ms.saturating_add(86_400_000)
        && canonical_rotation_digest(rotation) == rotation.content_sha256;
    if !rotation_valid {
        return Err(KeyLifecycleError::InvalidRotation);
    }
    let revocation_valid = revocation.schema == KEY_REVOCATION_SCHEMA
        && revocation.predecessor_ceremony_sha256 == predecessor_ceremony_sha256
        && revocation.epoch == 1
        && (1..=3).contains(&revocation.revoked_key_ids.len())
        && !revocation
            .revoked_key_ids
            .windows(2)
            .any(|pair| pair[0] >= pair[1])
        && revocation
            .revoked_key_ids
            .iter()
            .all(|value| predecessor_key_ids.contains(value))
        && matches!(
            revocation.reason_code.as_str(),
            "KEY_COMPROMISE" | "KEY_LOSS" | "CEREMONY_FAILURE"
        )
        && revocation.observer_ids.len() == 2
        && !revocation
            .observer_ids
            .windows(2)
            .any(|pair| pair[0] >= pair[1])
        && revocation
            .observer_ids
            .iter()
            .all(|value| is_canonical_opaque_id(value) && !predecessor_key_ids.contains(value))
        && revocation.evidence_sha256.len() == 2
        && !revocation
            .evidence_sha256
            .windows(2)
            .any(|pair| pair[0] >= pair[1])
        && revocation
            .evidence_sha256
            .iter()
            .all(|value| is_canonical_sha256(value))
        && revocation.created_at_epoch_ms <= now_epoch_ms
        && revocation.expires_at_epoch_ms > now_epoch_ms
        && revocation.expires_at_epoch_ms <= now_epoch_ms.saturating_add(600_000)
        && canonical_revocation_digest(revocation) == revocation.content_sha256;
    if !revocation_valid {
        return Err(KeyLifecycleError::InvalidRevocation);
    }
    Ok(KeyLifecycleReview {
        schema: "native-checkpoint-key-lifecycle-review.v1",
        rotation_sha256: rotation.content_sha256.clone(),
        revocation_sha256: revocation.content_sha256.clone(),
        rotation_content_bound: true,
        revocation_content_bound: true,
        execution_allowed: false,
        keys_changed: false,
        algorithm_selected: false,
    })
}

fn canonical_utxo_evidence_digest(
    input: &PreviewInputRequest,
    evidence: &UtxoEvidenceRequest,
) -> String {
    let canonical = format!(
        "{UTXO_EVIDENCE_SCHEMA}|{UTXO_EVIDENCE_SOURCE}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}",
        evidence.block_height,
        evidence.block_hash,
        evidence.observed_at_epoch_ms,
        input.previous_txid,
        input.previous_vout,
        input.amount_sats,
        input.sequence,
        evidence.previous_script_pubkey_hex,
        evidence.merkle_proof_hex,
        evidence.header_chain.checkpoint_kind,
        evidence.header_chain.checkpoint_height,
        evidence.header_chain.checkpoint_hash,
        evidence.header_chain.headers_hex.join(","),
        evidence.header_chain.checkpoint_artifact.content_sha256,
        evidence.header_chain.checkpoint_approval.content_sha256,
    );
    sha256::Hash::hash(canonical.as_bytes()).to_string()
}

fn is_canonical_sha256(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

fn canonical_checkpoint_artifact_digest(artifact: &CheckpointArtifactRequest) -> String {
    let canonical = format!(
        "{CHECKPOINT_ARTIFACT_SCHEMA}|BITCOIN_SIGNET|{}|{}|{}|{}|{}",
        artifact.checkpoint_height,
        artifact.checkpoint_hash,
        artifact.source_sha256.join(","),
        artifact.reviewer_ids.join(","),
        artifact.reviewed_at_epoch_ms,
    );
    sha256::Hash::hash(canonical.as_bytes()).to_string()
}

fn is_canonical_opaque_id(value: &str) -> bool {
    (8..=64).contains(&value.len())
        && value.bytes().all(|byte| {
            byte.is_ascii_lowercase() || byte.is_ascii_digit() || byte == b'-' || byte == b'_'
        })
}

fn canonical_checkpoint_approval_digest(approval: &CheckpointApprovalRequest) -> String {
    let claims = approval
        .signature_claims
        .iter()
        .map(|claim| format!("{}:{}", claim.signer_key_id, claim.signature_sha256))
        .collect::<Vec<_>>()
        .join(",");
    let canonical = format!(
        "{CHECKPOINT_APPROVAL_SCHEMA}|{CHECKPOINT_APPROVAL_POLICY}|{}|{}|{}|{}|{}",
        approval.checkpoint_artifact_sha256,
        approval.trust_key_ceremony.content_sha256,
        approval.signer_key_ids.join(","),
        claims,
        approval.expires_at_epoch_ms,
    );
    sha256::Hash::hash(canonical.as_bytes()).to_string()
}

fn canonical_trust_key_ceremony_digest(ceremony: &TrustKeyCeremonyRequest) -> String {
    let canonical = format!(
        "{TRUST_KEY_CEREMONY_SCHEMA}|1|UNDECIDED|{}|{}|{}|{}|{}||",
        ceremony.key_ids.join(","),
        ceremony.key_material_sha256.join(","),
        ceremony.participant_ids.join(","),
        ceremony.transcript_sha256.join(","),
        ceremony.created_at_epoch_ms,
    );
    sha256::Hash::hash(canonical.as_bytes()).to_string()
}

fn validate_trust_key_ceremony(
    ceremony: &TrustKeyCeremonyRequest,
    observed_at_epoch_ms: u64,
) -> Result<(), PreviewError> {
    if ceremony.schema != TRUST_KEY_CEREMONY_SCHEMA
        || ceremony.epoch != 1
        || ceremony.algorithm != "UNDECIDED"
        || ceremony.key_ids.len() != 3
        || ceremony.key_ids.windows(2).any(|pair| pair[0] >= pair[1])
        || !ceremony
            .key_ids
            .iter()
            .all(|value| is_canonical_opaque_id(value))
        || ceremony.key_material_sha256.len() != 3
        || ceremony
            .key_material_sha256
            .windows(2)
            .any(|pair| pair[0] >= pair[1])
        || !ceremony
            .key_material_sha256
            .iter()
            .all(|value| is_canonical_sha256(value))
        || ceremony.participant_ids.len() != 3
        || ceremony
            .participant_ids
            .windows(2)
            .any(|pair| pair[0] >= pair[1])
        || !ceremony
            .participant_ids
            .iter()
            .all(|value| is_canonical_opaque_id(value) && !ceremony.key_ids.contains(value))
        || ceremony.transcript_sha256.len() != 2
        || ceremony
            .transcript_sha256
            .windows(2)
            .any(|pair| pair[0] >= pair[1])
        || !ceremony
            .transcript_sha256
            .iter()
            .all(|value| is_canonical_sha256(value))
        || ceremony.created_at_epoch_ms == 0
        || ceremony.created_at_epoch_ms > observed_at_epoch_ms
        || !ceremony.predecessor_keyset_sha256.is_empty()
        || !ceremony.revoked_key_ids.is_empty()
        || canonical_trust_key_ceremony_digest(ceremony) != ceremony.content_sha256
    {
        return Err(PreviewError::InvalidUtxoEvidence);
    }
    Ok(())
}

fn validate_checkpoint_approval(
    approval: &CheckpointApprovalRequest,
    artifact_sha256: &str,
    observed_at_epoch_ms: u64,
) -> Result<(), PreviewError> {
    validate_trust_key_ceremony(&approval.trust_key_ceremony, observed_at_epoch_ms)?;
    if approval.schema != CHECKPOINT_APPROVAL_SCHEMA
        || approval.policy != CHECKPOINT_APPROVAL_POLICY
        || approval.checkpoint_artifact_sha256 != artifact_sha256
        || approval.signer_key_ids != approval.trust_key_ceremony.key_ids
        || approval.signer_key_ids.len() != 3
        || approval
            .signer_key_ids
            .windows(2)
            .any(|pair| pair[0] >= pair[1])
        || !approval
            .signer_key_ids
            .iter()
            .all(|identifier| is_canonical_opaque_id(identifier))
        || approval.signature_claims.len() != 2
        || approval
            .signature_claims
            .windows(2)
            .any(|pair| pair[0].signer_key_id >= pair[1].signer_key_id)
        || !approval.signature_claims.iter().all(|claim| {
            approval.signer_key_ids.contains(&claim.signer_key_id)
                && is_canonical_sha256(&claim.signature_sha256)
        })
        || approval.signature_claims[0].signature_sha256
            == approval.signature_claims[1].signature_sha256
        || approval.expires_at_epoch_ms <= observed_at_epoch_ms
        || approval.expires_at_epoch_ms
            > observed_at_epoch_ms.saturating_add(MAX_UTXO_EVIDENCE_AGE_MS)
        || canonical_checkpoint_approval_digest(approval) != approval.content_sha256
    {
        return Err(PreviewError::InvalidUtxoEvidence);
    }
    Ok(())
}

fn validate_checkpoint_artifact(
    artifact: &CheckpointArtifactRequest,
    checkpoint_height: u32,
    checkpoint_hash: BlockHash,
    observed_at_epoch_ms: u64,
) -> Result<(), PreviewError> {
    if artifact.schema != CHECKPOINT_ARTIFACT_SCHEMA
        || artifact.network != "BITCOIN_SIGNET"
        || artifact.checkpoint_height != checkpoint_height
        || artifact.checkpoint_hash != checkpoint_hash.to_string()
        || artifact.source_sha256.len() != 2
        || artifact
            .source_sha256
            .windows(2)
            .any(|pair| pair[0] >= pair[1])
        || !artifact
            .source_sha256
            .iter()
            .all(|digest| is_canonical_sha256(digest))
        || artifact.reviewer_ids.len() != 2
        || artifact
            .reviewer_ids
            .windows(2)
            .any(|pair| pair[0] >= pair[1])
        || !artifact
            .reviewer_ids
            .iter()
            .all(|reviewer| is_canonical_opaque_id(reviewer))
        || artifact.reviewed_at_epoch_ms == 0
        || artifact.reviewed_at_epoch_ms > observed_at_epoch_ms
        || canonical_checkpoint_artifact_digest(artifact) != artifact.content_sha256
    {
        return Err(PreviewError::InvalidUtxoEvidence);
    }
    Ok(())
}

fn validate_header_chain(
    request: &HeaderChainRequest,
    expected_height: u32,
    expected_tip: BlockHash,
    observed_at_epoch_ms: u64,
) -> Result<HeaderChainEvidence, PreviewError> {
    let checkpoint_hash = BlockHash::from_str(&request.checkpoint_hash)
        .map_err(|_| PreviewError::InvalidUtxoEvidence)?;
    if request.checkpoint_kind != HEADER_CHAIN_CHECKPOINT_KIND
        || checkpoint_hash == BlockHash::all_zeros()
        || checkpoint_hash.to_string() != request.checkpoint_hash
        || request.headers_hex.is_empty()
        || request.headers_hex.len() > MAX_HEADER_CHAIN_LENGTH
        || request.checkpoint_height.checked_add(
            u32::try_from(request.headers_hex.len())
                .map_err(|_| PreviewError::InvalidUtxoEvidence)?,
        ) != Some(expected_height)
    {
        return Err(PreviewError::InvalidUtxoEvidence);
    }
    let mut previous_hash = checkpoint_hash;
    for header_hex in &request.headers_hex {
        if header_hex.len() != Header::SIZE * 2
            || !header_hex
                .bytes()
                .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
        {
            return Err(PreviewError::InvalidUtxoEvidence);
        }
        let header_bytes =
            Vec::<u8>::from_hex(header_hex).map_err(|_| PreviewError::InvalidUtxoEvidence)?;
        let header: Header =
            deserialize(&header_bytes).map_err(|_| PreviewError::InvalidUtxoEvidence)?;
        if header.prev_blockhash != previous_hash {
            return Err(PreviewError::InvalidUtxoEvidence);
        }
        previous_hash = header.block_hash();
    }
    if previous_hash != expected_tip {
        return Err(PreviewError::InvalidUtxoEvidence);
    }
    validate_checkpoint_artifact(
        &request.checkpoint_artifact,
        request.checkpoint_height,
        checkpoint_hash,
        observed_at_epoch_ms,
    )?;
    validate_checkpoint_approval(
        &request.checkpoint_approval,
        &request.checkpoint_artifact.content_sha256,
        observed_at_epoch_ms,
    )?;
    Ok(HeaderChainEvidence {
        checkpoint_height: request.checkpoint_height,
        checkpoint_hash: request.checkpoint_hash.clone(),
        header_count: u32::try_from(request.headers_hex.len())
            .map_err(|_| PreviewError::InvalidUtxoEvidence)?,
        linkage_verified: true,
        checkpoint_trusted: false,
        validation: "LINKED_TO_UNREVIEWED_CHECKPOINT_NOT_CONSENSUS_VERIFIED",
        checkpoint_artifact_sha256: request.checkpoint_artifact.content_sha256.clone(),
        independent_review_claims_bound: true,
        consensus_capability: "HEADER_LINKAGE_ONLY_NO_SIGNET_CHALLENGE_OR_DIFFICULTY",
        checkpoint_approval_sha256: request.checkpoint_approval.content_sha256.clone(),
        approval_proposal_content_bound: true,
        approval_signatures_verified: false,
        trust_key_ceremony_sha256: request
            .checkpoint_approval
            .trust_key_ceremony
            .content_sha256
            .clone(),
        trust_key_ceremony_content_bound: true,
        trust_keys_installed: false,
        trust_key_algorithm_selected: false,
    })
}

fn validate_utxo_evidence(
    input: &PreviewInputRequest,
    created_at_epoch_ms: u64,
) -> Result<UtxoEvidence, PreviewError> {
    let evidence = &input.evidence;
    let block_hash =
        BlockHash::from_str(&evidence.block_hash).map_err(|_| PreviewError::InvalidUtxoEvidence)?;
    let proof_bytes = Vec::<u8>::from_hex(&evidence.merkle_proof_hex)
        .map_err(|_| PreviewError::InvalidUtxoEvidence)?;
    let proof: MerkleBlock =
        deserialize(&proof_bytes).map_err(|_| PreviewError::InvalidUtxoEvidence)?;
    let mut matched_txids = Vec::new();
    let mut matched_indexes = Vec::new();
    proof
        .extract_matches(&mut matched_txids, &mut matched_indexes)
        .map_err(|_| PreviewError::InvalidUtxoEvidence)?;
    let expected_txid =
        Txid::from_str(&input.previous_txid).map_err(|_| PreviewError::InvalidUtxoEvidence)?;
    let header_chain = validate_header_chain(
        &evidence.header_chain,
        evidence.block_height,
        block_hash,
        evidence.observed_at_epoch_ms,
    )?;
    if evidence.source != UTXO_EVIDENCE_SOURCE
        || evidence.block_height == 0
        || block_hash == BlockHash::all_zeros()
        || block_hash.to_string() != evidence.block_hash
        || evidence.previous_script_pubkey_hex.is_empty()
        || evidence.previous_script_pubkey_hex.len() > 20_000
        || !evidence
            .previous_script_pubkey_hex
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
        || ScriptBuf::from_hex(&evidence.previous_script_pubkey_hex).is_err()
        || evidence.merkle_proof_hex.is_empty()
        || evidence.merkle_proof_hex.len() > 2_000_000
        || !evidence
            .merkle_proof_hex
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
        || proof.header.block_hash() != block_hash
        || matched_txids.as_slice() != [expected_txid]
        || matched_indexes.len() != 1
        || evidence.observed_at_epoch_ms == 0
        || evidence.observed_at_epoch_ms > created_at_epoch_ms
        || created_at_epoch_ms - evidence.observed_at_epoch_ms > MAX_UTXO_EVIDENCE_AGE_MS
        || canonical_utxo_evidence_digest(input, evidence) != evidence.content_sha256
    {
        return Err(PreviewError::InvalidUtxoEvidence);
    }
    Ok(UtxoEvidence {
        schema: UTXO_EVIDENCE_SCHEMA,
        source: UTXO_EVIDENCE_SOURCE,
        block_height: evidence.block_height,
        block_hash: evidence.block_hash.clone(),
        previous_script_pubkey_hex: evidence.previous_script_pubkey_hex.clone(),
        merkle_proof_sha256: sha256::Hash::hash(&proof_bytes).to_string(),
        header_chain,
        observed_at_epoch_ms: evidence.observed_at_epoch_ms,
        content_sha256: evidence.content_sha256.clone(),
        validation: "TX_INCLUSION_VERIFIED_CHAIN_AND_UTXO_STATE_NOT_VERIFIED",
        transaction_inclusion_verified: true,
        chain_verified: false,
    })
}

/// Builds a non-signing Signet preview after canonical boundary validation.
///
/// # Errors
///
/// Returns [`PreviewError`] when the digest, destination, monetary
/// values or preview lifetime violates the frozen scaffold contract.
#[allow(
    clippy::too_many_lines,
    reason = "keeps the complete fail-closed transaction validation sequence auditable in one boundary"
)]
pub fn build_signet_preview(
    unsigned_payload_sha256: &str,
    transaction_version: i32,
    lock_time: u32,
    input_requests: &[PreviewInputRequest],
    output_requests: &[PreviewOutputRequest],
    created_at_epoch_ms: u64,
    expires_at_epoch_ms: u64,
) -> Result<TransactionPreview, PreviewError> {
    if unsigned_payload_sha256.len() != 64
        || !unsigned_payload_sha256
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err(PreviewError::InvalidPayloadDigest);
    }
    if transaction_version != 2 {
        return Err(PreviewError::InvalidTransactionPolicy);
    }
    if input_requests.is_empty() || input_requests.len() > MAX_PREVIEW_INPUTS {
        return Err(PreviewError::InvalidInputCount);
    }
    if output_requests.is_empty() || output_requests.len() > MAX_PREVIEW_OUTPUTS {
        return Err(PreviewError::InvalidOutputCount);
    }
    let mut inputs = Vec::with_capacity(input_requests.len());
    let mut tx_inputs = Vec::with_capacity(input_requests.len());
    let mut total_input_sats = 0_u64;
    for request in input_requests {
        let txid =
            Txid::from_str(&request.previous_txid).map_err(|_| PreviewError::InvalidInputTxid)?;
        if txid.to_string() != request.previous_txid {
            return Err(PreviewError::InvalidInputTxid);
        }
        if request.amount_sats == 0 || request.amount_sats > MAX_BTC_SUPPLY_SATS {
            return Err(PreviewError::InvalidAmount);
        }
        total_input_sats = total_input_sats
            .checked_add(request.amount_sats)
            .ok_or(PreviewError::InvalidInputTotal)?;
        let evidence = validate_utxo_evidence(request, created_at_epoch_ms)?;
        inputs.push(PreviewInput {
            previous_txid: request.previous_txid.clone(),
            previous_vout: request.previous_vout,
            amount_sats: request.amount_sats,
            sequence: request.sequence,
            evidence,
        });
        tx_inputs.push(TxIn {
            previous_output: OutPoint::new(txid, request.previous_vout),
            script_sig: ScriptBuf::new(),
            sequence: Sequence(request.sequence),
            witness: Witness::new(),
        });
    }
    if inputs.windows(2).any(|pair| {
        (pair[0].previous_txid.as_str(), pair[0].previous_vout)
            >= (pair[1].previous_txid.as_str(), pair[1].previous_vout)
    }) {
        return Err(PreviewError::NonCanonicalInputs);
    }
    if lock_time != 0 && inputs.iter().all(|input| input.sequence == u32::MAX) {
        return Err(PreviewError::InvalidTransactionPolicy);
    }
    let mut outputs = Vec::with_capacity(output_requests.len());
    let mut tx_outputs = Vec::with_capacity(output_requests.len());
    let mut total_output_sats = 0_u64;
    for request in output_requests {
        let unchecked = Address::<NetworkUnchecked>::from_str(&request.destination)
            .map_err(|_| PreviewError::InvalidDestination)?;
        let checked = unchecked
            .require_network(BitcoinNetwork::Signet)
            .map_err(|_| PreviewError::InvalidDestinationNetwork)?;
        let destination = checked.to_string();
        if request.destination != destination {
            return Err(PreviewError::NonCanonicalDestination);
        }
        if request.amount_sats == 0 || request.amount_sats > MAX_BTC_SUPPLY_SATS {
            return Err(PreviewError::InvalidAmount);
        }
        total_output_sats = total_output_sats
            .checked_add(request.amount_sats)
            .ok_or(PreviewError::InvalidInputTotal)?;
        outputs.push(PreviewOutput {
            destination,
            script_pubkey_hex: checked.script_pubkey().to_hex_string(),
            amount_sats: request.amount_sats,
        });
        tx_outputs.push(TxOut {
            value: Amount::from_sat(request.amount_sats),
            script_pubkey: checked.script_pubkey(),
        });
    }
    if outputs
        .windows(2)
        .any(|pair| pair[0].script_pubkey_hex >= pair[1].script_pubkey_hex)
    {
        return Err(PreviewError::NonCanonicalOutputs);
    }
    if total_input_sats > MAX_BTC_SUPPLY_SATS || total_input_sats <= total_output_sats {
        return Err(PreviewError::InvalidInputTotal);
    }
    let fee_sats = total_input_sats - total_output_sats;
    let transaction = Transaction {
        version: Version(transaction_version),
        lock_time: LockTime::from_consensus(lock_time),
        input: tx_inputs,
        output: tx_outputs,
    };
    let derived_payload_sha256 = sha256::Hash::hash(&serialize(&transaction)).to_string();
    if unsigned_payload_sha256 != derived_payload_sha256 {
        return Err(PreviewError::InvalidPayloadDigest);
    }
    if created_at_epoch_ms == 0
        || expires_at_epoch_ms <= created_at_epoch_ms
        || expires_at_epoch_ms - created_at_epoch_ms > MAX_PREVIEW_LIFETIME_MS
    {
        return Err(PreviewError::InvalidLifetime);
    }
    Ok(TransactionPreview {
        schema: "native-bitcoin-signet-preview.v1",
        network: Network::BitcoinSignet,
        unsigned_payload_sha256: unsigned_payload_sha256.to_owned(),
        transaction_version,
        lock_time,
        inputs,
        total_input_sats,
        outputs,
        fee_sats,
        created_at_epoch_ms,
        expires_at_epoch_ms,
        destination_validation: "CHECKSUM_NETWORK_AND_SCRIPT_VALIDATED_NOT_SIGNABLE",
        signing_allowed: false,
        production_action_allowed: false,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use bitcoin::block::{Header, Version as BlockVersion};
    use bitcoin::hex::DisplayHex;
    use bitcoin::{CompactTarget, TxMerkleNode, merkle_tree};

    const ADDRESS: &str = "tb1qrp33g0q5c5txsp9arysrx4k6zdkfs4nce4xj0gdcccefvpysxf3q0sl5k7";
    const TXID: &str = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";

    fn output(destination: &str, amount_sats: u64) -> PreviewOutputRequest {
        PreviewOutputRequest {
            destination: destination.to_owned(),
            amount_sats,
        }
    }

    #[allow(
        clippy::too_many_lines,
        reason = "complete deterministic trust fixture"
    )]
    fn input(amount_sats: u64) -> PreviewInputRequest {
        let txid = Txid::from_str(TXID).unwrap_or_else(|_| Txid::all_zeros());
        let merkle_root: TxMerkleNode = merkle_tree::calculate_root([txid].into_iter())
            .unwrap_or_else(Txid::all_zeros)
            .into();
        let header = Header {
            version: BlockVersion::ONE,
            prev_blockhash: BlockHash::from_str(
                "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
            )
            .unwrap_or_else(|_| BlockHash::all_zeros()),
            merkle_root,
            time: 1,
            bits: CompactTarget::from_consensus(0x207f_ffff),
            nonce: 0,
        };
        let proof = MerkleBlock::from_header_txids_with_predicate(&header, &[txid], |candidate| {
            candidate == &txid
        });
        let mut input = PreviewInputRequest {
            previous_txid: TXID.to_owned(),
            previous_vout: 0,
            amount_sats,
            sequence: 0xffff_fffd,
            evidence: UtxoEvidenceRequest {
                source: UTXO_EVIDENCE_SOURCE.to_owned(),
                block_height: 1,
                block_hash: header.block_hash().to_string(),
                previous_script_pubkey_hex: "00140000000000000000000000000000000000000000"
                    .to_owned(),
                merkle_proof_hex: serialize(&proof).to_lower_hex_string(),
                header_chain: HeaderChainRequest {
                    checkpoint_kind: HEADER_CHAIN_CHECKPOINT_KIND.to_owned(),
                    checkpoint_height: 0,
                    checkpoint_hash: header.prev_blockhash.to_string(),
                    headers_hex: vec![serialize(&header).to_lower_hex_string()],
                    checkpoint_artifact: CheckpointArtifactRequest {
                        schema: CHECKPOINT_ARTIFACT_SCHEMA.to_owned(),
                        network: "BITCOIN_SIGNET".to_owned(),
                        checkpoint_height: 0,
                        checkpoint_hash: header.prev_blockhash.to_string(),
                        source_sha256: vec!["1".repeat(64), "2".repeat(64)],
                        reviewer_ids: vec![
                            "reviewer_alpha".to_owned(),
                            "reviewer_bravo".to_owned(),
                        ],
                        reviewed_at_epoch_ms: 1,
                        content_sha256: String::new(),
                    },
                    checkpoint_approval: CheckpointApprovalRequest {
                        schema: CHECKPOINT_APPROVAL_SCHEMA.to_owned(),
                        policy: CHECKPOINT_APPROVAL_POLICY.to_owned(),
                        checkpoint_artifact_sha256: String::new(),
                        trust_key_ceremony: TrustKeyCeremonyRequest {
                            schema: TRUST_KEY_CEREMONY_SCHEMA.to_owned(),
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
                            content_sha256: String::new(),
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
                        content_sha256: String::new(),
                    },
                },
                observed_at_epoch_ms: 1,
                content_sha256: String::new(),
            },
        };
        input
            .evidence
            .header_chain
            .checkpoint_artifact
            .content_sha256 =
            canonical_checkpoint_artifact_digest(&input.evidence.header_chain.checkpoint_artifact);
        input
            .evidence
            .header_chain
            .checkpoint_approval
            .checkpoint_artifact_sha256 = input
            .evidence
            .header_chain
            .checkpoint_artifact
            .content_sha256
            .clone();
        input
            .evidence
            .header_chain
            .checkpoint_approval
            .trust_key_ceremony
            .content_sha256 = canonical_trust_key_ceremony_digest(
            &input
                .evidence
                .header_chain
                .checkpoint_approval
                .trust_key_ceremony,
        );
        input
            .evidence
            .header_chain
            .checkpoint_approval
            .content_sha256 =
            canonical_checkpoint_approval_digest(&input.evidence.header_chain.checkpoint_approval);
        input.evidence.content_sha256 = canonical_utxo_evidence_digest(&input, &input.evidence);
        input
    }

    fn digest(inputs: &[PreviewInputRequest], outputs: &[PreviewOutputRequest]) -> String {
        let tx_inputs = inputs
            .iter()
            .map(|request| TxIn {
                previous_output: OutPoint::new(
                    Txid::from_str(&request.previous_txid).unwrap_or_else(|_| Txid::all_zeros()),
                    request.previous_vout,
                ),
                script_sig: ScriptBuf::new(),
                sequence: Sequence(request.sequence),
                witness: Witness::new(),
            })
            .collect();
        let tx_outputs = outputs
            .iter()
            .filter_map(|request| {
                Address::<NetworkUnchecked>::from_str(&request.destination)
                    .ok()?
                    .require_network(BitcoinNetwork::Signet)
                    .ok()
                    .map(|address| TxOut {
                        value: Amount::from_sat(request.amount_sats),
                        script_pubkey: address.script_pubkey(),
                    })
            })
            .collect();
        sha256::Hash::hash(&serialize(&Transaction {
            version: Version::TWO,
            lock_time: LockTime::ZERO,
            input: tx_inputs,
            output: tx_outputs,
        }))
        .to_string()
    }

    #[test]
    fn creates_non_signing_signet_preview() {
        let inputs = [input(50_500)];
        let outputs = [output(ADDRESS, 50_000)];
        let payload_digest = digest(&inputs, &outputs);
        let result = build_signet_preview(&payload_digest, 2, 0, &inputs, &outputs, 1_000, 121_000);
        assert!(result.is_ok());
        let Ok(preview) = result else {
            return;
        };
        assert_eq!(preview.network, Network::BitcoinSignet);
        assert!(!preview.signing_allowed);
        assert!(!preview.production_action_allowed);
        assert_eq!(
            preview.destination_validation,
            "CHECKSUM_NETWORK_AND_SCRIPT_VALIDATED_NOT_SIGNABLE"
        );
        let checked = Address::<NetworkUnchecked>::from_str(ADDRESS)
            .and_then(|address| address.require_network(BitcoinNetwork::Signet));
        assert!(checked.is_ok());
        let Ok(checked) = checked else {
            return;
        };
        assert_eq!(
            preview.outputs[0].script_pubkey_hex,
            checked.script_pubkey().to_hex_string()
        );
        assert_eq!(preview.total_input_sats, 50_500);
        assert_eq!(preview.fee_sats, 500);
        assert!(!preview.inputs[0].evidence.chain_verified);
        assert!(preview.inputs[0].evidence.transaction_inclusion_verified);
        assert!(preview.inputs[0].evidence.header_chain.linkage_verified);
        assert!(!preview.inputs[0].evidence.header_chain.checkpoint_trusted);
        assert!(
            preview.inputs[0]
                .evidence
                .header_chain
                .independent_review_claims_bound
        );
        assert!(
            preview.inputs[0]
                .evidence
                .header_chain
                .approval_proposal_content_bound
        );
        assert!(
            !preview.inputs[0]
                .evidence
                .header_chain
                .approval_signatures_verified
        );
        assert!(
            preview.inputs[0]
                .evidence
                .header_chain
                .trust_key_ceremony_content_bound
        );
        assert!(!preview.inputs[0].evidence.header_chain.trust_keys_installed);
        assert!(
            !preview.inputs[0]
                .evidence
                .header_chain
                .trust_key_algorithm_selected
        );
    }

    #[test]
    fn rejects_mainnet_mixed_case_amount_fee_and_lifetime_drift() {
        assert_eq!(
            build_signet_preview(
                &"a".repeat(64),
                2,
                0,
                &[input(2)],
                &[output("bc1qvzvkjn4q3nszqxrv3nraga2r822xjty3ykvkuw", 1)],
                1,
                2
            ),
            Err(PreviewError::InvalidDestinationNetwork)
        );
        assert_eq!(
            build_signet_preview(
                &"a".repeat(64),
                2,
                0,
                &[input(2)],
                &[output("tb1qExample000000000000000000000000000000000", 1)],
                1,
                2
            ),
            Err(PreviewError::InvalidDestination)
        );
        assert_eq!(
            build_signet_preview(
                &"a".repeat(64),
                2,
                0,
                &[input(2)],
                &[output(
                    "tb1qrp33g0q5c5txsp9arysrx4k6zdkfs4nce4xj0gdcccefvpysxf3q0sl5kx",
                    1,
                )],
                1,
                2
            ),
            Err(PreviewError::InvalidDestination)
        );
        assert_eq!(
            build_signet_preview(
                &"a".repeat(64),
                2,
                0,
                &[input(2)],
                &[output(ADDRESS, 0)],
                1,
                2
            ),
            Err(PreviewError::InvalidAmount)
        );
        assert_eq!(
            build_signet_preview(
                &"a".repeat(64),
                2,
                0,
                &[input(10)],
                &[output(ADDRESS, 10)],
                1,
                2
            ),
            Err(PreviewError::InvalidInputTotal)
        );
        assert_eq!(
            {
                let inputs = [input(11)];
                let outputs = [output(ADDRESS, 10)];
                build_signet_preview(
                    &digest(&inputs, &outputs),
                    2,
                    0,
                    &inputs,
                    &outputs,
                    1,
                    120_002,
                )
            },
            Err(PreviewError::InvalidLifetime)
        );
    }

    #[test]
    fn rejects_empty_duplicate_and_noncanonical_output_sets() {
        assert_eq!(
            build_signet_preview(&"a".repeat(64), 2, 0, &[input(1)], &[], 1, 2),
            Err(PreviewError::InvalidOutputCount)
        );
        let duplicate = [output(ADDRESS, 10), output(ADDRESS, 10)];
        assert_eq!(
            build_signet_preview(&"a".repeat(64), 2, 0, &[input(21)], &duplicate, 1, 2),
            Err(PreviewError::NonCanonicalOutputs)
        );
    }

    #[test]
    fn binds_canonical_inputs_policy_and_exact_unsigned_digest() {
        let inputs = [input(11)];
        let outputs = [output(ADDRESS, 10)];
        assert_eq!(
            build_signet_preview(&"b".repeat(64), 2, 0, &inputs, &outputs, 1, 2),
            Err(PreviewError::InvalidPayloadDigest)
        );
        assert_eq!(
            build_signet_preview(&digest(&inputs, &outputs), 1, 0, &inputs, &outputs, 1, 2),
            Err(PreviewError::InvalidTransactionPolicy)
        );
        assert_eq!(
            build_signet_preview(&"a".repeat(64), 2, 0, &[], &outputs, 1, 2),
            Err(PreviewError::InvalidInputCount)
        );
        let duplicate = [input(6), input(5)];
        assert_eq!(
            build_signet_preview(&"a".repeat(64), 2, 0, &duplicate, &outputs, 1, 2),
            Err(PreviewError::NonCanonicalInputs)
        );
        let mut final_input = input(11);
        final_input.sequence = u32::MAX;
        final_input.evidence.content_sha256 =
            canonical_utxo_evidence_digest(&final_input, &final_input.evidence);
        assert_eq!(
            build_signet_preview(&"a".repeat(64), 2, 1, &[final_input], &outputs, 1, 2),
            Err(PreviewError::InvalidTransactionPolicy)
        );
    }

    #[test]
    fn rejects_drifted_stale_or_unknown_utxo_evidence() {
        let outputs = [output(ADDRESS, 10)];
        let mut drifted = input(11);
        drifted.evidence.block_height = 2;
        assert_eq!(
            build_signet_preview(&"a".repeat(64), 2, 0, &[drifted], &outputs, 1, 2),
            Err(PreviewError::InvalidUtxoEvidence)
        );
        let mut unknown = input(11);
        unknown.evidence.source = "UNTRUSTED".to_owned();
        unknown.evidence.content_sha256 =
            canonical_utxo_evidence_digest(&unknown, &unknown.evidence);
        assert_eq!(
            build_signet_preview(&"a".repeat(64), 2, 0, &[unknown], &outputs, 1, 2),
            Err(PreviewError::InvalidUtxoEvidence)
        );
        let mut stale = input(11);
        stale.evidence.observed_at_epoch_ms = 1;
        stale.evidence.content_sha256 = canonical_utxo_evidence_digest(&stale, &stale.evidence);
        assert_eq!(
            build_signet_preview(
                &"a".repeat(64),
                2,
                0,
                &[stale],
                &outputs,
                MAX_UTXO_EVIDENCE_AGE_MS + 2,
                MAX_UTXO_EVIDENCE_AGE_MS + 3,
            ),
            Err(PreviewError::InvalidUtxoEvidence)
        );
        let mut corrupted = input(11);
        corrupted.evidence.merkle_proof_hex.pop();
        corrupted.evidence.merkle_proof_hex.push('0');
        corrupted.evidence.content_sha256 =
            canonical_utxo_evidence_digest(&corrupted, &corrupted.evidence);
        assert_eq!(
            build_signet_preview(&"a".repeat(64), 2, 0, &[corrupted], &outputs, 1, 2),
            Err(PreviewError::InvalidUtxoEvidence)
        );
        let mut unlinked = input(11);
        unlinked.evidence.header_chain.checkpoint_hash =
            "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd".to_owned();
        unlinked.evidence.content_sha256 =
            canonical_utxo_evidence_digest(&unlinked, &unlinked.evidence);
        assert_eq!(
            build_signet_preview(&"a".repeat(64), 2, 0, &[unlinked], &outputs, 1, 2),
            Err(PreviewError::InvalidUtxoEvidence)
        );
        let mut self_reviewed = input(11);
        self_reviewed
            .evidence
            .header_chain
            .checkpoint_artifact
            .reviewer_ids = vec!["same_reviewer".to_owned(), "same_reviewer".to_owned()];
        self_reviewed
            .evidence
            .header_chain
            .checkpoint_artifact
            .content_sha256 = canonical_checkpoint_artifact_digest(
            &self_reviewed.evidence.header_chain.checkpoint_artifact,
        );
        self_reviewed.evidence.content_sha256 =
            canonical_utxo_evidence_digest(&self_reviewed, &self_reviewed.evidence);
        assert_eq!(
            build_signet_preview(&"a".repeat(64), 2, 0, &[self_reviewed], &outputs, 1, 2,),
            Err(PreviewError::InvalidUtxoEvidence)
        );
        let mut self_approved = input(11);
        self_approved
            .evidence
            .header_chain
            .checkpoint_approval
            .signature_claims[1]
            .signer_key_id = "signer_alpha".to_owned();
        self_approved
            .evidence
            .header_chain
            .checkpoint_approval
            .content_sha256 = canonical_checkpoint_approval_digest(
            &self_approved.evidence.header_chain.checkpoint_approval,
        );
        self_approved.evidence.content_sha256 =
            canonical_utxo_evidence_digest(&self_approved, &self_approved.evidence);
        assert_eq!(
            build_signet_preview(&"a".repeat(64), 2, 0, &[self_approved], &outputs, 1, 2,),
            Err(PreviewError::InvalidUtxoEvidence)
        );
    }

    #[test]
    fn reviews_rotation_and_revocation_without_executing_them() {
        let predecessor = "a".repeat(64);
        let old_keys = vec![
            "signer_alpha".to_owned(),
            "signer_bravo".to_owned(),
            "signer_charlie".to_owned(),
        ];
        let mut rotation = KeyRotationRequest {
            schema: KEY_ROTATION_SCHEMA.to_owned(),
            predecessor_ceremony_sha256: predecessor.clone(),
            from_epoch: 1,
            to_epoch: 2,
            old_key_ids: old_keys.clone(),
            new_key_ids: vec![
                "next_alpha".to_owned(),
                "next_bravo".to_owned(),
                "next_charlie".to_owned(),
            ],
            new_key_material_sha256: vec!["b".repeat(64), "c".repeat(64), "d".repeat(64)],
            participant_ids: vec![
                "rotate_alpha".to_owned(),
                "rotate_bravo".to_owned(),
                "rotate_charlie".to_owned(),
            ],
            transcript_sha256: vec!["e".repeat(64), "f".repeat(64)],
            effective_at_epoch_ms: 2_000,
            content_sha256: String::new(),
        };
        rotation.content_sha256 = canonical_rotation_digest(&rotation);
        let mut revocation = KeyRevocationRequest {
            schema: KEY_REVOCATION_SCHEMA.to_owned(),
            predecessor_ceremony_sha256: predecessor.clone(),
            epoch: 1,
            revoked_key_ids: vec!["signer_alpha".to_owned()],
            reason_code: "KEY_COMPROMISE".to_owned(),
            observer_ids: vec!["observer_alpha".to_owned(), "observer_bravo".to_owned()],
            evidence_sha256: vec!["1".repeat(64), "2".repeat(64)],
            created_at_epoch_ms: 1_000,
            expires_at_epoch_ms: 2_000,
            content_sha256: String::new(),
        };
        revocation.content_sha256 = canonical_revocation_digest(&revocation);
        let review = review_key_lifecycle(&predecessor, &old_keys, &rotation, &revocation, 1_000);
        assert!(review.is_ok());
        let Ok(review) = review else { return };
        assert!(review.rotation_content_bound);
        assert!(review.revocation_content_bound);
        assert!(!review.execution_allowed);
        assert!(!review.keys_changed);
        assert!(!review.algorithm_selected);

        let mut drifted = rotation;
        drifted.new_key_ids[0] = "signer_alpha".to_owned();
        drifted.content_sha256 = canonical_rotation_digest(&drifted);
        assert_eq!(
            review_key_lifecycle(&predecessor, &old_keys, &drifted, &revocation, 1_000),
            Err(KeyLifecycleError::InvalidRotation)
        );
    }

    #[test]
    fn freezes_checkpoint_signature_algorithm_without_enabling_trust() {
        let selection = checkpoint_signature_algorithm_selection();
        assert_eq!(selection.algorithm, "BIP340_SECP256K1_XONLY_SHA256");
        assert_eq!(selection.specification, "BIP-0340");
        assert_eq!(selection.message_domain, "OBSIDIAN_CHECKPOINT_APPROVAL_V1");
        assert_eq!(selection.rust_bitcoin_version, "0.32.102");
        assert_eq!(selection.rust_secp256k1_version, "0.29.1");
        assert_eq!(selection.rust_secp256k1_sys_version, "0.10.1");
        assert_eq!(selection.xonly_public_key_bytes, 32);
        assert_eq!(selection.signature_bytes, 64);
        assert_eq!(selection.message_digest_bytes, 32);
        assert!(selection.official_test_vectors_required);
        assert!(!selection.verifier_implemented);
        assert!(!selection.verifier_enabled);
        assert!(!selection.trust_keys_installed);
        assert!(!selection.checkpoint_trusted);
        assert!(!selection.chain_verified);
        assert!(!selection.signing_available);
    }
}
