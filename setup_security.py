"""One-time admin bootstrap: generate the Ed25519 keypair and embed the public
key into license_guard.py.

Previously this read a ``license_guard_template.py`` that does not exist in the
repo, so a clean run crashed *after* writing a fresh private key — orphaning the
new key and leaving license_guard.py trusting the old one. This version embeds
the key directly into the existing license_guard.py and validates everything
before generating keys.
"""

import os
import re

from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives import serialization

KEYS_DIR = "admin_keys"
PRIVATE_KEY_FILE = os.path.join(KEYS_DIR, "private_key.pem")
PUBLIC_KEY_FILE = os.path.join(KEYS_DIR, "public_key.pem")
GUARD_FILE = "license_guard.py"

# Matches the embedded ``PUBLIC_KEY_PEM = b"""...-----END PUBLIC KEY-----..."""``.
_PEM_BLOCK = re.compile(r'PUBLIC_KEY_PEM\s*=\s*b""".*?"""', re.DOTALL)


def main():
    # Validate the target BEFORE touching any keys: a missing/renamed marker
    # must not leave us with a freshly rotated private key that no shipped
    # license_guard.py trusts.
    if not os.path.exists(GUARD_FILE):
        print(f"ERROR: {GUARD_FILE} not found. Run this from the project root.")
        return

    with open(GUARD_FILE, "r", encoding="utf-8") as f:
        guard_source = f.read()

    if not _PEM_BLOCK.search(guard_source):
        print(f"ERROR: Could not find the PUBLIC_KEY_PEM block in {GUARD_FILE}.")
        print("Aborting before generating keys to avoid orphaning a new keypair.")
        return

    if os.path.exists(PRIVATE_KEY_FILE):
        resp = input(
            "A private key already exists. Regenerating it will INVALIDATE every "
            "license already issued to customers. Continue? [y/N]: "
        ).strip().lower()
        if resp != "y":
            print("Aborted. Existing keys left untouched.")
            return

    os.makedirs(KEYS_DIR, exist_ok=True)

    print("Generating Ed25519 keypair...")
    private_key = ed25519.Ed25519PrivateKey.generate()
    public_key = private_key.public_key()

    # Save the private key (admin only).
    with open(PRIVATE_KEY_FILE, "wb") as f:
        f.write(private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ))

    # Save the public key (reference copy).
    pub_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    with open(PUBLIC_KEY_FILE, "w", encoding="utf-8") as f:
        f.write(pub_pem)

    print(f"Keys saved to {KEYS_DIR}/")

    # Embed the new public key directly into license_guard.py. A function
    # replacement avoids re.sub backreference interpretation in the PEM body.
    new_block = f'PUBLIC_KEY_PEM = b"""{pub_pem.strip()}\n"""'
    updated = _PEM_BLOCK.sub(lambda _m: new_block, guard_source, count=1)
    with open(GUARD_FILE, "w", encoding="utf-8") as f:
        f.write(updated)

    print(f"Embedded the new public key into {GUARD_FILE}.")
    print("Done. Keep admin_keys/ private and OUT of version control.")


if __name__ == "__main__":
    main()
