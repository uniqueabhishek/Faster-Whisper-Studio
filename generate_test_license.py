"""Generate a DEV-TEST license key for THIS machine and install it locally.

Signs a one-year license for the current machine's HWID and writes the key
straight into the per-user store (``license.key``) so the app activates without a
manual paste. Vendor/dev convenience only — needs admin_keys/private_key.pem.
"""

from datetime import datetime, timedelta

import licensing_core as core
import license_guard


def main():
    try:
        private_key = core.load_private_key()
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}")
        return

    machine_id = license_guard.get_machine_id()
    expiry = (datetime.now() + timedelta(days=365)).strftime("%Y-%m-%d")
    data = core.build_license_data("DEV-TEST", machine_id, expiry)
    key = core.make_key(private_key, data)

    license_guard.save_key(key)

    print(f"[OK] Dev license installed to: {license_guard.license_key_path()}")
    print(f"  Machine ID: {machine_id}")
    print(f"  Expiry: {expiry}")
    print("\nKey:\n" + key)


if __name__ == "__main__":
    main()
