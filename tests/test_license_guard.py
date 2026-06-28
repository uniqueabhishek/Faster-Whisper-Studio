"""Tests for license_guard's pure helpers and the signing/verification contract.

These don't exercise the GUI/exit flow in verify_license_gui(); they pin the
cryptographic canonicalization contract (json.dumps(..., sort_keys=True) +
Ed25519) shared by admin_keygen (sign) and license_guard (verify), and the
HWID fallback helper.
"""

import json
import base64
from datetime import datetime, timedelta

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


def test_no_spoofable_hostname_mac_fallback():
    # The spoofable hostname+MAC fallback must be gone entirely.
    assert not hasattr(license_guard, "_legacy_machine_id")


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


def test_anti_rollback_state_roundtrip_and_machine_binding(tmp_path):
    p = str(tmp_path / "state")
    when = datetime(2027, 1, 1, 12, 0, 0)
    license_guard._write_last_seen("hwid-A", when, path=p)
    assert license_guard._read_last_seen("hwid-A", path=p) == when
    # A different machine's HWID can't validate the same state file.
    assert license_guard._read_last_seen("hwid-B", path=p) is None


def test_anti_rollback_state_rejects_tampered_date(tmp_path):
    p = str(tmp_path / "state")
    license_guard._write_last_seen("hwid-A", datetime(2027, 1, 1), path=p)
    with open(p, encoding="utf-8") as f:
        doc = json.load(f)
    doc["ts"] = doc["ts"] - 99999  # move the date back without fixing the MAC
    with open(p, "w", encoding="utf-8") as f:
        json.dump(doc, f)
    assert license_guard._read_last_seen("hwid-A", path=p) is None


def test_is_rollback_logic():
    base = datetime(2027, 6, 1)
    assert license_guard._is_rollback(base - timedelta(days=30), base) is True
    assert license_guard._is_rollback(base, base) is False
    assert license_guard._is_rollback(base - timedelta(hours=2), base) is False  # within grace
    assert license_guard._is_rollback(base, None) is False  # first run


# --- verify_license_doc + key store -------------------------------------------

def _signed_doc(private_key, machine_id, expiry,
                customer="Acme", issued="2020-01-01"):
    data = {"customer": customer, "machine_id": machine_id,
            "expiry": expiry, "issued": issued}
    sig = base64.b64encode(_sign(private_key, data)).decode()
    return {"data": data, "signature": sig}


def _use_ephemeral_key(monkeypatch):
    """Point the verifier at a throwaway keypair and a fixed online clock; return
    the matching private key so the test can sign documents the app will trust."""
    private_key = ed25519.Ed25519PrivateKey.generate()
    pub_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    monkeypatch.setattr(license_guard, "PUBLIC_KEY_PEM", pub_pem)
    monkeypatch.setattr(license_guard, "get_network_time", lambda: datetime(2030, 1, 1))
    monkeypatch.setattr(license_guard, "_write_last_seen", lambda *a, **k: None)
    return private_key


def test_verify_license_doc_valid(monkeypatch):
    private_key = _use_ephemeral_key(monkeypatch)
    doc = _signed_doc(private_key, "hwid-1", "2099-01-01")
    ok, reason = license_guard.verify_license_doc(doc, "hwid-1")
    assert ok, reason


def test_verify_license_doc_wrong_machine(monkeypatch):
    private_key = _use_ephemeral_key(monkeypatch)
    doc = _signed_doc(private_key, "hwid-OTHER", "2099-01-01")
    ok, reason = license_guard.verify_license_doc(doc, "hwid-1")
    assert not ok
    assert "different machine" in reason


def test_verify_license_doc_expired(monkeypatch):
    private_key = _use_ephemeral_key(monkeypatch)  # online clock = 2030-01-01
    doc = _signed_doc(private_key, "hwid-1", "2025-01-01")
    ok, reason = license_guard.verify_license_doc(doc, "hwid-1")
    assert not ok
    assert "ended on" in reason


def test_verify_license_doc_bad_signature(monkeypatch):
    _use_ephemeral_key(monkeypatch)
    # Sign with a *different* key than the one the verifier trusts.
    foreign = ed25519.Ed25519PrivateKey.generate()
    doc = _signed_doc(foreign, "hwid-1", "2099-01-01")
    ok, reason = license_guard.verify_license_doc(doc, "hwid-1")
    assert not ok
    assert "signature" in reason.lower()


def test_verify_license_doc_malformed(monkeypatch):
    _use_ephemeral_key(monkeypatch)
    ok, reason = license_guard.verify_license_doc({"data": {"machine_id": "x"}}, "hwid-1")
    assert not ok


def test_verify_fails_closed_when_hwid_unavailable(monkeypatch):
    # A properly-signed license still fails closed if this machine's HWID can't
    # be read, instead of matching against a spoofable fallback.
    private_key = _use_ephemeral_key(monkeypatch)
    doc = _signed_doc(private_key, "hwid-1", "2099-01-01")
    ok, reason = license_guard.verify_license_doc(doc, license_guard.HWID_UNAVAILABLE)
    assert not ok
    assert "stable hardware" in reason.lower()


