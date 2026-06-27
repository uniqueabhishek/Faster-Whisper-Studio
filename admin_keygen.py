"""Admin license key generator for customer license files."""

import os
import json
import base64
from datetime import datetime
from cryptography.hazmat.primitives import serialization

KEYS_DIR = "admin_keys"
PRIVATE_KEY_FILE = os.path.join(KEYS_DIR, "private_key.pem")


def load_private_key():
    """Load the admin private key from disk."""
    if not os.path.exists(PRIVATE_KEY_FILE):
        print(f"ERROR: Private key not found at {PRIVATE_KEY_FILE}")
        print("Please run setup_security.py first!")
        return None

    with open(PRIVATE_KEY_FILE, "rb") as f:
        return serialization.load_pem_private_key(f.read(), password=None)


def main():
    """Prompt for customer details and generate a signed license file."""
    private_key = load_private_key()
    if not private_key:
        return

    print("\n--- LICENSE GENERATOR (ADMIN ONLY) ---")
    customer_name = input("Enter Customer Name: ").strip()
    machine_id = input("Enter Customer's Machine ID: ").strip()
    expiry_str = input("Enter Expiry Date (YYYY-MM-DD): ").strip()

    try:
        datetime.strptime(expiry_str, "%Y-%m-%d")
    except ValueError:
        print("Invalid date format! Use YYYY-MM-DD")
        return

    # Canonical schema shared with generate_test_license.py.
    license_data = {
        "customer": customer_name,
        "machine_id": machine_id,
        "expiry": expiry_str,
        "issued": datetime.now().strftime("%Y-%m-%d"),
    }

    license_json = json.dumps(license_data, sort_keys=True)
    signature = private_key.sign(license_json.encode())

    final_license = {
        "data": license_data,
        "signature": base64.b64encode(signature).decode('utf-8')
    }

    filename = f"license_{customer_name.replace(' ', '_')}.dat"
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(final_license, f, indent=4)

    print(f"\n[SUCCESS] License saved to: {filename}")
    print("Send this file to the client.")


if __name__ == "__main__":
    main()
