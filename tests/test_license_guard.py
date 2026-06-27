"""Tests for license_guard's pure helpers and the signing/verification contract.

These don't exercise the GUI/exit flow in verify_license_gui(); they pin the
cryptographic canonicalization contract (json.dumps(..., sort_keys=True) +
Ed25519) shared by admin_keygen (sign) and license_guard (verify), and the
HWID fallback helper.
"""

import json
import base64

from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives import serialization
from cryptography.exceptions import InvalidSignature

import license_guard


def _sign(private_key, data: dict) -> bytes:
    payload = json.dumps(data, sort_keys=True).encode()
    return private_key.sign(payload)


def test_embedded_public_key_loads():
    pub = serialization.load_pem_public_key(license_guard.PUBLIC_KEY_PEM)
    assert isinstance(pub, ed25519.Ed25519PublicKey)


def test_legacy_machine_id_is_stable_64_hex():
    a = license_guard._legacy_machine_id()
    b = license_guard._legacy_machine_id()
    assert a == b
    assert len(a) == 64
    int(a, 16)  # must be valid hex (raises ValueError otherwise)


def test_signature_roundtrip_is_key_order_independent():
    private_key = ed25519.Ed25519PrivateKey.generate()
    public_key = private_key.public_key()

    data = {"machine_id": "abc", "expiry": "2099-01-01", "issued": "2020-01-01"}
    signature = _sign(private_key, data)

    # Re-serialize with keys in a different insertion order: sort_keys makes the
    # canonical payload identical, so verification must still succeed.
    reordered = {"issued": "2020-01-01", "expiry": "2099-01-01", "machine_id": "abc"}
    payload = json.dumps(reordered, sort_keys=True).encode()
    public_key.verify(signature, payload)  # raises InvalidSignature on failure


def test_tampered_payload_fails_verification():
    private_key = ed25519.Ed25519PrivateKey.generate()
    public_key = private_key.public_key()

    data = {"machine_id": "abc", "expiry": "2099-01-01"}
    signature = _sign(private_key, data)

    tampered = json.dumps({**data, "expiry": "2100-01-01"}, sort_keys=True).encode()
    raised = False
    try:
        public_key.verify(signature, tampered)
    except InvalidSignature:
        raised = True
    assert raised, "a tampered expiry must fail signature verification"


def test_foreign_key_cannot_verify():
    signer = ed25519.Ed25519PrivateKey.generate()
    other_public = ed25519.Ed25519PrivateKey.generate().public_key()

    data = {"machine_id": "abc", "expiry": "2099-01-01"}
    signature = _sign(signer, data)
    payload = json.dumps(data, sort_keys=True).encode()

    raised = False
    try:
        other_public.verify(signature, payload)
    except InvalidSignature:
        raised = True
    assert raised, "a signature must not verify under a different public key"
