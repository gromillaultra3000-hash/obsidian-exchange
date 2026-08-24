//! Test-only DSSE resource, lexical and public PAE construction contract.

const MAX_ENVELOPE_BYTES: usize = 262_144;
const MAX_PAYLOAD_BYTES: usize = 196_608;
const MAX_PAYLOAD_TYPE_BYTES: usize = 128;
const MAX_OUTER_JSON_DEPTH: usize = 4;
const MAX_PAYLOAD_JSON_DEPTH: usize = 16;
const MAX_JSON_TOKENS: usize = 8_192;
const MAX_STRING_BYTES: usize = 4_096;
const EXACT_SIGNATURES: usize = 1;
const EXACT_SIGNATURE_BYTES: usize = 64;
const MAX_KEY_ID_BYTES: usize = 128;
const EXACT_SUBJECTS: usize = 1;
const MAX_DIGESTS_PER_RESOURCE: usize = 4;
const MAX_DEPENDENCIES: usize = 256;
const MAX_EXTERNAL_PARAMETERS: usize = 32;

#[derive(Clone, Copy)]
#[allow(
    clippy::struct_excessive_bools,
    reason = "explicit strict parser gates"
)]
struct Shape {
    envelope_bytes: usize,
    payload_bytes: usize,
    payload_type_bytes: usize,
    payload_type_ascii: bool,
    outer_depth: usize,
    payload_depth: usize,
    json_tokens: usize,
    largest_string_bytes: usize,
    signatures: usize,
    signature_bytes: usize,
    key_id_bytes: usize,
    key_id_ascii: bool,
    subjects: usize,
    digests_per_resource: usize,
    dependencies: usize,
    external_parameters: usize,
    utf8_without_bom: bool,
    duplicate_keys_absent: bool,
    unknown_fields_absent: bool,
    integer_model_exact: bool,
    unicode_scalars_valid: bool,
}

const fn within_limits(shape: Shape) -> bool {
    shape.envelope_bytes <= MAX_ENVELOPE_BYTES
        && shape.payload_bytes <= MAX_PAYLOAD_BYTES
        && shape.payload_type_bytes <= MAX_PAYLOAD_TYPE_BYTES
        && shape.payload_type_ascii
        && shape.outer_depth <= MAX_OUTER_JSON_DEPTH
        && shape.payload_depth <= MAX_PAYLOAD_JSON_DEPTH
        && shape.json_tokens <= MAX_JSON_TOKENS
        && shape.largest_string_bytes <= MAX_STRING_BYTES
        && shape.signatures == EXACT_SIGNATURES
        && shape.signature_bytes == EXACT_SIGNATURE_BYTES
        && shape.key_id_bytes <= MAX_KEY_ID_BYTES
        && shape.key_id_ascii
        && shape.subjects == EXACT_SUBJECTS
        && shape.digests_per_resource <= MAX_DIGESTS_PER_RESOURCE
        && shape.dependencies <= MAX_DEPENDENCIES
        && shape.external_parameters <= MAX_EXTERNAL_PARAMETERS
        && shape.utf8_without_bom
        && shape.duplicate_keys_absent
        && shape.unknown_fields_absent
        && shape.integer_model_exact
        && shape.unicode_scalars_valid
}

const fn fixture() -> Shape {
    Shape {
        envelope_bytes: 1_024,
        payload_bytes: 768,
        payload_type_bytes: 31,
        payload_type_ascii: true,
        outer_depth: 3,
        payload_depth: 8,
        json_tokens: 100,
        largest_string_bytes: 128,
        signatures: 1,
        signature_bytes: 64,
        key_id_bytes: 0,
        key_id_ascii: true,
        subjects: 1,
        digests_per_resource: 1,
        dependencies: 3,
        external_parameters: 2,
        utf8_without_bom: true,
        duplicate_keys_absent: true,
        unknown_fields_absent: true,
        integer_model_exact: true,
        unicode_scalars_valid: true,
    }
}

const fn base64_value(byte: u8) -> Option<u8> {
    match byte {
        b'A'..=b'Z' => Some(byte - b'A'),
        b'a'..=b'z' => Some(byte - b'a' + 26),
        b'0'..=b'9' => Some(byte - b'0' + 52),
        b'+' => Some(62),
        b'/' => Some(63),
        _ => None,
    }
}

