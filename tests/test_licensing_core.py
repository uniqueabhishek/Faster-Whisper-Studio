"""Tests for licensing_core: the signing contract, the registry, and that the
admin private key on disk (if present) actually matches the public key embedded
in the shipped app.
"""

import base64
import json

import pytest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

import licensing_core as core
from license_codec import decode_key


def test_make_key_round_trips_and_signature_is_valid():
    private_key = ed25519.Ed25519PrivateKey.generate()
    public_key = private_key.public_key()

    data = core.build_license_data("Acme Co", "a" * 64, "2099-01-01")
    key = core.make_key(private_key, data)

    doc = decode_key(key)
    assert doc["data"] == data
    # The signature in the document must verify under the signer's public key.
    payload = json.dumps(doc["data"], sort_keys=True).encode()
    public_key.verify(base64.b64decode(doc["signature"]), payload)


def test_tampered_data_fails_signature():
    private_key = ed25519.Ed25519PrivateKey.generate()
    public_key = private_key.public_key()

    data = core.build_license_data("Acme", "a" * 64, "2099-01-01")
    doc = core.make_doc(private_key, data)
    # Forge a later expiry without re-signing.
    forged = json.dumps({**data, "expiry": "2100-01-01"}, sort_keys=True).encode()
    with pytest.raises(InvalidSignature):
        public_key.verify(base64.b64decode(doc["signature"]), forged)


def test_build_license_data_uses_canonical_schema():
    data = core.build_license_data("Acme", "b" * 64, "2030-01-01", issued="2025-01-01")
    assert set(data) == {"customer", "machine_id", "expiry", "issued"}
    assert data["issued"] == "2025-01-01"


def test_is_valid_machine_id():
    assert core.is_valid_machine_id("a" * 64)
    assert core.is_valid_machine_id("0123456789ABCDEF" * 4)
    assert not core.is_valid_machine_id("a" * 63)
    assert not core.is_valid_machine_id("z" * 64)
    assert not core.is_valid_machine_id("")


def test_expiry_from_days():
    from datetime import datetime
    # 2025 is not a leap year, so 365 days after Jan 1 is Jan 1 the next year.
    assert core.expiry_from_days(365, start=datetime(2025, 1, 1)) == "2026-01-01"


def test_registry_round_trip_and_reissue_history(tmp_path):
    reg_path = str(tmp_path / "license_registry.json")

    reg = core.load_registry(reg_path)
    assert reg == {"licenses": []}

    core.record_issued(reg, "Acme", "c" * 64, "2025-01-01", "2026-01-01")
    core.save_registry(reg, reg_path)

    reg2 = core.load_registry(reg_path)
    assert len(reg2["licenses"]) == 1
    entry = reg2["licenses"][0]
    assert entry["customer"] == "Acme"
    assert entry["expiry"] == "2026-01-01"
    assert entry["history"] == []

    # Re-issue the same machine: prior issuance archived, current updated.
    core.record_issued(reg2, "Acme", "c" * 64, "2026-06-01", "2027-06-01")
    assert len(reg2["licenses"]) == 1, "re-issue must not create a duplicate entry"
    entry = reg2["licenses"][0]
    assert entry["expiry"] == "2027-06-01"
    assert entry["history"] == [{"issued": "2025-01-01", "expiry": "2026-01-01"}]


def test_load_registry_tolerates_corrupt_file(tmp_path):
    reg_path = tmp_path / "license_registry.json"
    reg_path.write_text("not json at all", encoding="utf-8")
    assert core.load_registry(str(reg_path)) == {"licenses": []}


@pytest.mark.skipif(not core.keys_exist(), reason="admin private key not present")
def test_real_admin_key_matches_app_embedded_public_key():
    """A key signed with the on-disk admin private key must verify under the
    public key embedded in license_guard.py — otherwise issued licenses would be
    rejected by the shipped app."""
    private_key = core.load_private_key()
    data = core.build_license_data("Acme", "a" * 64, "2099-01-01")
    doc = decode_key(core.make_key(private_key, data))

    pem = core.embedded_public_key_pem()
    assert pem is not None, "could not read the embedded PUBLIC_KEY_PEM"
    public_key = serialization.load_pem_public_key(pem)
    payload = json.dumps(doc["data"], sort_keys=True).encode()
    public_key.verify(base64.b64decode(doc["signature"]), payload)
