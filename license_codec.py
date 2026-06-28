"""License-key transport: encode/decode a signed license document to/from a
single copy-pasteable string.

This is the one definition of the key format, shared by both sides:
- the vendor tooling (``licensing_core``) calls :func:`encode_key` to turn a
  signed document into the string handed to a customer, and
- the app (``license_guard``) calls :func:`decode_key` to turn a pasted string
  back into the document it then verifies.

A "key" is just base64 of the existing signed document
``{"data": {...}, "signature": "<b64>"}`` with an ``FWL-`` prefix. The crypto and
the canonical schema are unchanged — this module only governs the envelope, so it
must stay dependency-free (no Qt, no cryptography) and import-safe in the customer
build.
"""

from __future__ import annotations

import base64
import json

KEY_PREFIX = "FWL-"

# A real license key is a few hundred bytes (base64 of a small JSON doc). Cap the
# accepted input well above that but far below anything that could exhaust memory,
# so a maliciously huge pasted string is rejected BEFORE base64/JSON decoding.
MAX_KEY_LENGTH = 8192


def encode_key(doc: dict) -> str:
    """Encode a signed license document into a license-key string.

    ``doc`` is the full ``{"data": ..., "signature": ...}`` structure. The JSON is
    serialized compactly and deterministically (``sort_keys``) so the same document
    always yields the same key.
    """
    if not isinstance(doc, dict) or "data" not in doc or "signature" not in doc:
        raise ValueError("Cannot encode: document is missing 'data'/'signature'.")
    raw = json.dumps(doc, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return KEY_PREFIX + base64.urlsafe_b64encode(raw).decode("ascii")


def decode_key(key: str) -> dict:
    """Decode a license-key string back into a signed license document.

    Tolerant of how a key arrives by paste: surrounding/embedded whitespace and
    line breaks are stripped, the ``FWL-`` prefix is optional, and both URL-safe
    and standard base64 alphabets are accepted. Raises ``ValueError`` with a
    user-facing message on anything that isn't a well-formed key — the caller still
    has to verify the signature; a clean decode says nothing about authenticity.
    """
    if not isinstance(key, str):
        raise ValueError("License key must be text.")

    # Reject absurdly large input before doing any base64/JSON work, so a giant
    # pasted string can't force a big allocation ahead of the signature check.
    if len(key) > MAX_KEY_LENGTH:
        raise ValueError("License key is too long to be valid.")

    # Paste artifacts: drop every kind of whitespace (spaces, tabs, newlines).
    compact = "".join(key.split())
    if not compact:
        raise ValueError("License key is empty.")

    if compact[: len(KEY_PREFIX)].upper() == KEY_PREFIX:
        compact = compact[len(KEY_PREFIX):]

    # Restore base64 padding the prefix-strip/paste may have dropped.
    compact_padded = compact + "=" * ((-len(compact)) % 4)

    raw = None
    for decoder in (base64.urlsafe_b64decode, base64.standard_b64decode):
        try:
            raw = decoder(compact_padded)
            break
        except Exception:  # pylint: disable=broad-except  # any malformed base64
            continue
    if raw is None:
        raise ValueError("License key is malformed (not valid base64).")

    try:
        doc = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("License key is malformed (not valid license data).") from exc

    if not isinstance(doc, dict) or "data" not in doc or "signature" not in doc:
        raise ValueError("License key is missing required fields.")
    return doc
