"""Tests for the license-key envelope (license_codec).

These pin the transport contract only — that a signed document survives an
encode->decode round-trip and that decode is tolerant of paste artifacts but
rejects garbage. Signature/authenticity is verified elsewhere (license_guard).
"""

import pytest

import license_codec


SAMPLE_DOC = {
    "data": {
        "customer": "Acme Co",
        "machine_id": "a" * 64,
        "expiry": "2099-01-01",
        "issued": "2020-01-01",
    },
    "signature": "c2lnbmF0dXJl",  # not a real signature; the codec doesn't care
}


def test_round_trip_preserves_document():
    key = license_codec.encode_key(SAMPLE_DOC)
    assert key.startswith(license_codec.KEY_PREFIX)
    assert license_codec.decode_key(key) == SAMPLE_DOC


def test_decode_tolerates_whitespace_and_newlines():
    key = license_codec.encode_key(SAMPLE_DOC)
    # Simulate a key pasted with wrapping/line breaks and surrounding spaces.
    mid = len(key) // 2
    mangled = f"  {key[:mid]}\n{key[mid:]}\t\n"
    assert license_codec.decode_key(mangled) == SAMPLE_DOC


def test_decode_tolerates_missing_prefix():
    key = license_codec.encode_key(SAMPLE_DOC)
    without_prefix = key[len(license_codec.KEY_PREFIX):]
    assert license_codec.decode_key(without_prefix) == SAMPLE_DOC


def test_decode_rejects_empty():
    with pytest.raises(ValueError):
        license_codec.decode_key("   \n  ")


def test_decode_rejects_oversized_input():
    # A maliciously huge key must be rejected before any base64/JSON decoding.
    with pytest.raises(ValueError):
        license_codec.decode_key("FWL-" + "A" * (license_codec.MAX_KEY_LENGTH + 1))


def test_decode_rejects_garbage():
    with pytest.raises(ValueError):
        license_codec.decode_key("FWL-this-is-not-base64-or-json-!!!")


def test_decode_rejects_non_license_json():
    import base64
    import json
    not_a_license = base64.urlsafe_b64encode(json.dumps({"hello": "world"}).encode()).decode()
    with pytest.raises(ValueError):
        license_codec.decode_key(license_codec.KEY_PREFIX + not_a_license)


def test_encode_rejects_incomplete_document():
    with pytest.raises(ValueError):
        license_codec.encode_key({"data": {"machine_id": "x"}})  # no signature
