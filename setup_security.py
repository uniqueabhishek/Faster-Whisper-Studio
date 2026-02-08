import os
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives import serialization

KEYS_DIR = "admin_keys"
PRIVATE_KEY_FILE = os.path.join(KEYS_DIR, "private_key.pem")
PUBLIC_KEY_FILE = os.path.join(KEYS_DIR, "public_key.pem")


def main():
    if not os.path.exists(KEYS_DIR):
        os.makedirs(KEYS_DIR)

    print("Generating Ed25519 Keypair...")
    private_key = ed25519.Ed25519PrivateKey.generate()
    public_key = private_key.public_key()

    # Save Private Key (Admin Only)
    with open(PRIVATE_KEY_FILE, "wb") as f:
        f.write(private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        ))

    # Get Public Key PEM as string
    pub_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode('utf-8')

    # Save Public Key file (just in case)
    with open(PUBLIC_KEY_FILE, "w") as f:
        f.write(pub_pem)

    print(f"Keys saved to {KEYS_DIR}/")

    # Embed into license_guard.py
    with open("license_guard_template.py", "r") as f:
        template = f.read()

    # Replace placeholder
    # formatting note: we strip the header/footer lines from PEM if we want,
    # but the PEM loader expects them.
    # The template uses triple quotes b""" ... """, so we just inject the string.

    final_code = template.replace("{{PUBLIC_KEY_PEM}}", pub_pem)

    with open("license_guard.py", "w") as f:
        f.write(final_code)

    print("Created license_guard.py with EMBEDDED Public Key.")

    # Cleanup template
    if os.path.exists("license_guard_template.py"):
        os.remove("license_guard_template.py")


if __name__ == "__main__":
    main()
