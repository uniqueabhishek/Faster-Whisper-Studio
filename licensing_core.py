"""Vendor-side licensing core: signing, keypair management, and the issuance
registry. Shared by the admin CLIs and the license-manager GUI.

IMPORTANT — build boundary: this module is the vendor's signing toolchain and
must NEVER be bundled into the customer build. The customer app reaches the key
format through ``license_codec`` only; nothing the app imports may import this
module. Keep it Qt-free so it stays a plain importable library for both the CLIs
and the manager GUI.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timedelta

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

from license_codec import encode_key

KEYS_DIR = "admin_keys"
PRIVATE_KEY_FILE = os.path.join(KEYS_DIR, "private_key.pem")
PUBLIC_KEY_FILE = os.path.join(KEYS_DIR, "public_key.pem")
GUARD_FILE = "license_guard.py"
REGISTRY_FILE = "license_registry.json"

# Matches the embedded ``PUBLIC_KEY_PEM = b"""...-----END PUBLIC KEY-----..."""``.
_PEM_BLOCK = re.compile(r'PUBLIC_KEY_PEM\s*=\s*b""".*?"""', re.DOTALL)
_HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")


# --- Machine ID / expiry helpers -------------------------------------------

def is_valid_machine_id(value: str) -> bool:
    """A Machine ID is the sha256 hex digest produced by license_guard (64 hex)."""
    return bool(_HEX64.match((value or "").strip()))


def expiry_from_days(days: int, start: datetime | None = None) -> str:
    """Return a ``YYYY-MM-DD`` expiry ``days`` from ``start`` (default: today)."""
    base = start or datetime.now()
    return (base + timedelta(days=days)).strftime("%Y-%m-%d")


def today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


# --- Signing ---------------------------------------------------------------

def load_private_key(path: str = PRIVATE_KEY_FILE):
    """Load the admin Ed25519 private key. Raises ``FileNotFoundError`` if absent."""
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Private key not found at {path}. Run setup_security.py first.")
    with open(path, "rb") as f:
        return serialization.load_pem_private_key(f.read(), password=None)


def keys_exist(path: str = PRIVATE_KEY_FILE) -> bool:
    return os.path.exists(path)


MAX_CUSTOMER_LEN = 200


def build_license_data(customer: str, machine_id: str, expiry: str,
                       issued: str | None = None) -> dict:
    """Build the canonical license payload that gets signed.

    Schema (shared with license_guard's verifier): customer, machine_id, expiry,
    issued. Keep these four fields and their names stable — the signature is over
    ``json.dumps(data, sort_keys=True)``. The customer name is bounded so a typo
    or paste can't bloat the registry / keys.
    """
    customer = (customer or "").strip()
    if len(customer) > MAX_CUSTOMER_LEN:
        raise ValueError(f"Customer name too long (max {MAX_CUSTOMER_LEN} characters).")
    return {
        "customer": customer,
        "machine_id": machine_id,
        "expiry": expiry,
        "issued": issued or today_str(),
    }


def sign_license(private_key, data: dict) -> str:
    """Sign the canonical payload; return the base64 signature."""
    payload = json.dumps(data, sort_keys=True).encode()
    return base64.b64encode(private_key.sign(payload)).decode("utf-8")


def make_doc(private_key, data: dict) -> dict:
    """Build the signed license document ``{"data", "signature"}``."""
    return {"data": data, "signature": sign_license(private_key, data)}


def make_key(private_key, data: dict) -> str:
    """Sign ``data`` and encode it as the copy-pasteable license key string."""
    return encode_key(make_doc(private_key, data))


# --- Keypair generation / embedding ----------------------------------------

def guard_has_marker(guard_file: str = GUARD_FILE) -> bool:
    """True if license_guard.py still has the embeddable PUBLIC_KEY_PEM block."""
    try:
        with open(guard_file, encoding="utf-8") as f:
            return bool(_PEM_BLOCK.search(f.read()))
    except OSError:
        return False


def embedded_public_key_pem(guard_file: str = GUARD_FILE) -> bytes | None:
    """Extract the PUBLIC_KEY_PEM currently embedded in license_guard.py.

    Reads it as text (rather than importing license_guard, which would pull in Qt)
    so the manager can compare it against admin_keys/public_key.pem.
    """
    try:
        with open(guard_file, encoding="utf-8") as f:
            src = f.read()
    except OSError:
        return None
    match = _PEM_BLOCK.search(src)
    if not match:
        return None
    block = match.group(0)
    try:
        inner = block.split('b"""', 1)[1].rsplit('"""', 1)[0]
    except IndexError:
        return None
    return inner.encode("utf-8")


def public_key_fingerprint(pub_pem: bytes) -> str:
    """A short, stable fingerprint of a PEM public key for display/comparison."""
    normalized = b"".join(pub_pem.split())  # ignore whitespace/newline differences
    return hashlib.sha256(normalized).hexdigest()[:16]


def generate_keypair_and_embed(guard_file: str = GUARD_FILE,
                               keys_dir: str = KEYS_DIR) -> str:
    """Generate a fresh Ed25519 keypair and embed the public key into license_guard.py.

    Validates the embed target BEFORE generating anything: a missing marker raises
    without writing keys, so we never orphan a freshly rotated private key that no
    shipped license_guard.py trusts. Returns the new public-key PEM. Regenerating
    INVALIDATES every license already issued — callers must confirm first.
    """
    if not os.path.exists(guard_file):
        raise FileNotFoundError(
            f"{guard_file} not found. Run this from the project root.")
    with open(guard_file, encoding="utf-8") as f:
        guard_source = f.read()
    if not _PEM_BLOCK.search(guard_source):
        raise ValueError(
            f"Could not find the PUBLIC_KEY_PEM block in {guard_file}; "
            "aborting before generating keys.")

    os.makedirs(keys_dir, exist_ok=True)
    try:
        os.chmod(keys_dir, 0o700)  # owner-only; no-op where unsupported
    except OSError:
        pass
    private_key = ed25519.Ed25519PrivateKey.generate()
    public_key = private_key.public_key()

    private_key_path = os.path.join(keys_dir, "private_key.pem")
    with open(private_key_path, "wb") as f:
        f.write(private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ))
    # The private signing key is the crown jewel — restrict it to the owner so a
    # permissive umask can't leave it world-readable on Unix admin machines.
    try:
        os.chmod(private_key_path, 0o600)
    except OSError:
        pass

    pub_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    with open(os.path.join(keys_dir, "public_key.pem"), "w", encoding="utf-8") as f:
        f.write(pub_pem)

    # A lambda replacement avoids re.sub backreference interpretation in the PEM.
    new_block = f'PUBLIC_KEY_PEM = b"""{pub_pem.strip()}\n"""'
    updated = _PEM_BLOCK.sub(lambda _m: new_block, guard_source, count=1)
    with open(guard_file, "w", encoding="utf-8") as f:
        f.write(updated)
    return pub_pem


# --- Issuance registry -----------------------------------------------------

def load_registry(path: str = REGISTRY_FILE) -> dict:
    """Load the issuance registry, returning an empty one if absent/corrupt."""
    if not os.path.exists(path):
        return {"licenses": []}
    try:
        with open(path, encoding="utf-8") as f:
            reg = json.load(f)
    except (OSError, ValueError):
        return {"licenses": []}
    if not isinstance(reg, dict) or not isinstance(reg.get("licenses"), list):
        return {"licenses": []}
    return reg


def save_registry(reg: dict, path: str = REGISTRY_FILE) -> None:
    """Atomically persist the registry (temp file + os.replace)."""
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".reg_", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(reg, f, indent=2)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def find_entry(reg: dict, machine_id: str) -> dict | None:
    for entry in reg.get("licenses", []):
        if entry.get("machine_id") == machine_id:
            return entry
    return None


def record_issued(reg: dict, customer: str, machine_id: str,
                  issued: str, expiry: str) -> dict:
    """Record (or re-issue) a license in the registry, keyed by machine_id.

    A re-issue for a machine already present archives the prior issuance into the
    entry's ``history`` so the issuance trail is preserved. Mutates and returns the
    entry; the caller is responsible for ``save_registry``.
    """
    entry = find_entry(reg, machine_id)
    if entry is None:
        entry = {
            "customer": customer,
            "machine_id": machine_id,
            "issued": issued,
            "expiry": expiry,
            "history": [],
        }
        reg["licenses"].append(entry)
        return entry

    entry.setdefault("history", []).append(
        {"issued": entry.get("issued"), "expiry": entry.get("expiry")})
    entry["customer"] = customer
    entry["issued"] = issued
    entry["expiry"] = expiry
    return entry
