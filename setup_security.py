"""One-time admin bootstrap: generate the Ed25519 keypair and embed the public
key into license_guard.py. The actual work lives in licensing_core; this is just
the CLI wrapper with the destructive-action confirmation.

VENDOR-ONLY. Keep admin_keys/ private and OUT of version control.
"""

import licensing_core as core


def main():
    # Validate the embed target BEFORE touching any keys: a missing/renamed
    # marker must not leave us with a freshly rotated private key that no shipped
    # license_guard.py trusts.
    if not core.guard_has_marker():
        print(f"ERROR: Could not find the PUBLIC_KEY_PEM block in {core.GUARD_FILE}.")
        print("Run this from the project root. Aborting before generating keys.")
        return

    if core.keys_exist():
        resp = input(
            "A private key already exists. Regenerating it will INVALIDATE every "
            "license already issued to customers. Continue? [y/N]: "
        ).strip().lower()
        if resp != "y":
            print("Aborted. Existing keys left untouched.")
            return

    print("Generating Ed25519 keypair...")
    try:
        core.generate_keypair_and_embed()
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}")
        return

    print(f"Keys saved to {core.KEYS_DIR}/")
    print(f"Embedded the new public key into {core.GUARD_FILE}.")
    print("Done. Keep admin_keys/ private and OUT of version control.")


if __name__ == "__main__":
    main()
