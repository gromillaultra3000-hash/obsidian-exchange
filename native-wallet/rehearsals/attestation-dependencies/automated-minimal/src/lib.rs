//! Isolated strict-data-model rehearsal for future automated attestation parsing.

use base64::{Engine as _, engine::general_purpose::STANDARD};
use serde::Deserialize;

const MAX_ENVELOPE_BYTES: usize = 262_144;
const MAX_PAYLOAD_BYTES: usize = 196_608;
const MAX_PAYLOAD_BASE64_BYTES: usize = 262_144;
const CANONICAL_SIGNATURE_BASE64_BYTES: usize = 88;
const ED25519_SIGNATURE_BYTES: usize = 64;
const MAX_PAYLOAD_TYPE_BYTES: usize = 128;
const MAX_KEY_ID_BYTES: usize = 128;
const MAX_DEPENDENCIES: usize = 256;
const MAX_OUTER_JSON_DEPTH: usize = 4;
const MAX_PAYLOAD_JSON_DEPTH: usize = 16;
const MAX_JSON_TOKENS: usize = 8_192;
const MAX_JSON_STRING_BYTES: usize = 4_096;
const DSSE_PAYLOAD_TYPE: &str = "application/vnd.in-toto+json";
const STATEMENT_TYPE: &str = "https://in-toto.io/Statement/v1";
const PREDICATE_TYPE: &str = "https://slsa.dev/provenance/v1";