fn canonical_standard_base64(value: &str) -> bool {
    let bytes = value.as_bytes();
    if bytes.is_empty() || !bytes.len().is_multiple_of(4) {
        return false;
    }
    let padding = usize::from(bytes.ends_with(b"=")) + usize::from(bytes.ends_with(b"=="));
    let data_len = bytes.len() - padding;
    if bytes[..data_len]
        .iter()
        .any(|byte| base64_value(*byte).is_none())
        || bytes[data_len..].iter().any(|byte| *byte != b'=')
    {
        return false;
    }
    match padding {
        0 => true,
        1 => base64_value(bytes[data_len - 1]).is_some_and(|last| last.trailing_zeros() >= 2),
        2 => base64_value(bytes[data_len - 1]).is_some_and(|last| last.trailing_zeros() >= 4),
        _ => false,
    }
}

fn pae(payload_type: &str, payload: &[u8]) -> Vec<u8> {
    format!(
        "DSSEv1 {} {} {} ",
        payload_type.len(),
        payload_type,
        payload.len()
    )
    .into_bytes()
    .into_iter()
    .chain(payload.iter().copied())
    .collect()
}

#[test]
fn every_resource_and_lexical_limit_fails_closed() {
    let mut cases = Vec::new();
    let mut x = fixture();
    x.envelope_bytes = MAX_ENVELOPE_BYTES + 1;
    cases.push(x);
    let mut x = fixture();
    x.payload_bytes = MAX_PAYLOAD_BYTES + 1;
    cases.push(x);
    let mut x = fixture();
    x.payload_type_bytes = MAX_PAYLOAD_TYPE_BYTES + 1;
    cases.push(x);
    let mut x = fixture();
    x.payload_type_ascii = false;
    cases.push(x);
    let mut x = fixture();
    x.outer_depth = MAX_OUTER_JSON_DEPTH + 1;
    cases.push(x);
    let mut x = fixture();
    x.payload_depth = MAX_PAYLOAD_JSON_DEPTH + 1;
    cases.push(x);
    let mut x = fixture();
    x.json_tokens = MAX_JSON_TOKENS + 1;
    cases.push(x);
    let mut x = fixture();
    x.largest_string_bytes = MAX_STRING_BYTES + 1;
    cases.push(x);
    let mut x = fixture();
    x.signatures = 2;
    cases.push(x);
    let mut x = fixture();
    x.signature_bytes = EXACT_SIGNATURE_BYTES - 1;
    cases.push(x);
    let mut x = fixture();
    x.key_id_bytes = MAX_KEY_ID_BYTES + 1;
    cases.push(x);
    let mut x = fixture();
    x.key_id_ascii = false;
    cases.push(x);
    let mut x = fixture();
    x.subjects = 2;
    cases.push(x);
    let mut x = fixture();
    x.digests_per_resource = MAX_DIGESTS_PER_RESOURCE + 1;
    cases.push(x);
    let mut x = fixture();
    x.dependencies = MAX_DEPENDENCIES + 1;
    cases.push(x);
    let mut x = fixture();
    x.external_parameters = MAX_EXTERNAL_PARAMETERS + 1;
    cases.push(x);
    let mut x = fixture();
    x.utf8_without_bom = false;
    cases.push(x);
    let mut x = fixture();
    x.duplicate_keys_absent = false;
    cases.push(x);
    let mut x = fixture();
    x.unknown_fields_absent = false;
    cases.push(x);
    let mut x = fixture();
    x.integer_model_exact = false;
    cases.push(x);
    let mut x = fixture();
    x.unicode_scalars_valid = false;
    cases.push(x);
    assert!(within_limits(fixture()));
    assert!(cases.into_iter().all(|case| !within_limits(case)));
}

#[test]
fn base64_requires_standard_alphabet_padding_and_zero_unused_bits() {
    for valid in ["aGVsbG8gd29ybGQ=", "TQ==", "TWE=", "QUJD"] {
        assert!(canonical_standard_base64(valid));
    }
    for invalid in [
        "",
        "aGVsbG8gd29ybGQ",
        "aGVsbG8gd29ybGQ_",
        "TQ=",
        "TR==",
        "TWF=",
        "QU JD",
        "====",
    ] {
        assert!(!canonical_standard_base64(invalid));
    }
}

#[test]
fn pinned_public_reference_constructs_exact_pae_without_crypto() {
    let constructed = pae("http://example.com/HelloWorld", b"hello world");
    assert_eq!(
        constructed,
        b"DSSEv1 29 http://example.com/HelloWorld 11 hello world"
    );
}