def _trust_key(monkeypatch, when):
    """Trust an ephemeral key and pin the online clock to ``when``; spy on writes.

    Returns ``(private_key, write_calls)`` — write_calls records every
    _write_last_seen invocation so a test can assert whether the high-water mark
    advanced."""
    private_key = ed25519.Ed25519PrivateKey.generate()
    pub_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    monkeypatch.setattr(license_guard, "PUBLIC_KEY_PEM", pub_pem)
    monkeypatch.setattr(license_guard, "get_network_time", lambda: when)
    calls = []
    monkeypatch.setattr(license_guard, "_write_last_seen", lambda *a, **k: calls.append(a))
    return private_key, calls


def test_expired_license_does_not_advance_rollback_state(monkeypatch):
    private_key, calls = _trust_key(monkeypatch, datetime(2030, 1, 1))
    doc = _signed_doc(private_key, "hwid-1", "2025-01-01")  # expired vs the 2030 clock
    ok, reason = license_guard.verify_license_doc(doc, "hwid-1")
    assert not ok and "ended on" in reason
    assert calls == [], "an expired license must not write the anti-rollback high-water mark"


def test_valid_license_advances_rollback_state(monkeypatch):
    private_key, calls = _trust_key(monkeypatch, datetime(2030, 1, 1))
    doc = _signed_doc(private_key, "hwid-1", "2099-01-01")
    ok, _reason = license_guard.verify_license_doc(doc, "hwid-1")
    assert ok
    assert len(calls) == 1, "a valid license should record the high-water mark exactly once"


def test_license_valid_through_end_of_expiry_day(monkeypatch):
    # Noon ON the expiry day must still be valid — the user keeps their last day.
    private_key, _calls = _trust_key(monkeypatch, datetime(2030, 6, 28, 12, 0, 0))
    doc = _signed_doc(private_key, "hwid-1", "2030-06-28")
    ok, reason = license_guard.verify_license_doc(doc, "hwid-1")
    assert ok, reason


def test_license_expired_the_day_after_expiry(monkeypatch):
    private_key, _calls = _trust_key(monkeypatch, datetime(2030, 6, 29, 0, 0, 1))
    doc = _signed_doc(private_key, "hwid-1", "2030-06-28")
    ok, reason = license_guard.verify_license_doc(doc, "hwid-1")
    assert not ok and "ended on" in reason


def test_full_key_round_trip_through_codec_and_core(monkeypatch):
    """A key minted by licensing_core decodes and verifies through license_guard."""
    import licensing_core as core
    from license_codec import decode_key

    private_key = _use_ephemeral_key(monkeypatch)
    data = core.build_license_data("Acme", "hwid-1", "2099-01-01")
    key = core.make_key(private_key, data)
    ok, reason = license_guard.verify_license_doc(decode_key(key), "hwid-1")
    assert ok, reason


def test_save_and_load_key_round_trip(monkeypatch, tmp_path):
    monkeypatch.setattr(license_guard, "_appdata_dir", lambda: str(tmp_path))
    assert license_guard.load_saved_key() is None
    license_guard.save_key("FWL-some-key-string")
    assert license_guard.load_saved_key() == "FWL-some-key-string"


# --- license_status (network-free UI status) ----------------------------------

def _install_key(monkeypatch, tmp_path, private_key, machine_id, expiry, customer="Acme"):
    from license_codec import encode_key
    monkeypatch.setattr(license_guard, "_appdata_dir", lambda: str(tmp_path))
    monkeypatch.setattr(license_guard, "get_machine_id", lambda: "hwid-1")
    license_guard.save_key(encode_key(
        _signed_doc(private_key, machine_id, expiry, customer=customer)))


def test_license_status_registered(monkeypatch, tmp_path):
    private_key = _use_ephemeral_key(monkeypatch)
    _install_key(monkeypatch, tmp_path, private_key, "hwid-1", "2099-01-01", customer="Acme")
    status = license_guard.license_status()
    assert status["registered"] is True
    assert status["customer"] == "Acme"
    assert status["expiry"] == "2099-01-01"
    assert status["machine_id"] == "hwid-1"
    assert status["days_left"] is not None and status["days_left"] > 0
    assert status["reason"] == ""


def test_license_status_no_key(monkeypatch, tmp_path):
    monkeypatch.setattr(license_guard, "_appdata_dir", lambda: str(tmp_path))
    monkeypatch.setattr(license_guard, "get_machine_id", lambda: "hwid-1")
    status = license_guard.license_status()
    assert status["registered"] is False
    assert status["machine_id"] == "hwid-1"
    assert "No license" in status["reason"]


def test_license_status_expired(monkeypatch, tmp_path):
    private_key = _use_ephemeral_key(monkeypatch)
    _install_key(monkeypatch, tmp_path, private_key, "hwid-1", "2000-01-01", customer="Acme")
    status = license_guard.license_status()
    assert status["registered"] is False
    assert "expired" in status["reason"].lower()
    assert status["customer"] == "Acme"  # still surfaced for the details view


def test_license_status_wrong_machine(monkeypatch, tmp_path):
    private_key = _use_ephemeral_key(monkeypatch)
    _install_key(monkeypatch, tmp_path, private_key, "hwid-OTHER", "2099-01-01",
                 customer="Acme")
    status = license_guard.license_status()
    assert status["registered"] is False
    assert "different machine" in status["reason"]
    # Customer/expiry stay visible so the details view can still show them.
    assert status["customer"] == "Acme"
    assert status["expiry"] == "2099-01-01"