/// This rehearsal deliberately exposes no signature verifier or runtime capability.
pub const VERIFIER_IMPLEMENTED: bool = false;

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Envelope {
    #[serde(rename = "payloadType")]
    pub payload_type: String,
    pub payload: String,
    pub signatures: Vec<EnvelopeSignature>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct EnvelopeSignature {
    pub keyid: Option<String>,
    pub sig: String,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Statement {
    #[serde(rename = "_type")]
    pub statement_type: String,
    pub subject: Vec<Subject>,
    #[serde(rename = "predicateType")]
    pub predicate_type: String,
    pub predicate: Provenance,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Subject {
    pub name: String,
    pub digest: Sha256Digest,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Sha256Digest {
    pub sha256: String,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Provenance {
    #[serde(rename = "buildDefinition")]
    pub build_definition: BuildDefinition,
    #[serde(rename = "runDetails")]
    pub run_details: RunDetails,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct BuildDefinition {
    #[serde(rename = "buildType")]
    pub build_type: String,
    #[serde(rename = "externalParameters")]
    pub external_parameters: ExternalParameters,
    #[serde(rename = "resolvedDependencies")]
    pub resolved_dependencies: Vec<Dependency>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ExternalParameters {
    pub profile: String,
    pub target: String,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Dependency {
    pub uri: String,
    pub digest: Sha256Digest,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RunDetails {
    pub builder: Builder,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Builder {
    pub id: String,
}

#[derive(Debug, Clone, Copy)]
pub struct ExpectedDependency<'a> {
    pub uri: &'a str,
    pub sha256: &'a str,
}

#[derive(Debug, Clone, Copy)]
pub struct ExpectedPolicy<'a> {
    pub subject_name: &'a str,
    pub subject_sha256: &'a str,
    pub build_type: &'a str,
    pub profile: &'a str,
    pub target: &'a str,
    pub builder_id: &'a str,
    pub dependencies: &'a [ExpectedDependency<'a>],
}

/// Fixed-width decoded signature material; this type performs no verification.
pub struct DecodedSignature([u8; ED25519_SIGNATURE_BYTES]);

impl DecodedSignature {
    #[must_use]
    pub const fn as_bytes(&self) -> &[u8; ED25519_SIGNATURE_BYTES] {
        &self.0
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RootEpochStatus {
    Active,
    Revoked,
}

#[derive(Debug, Clone, Copy)]
pub struct ExternalRootSnapshot<'a> {
    pub policy_id: &'a str,
    pub epoch: u64,
    pub status: RootEpochStatus,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RootGateError {
    MalformedExpectation,
    UnknownPolicy,
    StaleEpoch,
    UnknownEpoch,
    RevokedEpoch,
}

fn input_boundary(bytes: &[u8], maximum: usize) -> Result<(), &'static str> {
    if bytes.is_empty() || bytes.len() > maximum || bytes.starts_with(&[0xef, 0xbb, 0xbf]) {
        return Err("input boundary rejected");
    }
    core::str::from_utf8(bytes).map_err(|_| "invalid UTF-8")?;
    Ok(())
}

fn finish_atom(in_atom: &mut bool, tokens: &mut usize) -> Result<(), &'static str> {
    if *in_atom {
        *in_atom = false;
        *tokens += 1;
        if *tokens > MAX_JSON_TOKENS {
            return Err("JSON token limit exceeded");
        }
    }
    Ok(())
}

/// Performs allocation-free resource preflight; Serde remains the syntax authority.
#[allow(
    clippy::too_many_lines,
    reason = "single-pass state machine is easier to audit intact"
)]
fn lexical_preflight(
    bytes: &[u8],
    maximum: usize,
    maximum_depth: usize,
) -> Result<(), &'static str> {
    input_boundary(bytes, maximum)?;

    let mut stack = [0_u8; MAX_PAYLOAD_JSON_DEPTH];
    let mut depth = 0_usize;
    let mut tokens = 0_usize;
    let mut in_atom = false;
    let mut in_string = false;
    let mut escaped = false;
    let mut unicode_digits = 0_u8;
    let mut string_bytes = 0_usize;

    for &byte in bytes {
        if in_string {
            if unicode_digits != 0 {
                string_bytes += 1;
                if !byte.is_ascii_hexdigit() {
                    return Err("invalid JSON Unicode escape");
                }
                unicode_digits -= 1;
            } else if escaped {
                string_bytes += 1;
                escaped = false;
                match byte {
                    b'"' | b'\\' | b'/' | b'b' | b'f' | b'n' | b'r' | b't' => {}
                    b'u' => unicode_digits = 4,
                    _ => return Err("invalid JSON escape"),
                }
            } else {
                match byte {
                    b'"' => {
                        in_string = false;
                        tokens += 1;
                        if tokens > MAX_JSON_TOKENS {
                            return Err("JSON token limit exceeded");
                        }
                    }
                    b'\\' => {
                        string_bytes += 1;
                        escaped = true;
                    }
                    0x00..=0x1f => return Err("unescaped JSON control character"),
                    _ => string_bytes += 1,
                }
            }
            if string_bytes > MAX_JSON_STRING_BYTES {
                return Err("JSON string limit exceeded");
            }
            continue;
        }

        match byte {
            b'"' => {
                finish_atom(&mut in_atom, &mut tokens)?;
                in_string = true;
                string_bytes = 0;
            }
            b'{' | b'[' => {
                finish_atom(&mut in_atom, &mut tokens)?;
                if depth >= maximum_depth {
                    return Err("JSON depth limit exceeded");
                }
                stack[depth] = byte;
                depth += 1;
                tokens += 1;
            }
            b'}' | b']' => {
                finish_atom(&mut in_atom, &mut tokens)?;
                let expected = if byte == b'}' { b'{' } else { b'[' };
                if depth == 0 || stack[depth - 1] != expected {
                    return Err("mismatched JSON container");
                }
                depth -= 1;
                tokens += 1;
            }
            b',' | b':' | b' ' | b'\t' | b'\n' | b'\r' => {
                finish_atom(&mut in_atom, &mut tokens)?;
            }
            _ => in_atom = true,
        }
        if tokens > MAX_JSON_TOKENS {
            return Err("JSON token limit exceeded");
        }
    }

    finish_atom(&mut in_atom, &mut tokens)?;
    if in_string || escaped || unicode_digits != 0 {
        return Err("incomplete JSON string or escape");
    }
    if depth != 0 {
        return Err("incomplete JSON container");
    }
    Ok(())
}

/// Parses only the strict outer DSSE data model after the caller's preflight.
///
/// # Errors
///
/// Returns an error for boundary, JSON, duplicate, unknown-field or shape drift.
pub fn parse_envelope(bytes: &[u8]) -> Result<Envelope, String> {
    lexical_preflight(bytes, MAX_ENVELOPE_BYTES, MAX_OUTER_JSON_DEPTH).map_err(str::to_owned)?;
    let envelope: Envelope = serde_json::from_slice(bytes).map_err(|error| error.to_string())?;
    if envelope.payload_type != DSSE_PAYLOAD_TYPE
        || envelope.signatures.len() != 1
        || envelope.signatures[0]
            .keyid
            .as_ref()
            .is_some_and(|keyid| keyid.len() > MAX_KEY_ID_BYTES || !keyid.is_ascii())
    {
        return Err("envelope policy rejected".to_owned());
    }
    Ok(envelope)
}

/// Decodes only the payload using canonical padded RFC 4648 Base64.
///
/// The returned bytes are the exact bytes to retain for future PAE construction.
/// The signature remains opaque and is deliberately not decoded here.
///
/// # Errors
///
/// Returns an error for oversized, malformed or non-canonical payload encoding.
pub fn decode_payload_exact(envelope: &Envelope) -> Result<Vec<u8>, String> {
    if envelope.payload.len() > MAX_PAYLOAD_BASE64_BYTES {
        return Err("encoded payload limit exceeded".to_owned());
    }
    let decoded = STANDARD
        .decode(envelope.payload.as_bytes())
        .map_err(|error| error.to_string())?;
    if decoded.len() > MAX_PAYLOAD_BYTES || STANDARD.encode(&decoded) != envelope.payload {
        return Err("payload Base64 is not canonical".to_owned());
    }
    Ok(decoded)
}

/// Canonically decodes the envelope's sole signature to exactly 64 bytes.
///
/// This is shape validation only; it does not select a key or verify Ed25519.
///
/// # Errors
///
/// Returns an error for a missing, oversized, malformed, non-canonical or
/// non-64-byte signature.
pub fn decode_signature_exact(envelope: &Envelope) -> Result<DecodedSignature, String> {
    let signature = envelope
        .signatures
        .first()
        .filter(|_| envelope.signatures.len() == 1)
        .ok_or_else(|| "exactly one signature required".to_owned())?;
    if signature.sig.len() != CANONICAL_SIGNATURE_BASE64_BYTES {
        return Err("encoded signature length rejected".to_owned());
    }
    let decoded = STANDARD
        .decode(signature.sig.as_bytes())
        .map_err(|error| error.to_string())?;
    if STANDARD.encode(&decoded) != signature.sig {
        return Err("signature Base64 is not canonical".to_owned());
    }
    let bytes = decoded
        .try_into()
        .map_err(|_| "decoded signature must be 64 bytes".to_owned())?;
    Ok(DecodedSignature(bytes))
}

/// Applies epoch and revocation policy to a root selected outside the envelope.
///
/// The unauthenticated DSSE `keyid` hint is intentionally absent from this API.
/// No key bytes are accepted and no signature verification occurs.
///
/// # Errors
///
/// Returns a typed fail-closed root-policy decision.
pub fn validate_external_root_snapshot(
    expected_policy_id: &str,
    expected_epoch: u64,
    snapshot: &ExternalRootSnapshot<'_>,
) -> Result<(), RootGateError> {
    if expected_policy_id.is_empty()
        || expected_policy_id.len() > MAX_KEY_ID_BYTES
        || !expected_policy_id.is_ascii()
        || expected_epoch == 0
    {
        return Err(RootGateError::MalformedExpectation);
    }
    if snapshot.policy_id != expected_policy_id {
        return Err(RootGateError::UnknownPolicy);
    }
    if snapshot.epoch < expected_epoch {
        return Err(RootGateError::StaleEpoch);
    }
    if snapshot.epoch > expected_epoch {
        return Err(RootGateError::UnknownEpoch);
    }
    if snapshot.status == RootEpochStatus::Revoked {
        return Err(RootGateError::RevokedEpoch);
    }
    Ok(())
}

/// Constructs DSSE 1.0.2 PAE from the exact payload bytes without normalization.
///
/// # Errors
///
/// Returns an error for an invalid payload type or a capacity overflow.
pub fn construct_pae(payload_type: &str, payload: &[u8]) -> Result<Vec<u8>, String> {
    if payload_type.is_empty()
        || payload_type.len() > MAX_PAYLOAD_TYPE_BYTES
        || !payload_type.is_ascii()
        || payload.len() > MAX_PAYLOAD_BYTES
    {
        return Err("PAE input policy rejected".to_owned());
    }
    let type_length = payload_type.len().to_string();
    let payload_length = payload.len().to_string();
    let capacity = b"DSSEv1 "
        .len()
        .checked_add(type_length.len())
        .and_then(|length| length.checked_add(1 + payload_type.len()))
        .and_then(|length| length.checked_add(1 + payload_length.len()))
        .and_then(|length| length.checked_add(1 + payload.len()))
        .ok_or_else(|| "PAE capacity overflow".to_owned())?;
    let mut pae = Vec::with_capacity(capacity);
    pae.extend_from_slice(b"DSSEv1 ");
    pae.extend_from_slice(type_length.as_bytes());
    pae.push(b' ');
    pae.extend_from_slice(payload_type.as_bytes());
    pae.push(b' ');
    pae.extend_from_slice(payload_length.as_bytes());
    pae.push(b' ');
    pae.extend_from_slice(payload);
    Ok(pae)
}

fn valid_sha256(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

fn valid_closed_uri(value: &str, allow_git_https: bool) -> bool {
    let remainder = value.strip_prefix("https://").or_else(|| {
        allow_git_https
            .then(|| value.strip_prefix("git+https://"))
            .flatten()
    });
    remainder.is_some_and(|rest| {
        !rest.is_empty()
            && !rest.starts_with('/')
            && value.is_ascii()
            && !value.bytes().any(|byte| byte.is_ascii_whitespace())
            && !value.contains(['@', '#', '?'])
    })
}

fn expected_policy_is_closed(expected: &ExpectedPolicy<'_>) -> bool {
    !expected.subject_name.is_empty()
        && expected.subject_name.len() <= MAX_JSON_STRING_BYTES
        && expected.subject_name.is_ascii()
        && valid_sha256(expected.subject_sha256)
        && valid_closed_uri(expected.build_type, false)
        && valid_closed_uri(expected.builder_id, false)
        && !expected.profile.is_empty()
        && !expected.target.is_empty()
        && expected.dependencies.len() <= MAX_DEPENDENCIES
        && expected
            .dependencies
            .iter()
            .enumerate()
            .all(|(index, item)| {
                valid_closed_uri(item.uri, true)
                    && valid_sha256(item.sha256)
                    && expected.dependencies[..index]
                        .iter()
                        .all(|earlier| earlier.uri != item.uri)
            })
}

/// Applies closed semantic policy only to an already symbolically verified statement.
///
/// This function does not verify a signature and grants no authority.
///
/// # Errors
///
/// Returns an error when the expected context is malformed or any claim differs.
pub fn validate_verified_statement(
    statement: &Statement,
    expected: &ExpectedPolicy<'_>,
) -> Result<(), &'static str> {
    if !expected_policy_is_closed(expected) {
        return Err("expected policy is not closed");
    }
    let subject = statement
        .subject
        .first()
        .filter(|_| statement.subject.len() == 1)
        .ok_or("subject policy rejected")?;
    let build = &statement.predicate.build_definition;
    if statement.statement_type != STATEMENT_TYPE
        || statement.predicate_type != PREDICATE_TYPE
        || subject.name != expected.subject_name
        || !valid_sha256(&subject.digest.sha256)
        || subject.digest.sha256 != expected.subject_sha256
        || build.build_type != expected.build_type
        || build.external_parameters.profile != expected.profile
        || build.external_parameters.target != expected.target
        || statement.predicate.run_details.builder.id != expected.builder_id
        || build.resolved_dependencies.len() != expected.dependencies.len()
    {
        return Err("statement semantic policy rejected");
    }
    for (actual, expected_item) in build
        .resolved_dependencies
        .iter()
        .zip(expected.dependencies)
    {
        if !valid_closed_uri(&actual.uri, true)
            || !valid_sha256(&actual.digest.sha256)
            || actual.uri != expected_item.uri
            || actual.digest.sha256 != expected_item.sha256
        {
            return Err("dependency semantic policy rejected");
        }
    }
    Ok(())
}

/// Parses the exact signed payload bytes only after future signature success.
///
/// # Errors
///
/// Returns an error for boundary, JSON, duplicate, unknown-field or shape drift.
pub fn parse_verified_payload(bytes: &[u8]) -> Result<Statement, String> {
    lexical_preflight(bytes, MAX_PAYLOAD_BYTES, MAX_PAYLOAD_JSON_DEPTH).map_err(str::to_owned)?;
    let statement: Statement = serde_json::from_slice(bytes).map_err(|error| error.to_string())?;
    if statement.subject.len() != 1
        || statement
            .predicate
            .build_definition
            .resolved_dependencies
            .len()
            > MAX_DEPENDENCIES
    {
        return Err("verified payload policy rejected".to_owned());
    }
    Ok(statement)
}

#[cfg(test)]
mod tests {
    use super::*;

    const ENVELOPE: &[u8] = br#"{
      "payloadType":"application/vnd.in-toto+json",
      "payload":"e30=",
      "signatures":[{"keyid":"hint-only","sig":"synthetic-not-decoded"}]
    }"#;

    const PAYLOAD: &[u8] = br#"{
      "_type":"https://in-toto.io/Statement/v1",
      "subject":[{"name":"obsidian-wallet-core.a","digest":{"sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}}],
      "predicateType":"https://slsa.dev/provenance/v1",
      "predicate":{
        "buildDefinition":{
          "buildType":"https://build.obsidian.invalid/native-wallet/v1",
          "externalParameters":{"profile":"release","target":"aarch64-apple-ios"},
          "resolvedDependencies":[{"uri":"git+https://example.invalid/source","digest":{"sha256":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}}]
        },
        "runDetails":{"builder":{"id":"https://build.obsidian.invalid/reproducible/v1"}}
      }
    }"#;

    const DEPENDENCIES: &[ExpectedDependency<'_>] = &[ExpectedDependency {
        uri: "git+https://example.invalid/source",
        sha256: "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    }];

    const EXPECTED: ExpectedPolicy<'_> = ExpectedPolicy {
        subject_name: "obsidian-wallet-core.a",
        subject_sha256: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        build_type: "https://build.obsidian.invalid/native-wallet/v1",
        profile: "release",
        target: "aarch64-apple-ios",
        builder_id: "https://build.obsidian.invalid/reproducible/v1",
        dependencies: DEPENDENCIES,
    };

    #[derive(Debug, Clone, Copy, PartialEq, Eq)]
    enum SymbolicSignatureOutcome {
        Rejected,
        PassedByTestOnlyOracle,
    }

    fn policy_after_symbolic_signature(
        payload: &[u8],
        signature: SymbolicSignatureOutcome,
    ) -> Result<(), String> {
        if signature != SymbolicSignatureOutcome::PassedByTestOnlyOracle {
            return Err("symbolic signature rejected".to_owned());
        }
        let statement = parse_verified_payload(payload)?;
        validate_verified_statement(&statement, &EXPECTED).map_err(str::to_owned)
    }

    #[test]
    fn exact_models_parse_without_granting_verification() -> Result<(), String> {
        let envelope = parse_envelope(ENVELOPE)?;
        assert_eq!(envelope.payload_type, "application/vnd.in-toto+json");
        let statement = parse_verified_payload(PAYLOAD)?;
        assert_eq!(statement.subject.len(), 1);
        assert_eq!(
            statement
                .predicate
                .build_definition
                .external_parameters
                .profile,
            "release"
        );
        const { assert!(!VERIFIER_IMPLEMENTED) };
        Ok(())
    }

    #[test]
    fn duplicate_and_unknown_fields_fail_at_nested_depths() {
        let duplicate_outer =
            br#"{"payloadType":"a","payloadType":"b","payload":"e30=","signatures":[{"sig":"x"}]}"#;
        assert!(parse_envelope(duplicate_outer).is_err());
        let unknown_signature =
            br#"{"payloadType":"a","payload":"e30=","signatures":[{"sig":"x","authority":true}]}"#;
        assert!(parse_envelope(unknown_signature).is_err());
        let duplicate_nested = String::from_utf8_lossy(PAYLOAD).replace(
            "\"profile\":\"release\"",
            "\"profile\":\"release\",\"profile\":\"debug\"",
        );
        assert!(parse_verified_payload(duplicate_nested.as_bytes()).is_err());
        let unknown_predicate = String::from_utf8_lossy(PAYLOAD)
            .replace("\"runDetails\"", "\"unexpected\":true,\"runDetails\"");
        assert!(parse_verified_payload(unknown_predicate.as_bytes()).is_err());
    }

    #[test]
    fn bom_invalid_utf8_and_oversize_fail_before_typed_parse() {
        assert!(parse_envelope(b"\xef\xbb\xbf{}").is_err());
        assert!(parse_envelope(&[0xff]).is_err());
        assert!(parse_envelope(&vec![b' '; MAX_ENVELOPE_BYTES + 1]).is_err());
        assert!(parse_verified_payload(&vec![b' '; MAX_PAYLOAD_BYTES + 1]).is_err());
    }

    #[test]
    fn lexical_resource_and_state_limits_fail_closed() {
        assert!(lexical_preflight(b"[[[[[]]]]]", 64, MAX_OUTER_JSON_DEPTH).is_err());
        let oversized_string = format!("\"{}\"", "a".repeat(MAX_JSON_STRING_BYTES + 1));
        assert!(lexical_preflight(oversized_string.as_bytes(), 8_192, 4).is_err());
        let too_many_tokens = format!("[{}]", "0,".repeat(MAX_JSON_TOKENS));
        assert!(lexical_preflight(too_many_tokens.as_bytes(), 32_768, 4).is_err());
        assert!(lexical_preflight(b"{]", 8, 4).is_err());
        assert!(lexical_preflight(br#""\q""#, 8, 4).is_err());
        assert!(lexical_preflight(br#""\u123""#, 16, 4).is_err());
    }

    #[test]
    fn lexical_preflight_does_not_panic_for_any_two_byte_input() {
        for first in u8::MIN..=u8::MAX {
            for second in u8::MIN..=u8::MAX {
                let _ = lexical_preflight(&[first, second], 2, MAX_OUTER_JSON_DEPTH);
            }
        }
    }

    #[test]
    fn canonical_payload_decode_preserves_exact_bytes() -> Result<(), String> {
        fn envelope_with(payload: &str) -> Envelope {
            Envelope {
                payload_type: "application/vnd.in-toto+json".to_owned(),
                payload: payload.to_owned(),
                signatures: vec![EnvelopeSignature {
                    keyid: None,
                    sig: "still-opaque".to_owned(),
                }],
            }
        }

        assert_eq!(
            decode_payload_exact(&envelope_with("aGVsbG8gd29ybGQ="))?,
            b"hello world"
        );
        for rejected in ["aGVsbG8gd29ybGQ", "_w==", "aGVs bG8=", "Zh=="] {
            assert!(decode_payload_exact(&envelope_with(rejected)).is_err());
        }
        Ok(())
    }

    #[test]
    fn signature_decode_is_canonical_fixed_width_and_non_verifying() -> Result<(), String> {
        fn envelope_with(signature: String) -> Envelope {
            Envelope {
                payload_type: DSSE_PAYLOAD_TYPE.to_owned(),
                payload: "e30=".to_owned(),
                signatures: vec![EnvelopeSignature {
                    keyid: Some("hint-only".to_owned()),
                    sig: signature,
                }],
            }
        }

        let canonical = STANDARD.encode([0x42_u8; ED25519_SIGNATURE_BYTES]);
        let decoded = decode_signature_exact(&envelope_with(canonical.clone()))?;
        assert_eq!(decoded.as_bytes(), &[0x42; ED25519_SIGNATURE_BYTES]);
        assert!(
            decode_signature_exact(&envelope_with(canonical.trim_end_matches('=').to_owned()))
                .is_err()
        );
        assert!(decode_signature_exact(&envelope_with(format!("{} ", &canonical[..87]))).is_err());
        assert!(decode_signature_exact(&envelope_with(STANDARD.encode([0_u8; 63]))).is_err());

        let mut non_zero_padding_bits = STANDARD.encode([0_u8; ED25519_SIGNATURE_BYTES]);
        non_zero_padding_bits.replace_range(85..86, "B");
        assert!(decode_signature_exact(&envelope_with(non_zero_padding_bits)).is_err());
        let url_safe = STANDARD
            .encode([0xff_u8; ED25519_SIGNATURE_BYTES])
            .replace('/', "_");
        assert!(decode_signature_exact(&envelope_with(url_safe)).is_err());
        const { assert!(!VERIFIER_IMPLEMENTED) };
        Ok(())
    }

    #[test]
    fn external_root_gate_is_ordered_and_keyid_cannot_select_it() -> Result<(), String> {
        const POLICY: &str = "reproducible-build-review-v1";
        let active = ExternalRootSnapshot {
            policy_id: POLICY,
            epoch: 7,
            status: RootEpochStatus::Active,
        };
        assert_eq!(validate_external_root_snapshot(POLICY, 7, &active), Ok(()));
        assert_eq!(
            validate_external_root_snapshot("other-policy", 7, &active),
            Err(RootGateError::UnknownPolicy)
        );
        assert_eq!(
            validate_external_root_snapshot(POLICY, 8, &active),
            Err(RootGateError::StaleEpoch)
        );
        assert_eq!(
            validate_external_root_snapshot(POLICY, 6, &active),
            Err(RootGateError::UnknownEpoch)
        );
        let revoked = ExternalRootSnapshot {
            status: RootEpochStatus::Revoked,
            ..active
        };
        assert_eq!(
            validate_external_root_snapshot(POLICY, 7, &revoked),
            Err(RootGateError::RevokedEpoch)
        );

        for keyid in [
            None,
            Some("matching-looking-id"),
            Some("attacker-selected-id"),
        ] {
            let envelope = Envelope {
                payload_type: DSSE_PAYLOAD_TYPE.to_owned(),
                payload: "e30=".to_owned(),
                signatures: vec![EnvelopeSignature {
                    keyid: keyid.map(str::to_owned),
                    sig: STANDARD.encode([0_u8; ED25519_SIGNATURE_BYTES]),
                }],
            };
            assert!(decode_signature_exact(&envelope).is_ok());
            assert_eq!(validate_external_root_snapshot(POLICY, 7, &active), Ok(()));
        }
        Ok(())
    }

    #[test]
    fn pae_matches_safe_reference_and_preserves_non_utf8_payload() -> Result<(), String> {
        assert_eq!(
            construct_pae("http://example.com/HelloWorld", b"hello world")?,
            b"DSSEv1 29 http://example.com/HelloWorld 11 hello world"
        );
        assert_eq!(
            construct_pae(DSSE_PAYLOAD_TYPE, &[0x00, 0xff])?,
            [
                b"DSSEv1 28 application/vnd.in-toto+json 2 ".as_slice(),
                &[0x00, 0xff],
            ]
            .concat()
        );
        Ok(())
    }

    #[test]
    fn semantics_run_only_after_symbolic_signature_success() {
        assert!(
            policy_after_symbolic_signature(PAYLOAD, SymbolicSignatureOutcome::Rejected).is_err()
        );
        assert!(
            policy_after_symbolic_signature(
                PAYLOAD,
                SymbolicSignatureOutcome::PassedByTestOnlyOracle
            )
            .is_ok()
        );
    }

    #[test]
    fn semantic_uri_digest_and_dependency_order_fail_closed() -> Result<(), String> {
        for mutation in [
            (
                "https://in-toto.io/Statement/v1",
                "https://in-toto.io/Statement/v2",
            ),
            (
                "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
            ),
            (
                "https://build.obsidian.invalid/reproducible/v1",
                "https://evil.invalid/builder",
            ),
            (
                "git+https://example.invalid/source",
                "git+https://example.invalid/other",
            ),
        ] {
            let changed = String::from_utf8_lossy(PAYLOAD).replace(mutation.0, mutation.1);
            let statement = parse_verified_payload(changed.as_bytes())?;
            assert!(validate_verified_statement(&statement, &EXPECTED).is_err());
        }

        let reversed_payload = String::from_utf8_lossy(PAYLOAD).replace(
            r#"[{"uri":"git+https://example.invalid/source","digest":{"sha256":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}}]"#,
            r#"[{"uri":"git+https://example.invalid/second","digest":{"sha256":"cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"}},{"uri":"git+https://example.invalid/source","digest":{"sha256":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}}]"#,
        );
        let reversed = parse_verified_payload(reversed_payload.as_bytes())?;
        let two_dependencies = [
            DEPENDENCIES[0],
            ExpectedDependency {
                uri: "git+https://example.invalid/second",
                sha256: "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
            },
        ];
        let reordered_expected = ExpectedPolicy {
            dependencies: &two_dependencies,
            ..EXPECTED
        };
        assert!(validate_verified_statement(&reversed, &reordered_expected).is_err());
        Ok(())
    }
}
