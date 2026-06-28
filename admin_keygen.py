"""Admin license generator (CLI). Prompts for customer details and prints a
license KEY string to send to the client. Signing/registry live in licensing_core.

VENDOR-ONLY — never ship this with the customer build.
"""

from datetime import datetime

import licensing_core as core


def main():
    """Prompt for customer details and print a signed license key."""
    try:
        private_key = core.load_private_key()
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}")
        return

    print("\n--- LICENSE GENERATOR (ADMIN ONLY) ---")
    customer_name = input("Enter Customer Name: ").strip()
    machine_id = input("Enter Customer's Machine ID: ").strip()
    if not core.is_valid_machine_id(machine_id):
        print("Invalid Machine ID — expected 64 hexadecimal characters.")
        return

    expiry_str = input("Enter Expiry Date (YYYY-MM-DD): ").strip()
    try:
        datetime.strptime(expiry_str, "%Y-%m-%d")
    except ValueError:
        print("Invalid date format! Use YYYY-MM-DD")
        return

    data = core.build_license_data(customer_name, machine_id, expiry_str)
    key = core.make_key(private_key, data)

    # Record the issuance so the manager can track/renew it later.
    reg = core.load_registry()
    core.record_issued(reg, customer_name, machine_id, data["issued"], expiry_str)
    core.save_registry(reg)

    print("\n[SUCCESS] License key — send this single string to the client:\n")
    print(key)


if __name__ == "__main__":
    main()
