//! Test-only parser and mutation harness for the pinned official BIP340 CSV.

use bitcoin::hashes::{Hash, sha256};
use bitcoin::secp256k1::{Message, Secp256k1, XOnlyPublicKey, schnorr::Signature};

const FIXTURE: &str = include_str!("../../../tests/fixtures/bip340-test-vectors.csv");
const EXPECTED_FIXTURE_SHA256: &str =
    "34c9d1d9c3a88d524bc80778540dc43f8306ec249a7485293063c376db851c2d";
const EXPECTED_HEADER: &str =
    "index,secret key,public key,aux_rand,message,signature,verification result,comment";

#[derive(Debug)]
struct Vector {
    index: usize,
    public_key: Vec<u8>,
    message: Vec<u8>,
    signature: Vec<u8>,
    expected: bool,
}

fn decode_hex(value: &str) -> Result<Vec<u8>, String> {
    if !value.len().is_multiple_of(2) {
        return Err("odd hex length".to_owned());
    }
    value
        .as_bytes()
        .chunks_exact(2)
        .map(|pair| {
            let text = std::str::from_utf8(pair).map_err(|_| "non-UTF-8 hex".to_owned())?;
            u8::from_str_radix(text, 16).map_err(|_| "invalid hex".to_owned())
        })
        .collect()
}

fn parse_vectors(csv: &str) -> Result<Vec<Vector>, String> {
    let normalized = csv.replace("\r\n", "\n");
    let mut lines = normalized.lines();
    if lines.next() != Some(EXPECTED_HEADER) {
        return Err("unexpected BIP340 CSV header".to_owned());
    }
    lines
        .map(|line| {
            let fields: Vec<&str> = line.splitn(8, ',').collect();
            if fields.len() != 8 {
                return Err("unexpected BIP340 CSV field count".to_owned());
            }
            let expected = match fields[6] {
                "TRUE" => true,
                "FALSE" => false,
                _ => return Err("invalid verification result".to_owned()),
            };
            Ok(Vector {
                index: fields[0].parse().map_err(|_| "invalid index".to_owned())?,
                public_key: decode_hex(fields[2])?,
                message: decode_hex(fields[4])?,
                signature: decode_hex(fields[5])?,
                expected,
            })
        })
        .collect()
}

#[test]
fn fixture_matches_pinned_upstream_provenance() {
    assert_eq!(
        sha256::Hash::hash(FIXTURE.as_bytes()).to_string(),
        EXPECTED_FIXTURE_SHA256
    );
}

fn verify_profile_vector(vector: &Vector) -> bool {
    let Ok(public_key) = XOnlyPublicKey::from_slice(&vector.public_key) else {
        return false;
    };
    let Ok(signature) = Signature::from_slice(&vector.signature) else {
        return false;
    };
    let Ok(message) = Message::from_digest_slice(&vector.message) else {
        return false;
    };
    Secp256k1::verification_only()
        .verify_schnorr(&signature, &message, &public_key)
        .is_ok()
}

#[test]
fn parses_every_pinned_official_vector_and_verifies_the_frozen_digest_profile() -> Result<(), String>
{
    let vectors = parse_vectors(FIXTURE)?;
    assert_eq!(vectors.len(), 19);
    assert!(
        vectors
            .iter()
            .enumerate()
            .all(|(index, row)| row.index == index)
    );

    let (profile, arbitrary_length): (Vec<_>, Vec<_>) =
        vectors.iter().partition(|row| row.message.len() == 32);
    assert_eq!(profile.len(), 15);
    assert_eq!(
        arbitrary_length
            .iter()
            .map(|row| row.message.len())
            .collect::<Vec<_>>(),
        vec![0, 1, 17, 100]
    );
    assert!(
        profile
            .iter()
            .all(|row| verify_profile_vector(row) == row.expected)
    );
    assert!(arbitrary_length.iter().all(|row| row.expected));
    Ok(())
}

#[test]
fn valid_profile_vectors_fail_closed_under_key_message_and_signature_mutation() -> Result<(), String>
{
    let vectors = parse_vectors(FIXTURE)?;
    for vector in vectors
        .iter()
        .filter(|row| row.expected && row.message.len() == 32)
    {
        let mut key = vector.public_key.clone();
        key[0] ^= 1;
        let mut message = vector.message.clone();
        message[0] ^= 1;
        let mut signature = vector.signature.clone();
        signature[0] ^= 1;

        assert!(!verify_profile_vector(&Vector {
            public_key: key,
            ..copy(vector)
        }));
        assert!(!verify_profile_vector(&Vector {
            message,
            ..copy(vector)
        }));
        assert!(!verify_profile_vector(&Vector {
            signature,
            ..copy(vector)
        }));
    }
    Ok(())
}

#[test]
fn parser_rejects_schema_result_and_hex_mutations() {
    assert!(parse_vectors(&FIXTURE.replacen("index,", "case,", 1)).is_err());
    assert!(parse_vectors(&FIXTURE.replacen(",TRUE,", ",YES,", 1)).is_err());
    assert!(parse_vectors(&FIXTURE.replacen("F9308A", "G9308A", 1)).is_err());
}

#[test]
fn verifier_rejects_malformed_profile_lengths() -> Result<(), String> {
    let vectors = parse_vectors(FIXTURE)?;
    let Some(valid) = vectors
        .iter()
        .find(|row| row.expected && row.message.len() == 32)
    else {
        return Err("missing valid digest-profile vector".to_owned());
    };

    let mut short_key = copy(valid);
    short_key.public_key.pop();
    let mut short_message = copy(valid);
    short_message.message.pop();
    let mut long_signature = copy(valid);
    long_signature.signature.push(0);

    assert!(!verify_profile_vector(&short_key));
    assert!(!verify_profile_vector(&short_message));
    assert!(!verify_profile_vector(&long_signature));
    Ok(())
}

fn copy(vector: &Vector) -> Vector {
    Vector {
        index: vector.index,
        public_key: vector.public_key.clone(),
        message: vector.message.clone(),
        signature: vector.signature.clone(),
        expected: vector.expected,
    }
}
