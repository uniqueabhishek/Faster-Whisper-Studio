import os
import sys


def check():
    result = []

    # 1. Check Import
    try:
        import cryptography
        result.append("PASS: Cryptography installed")
    except ImportError as e:
        result.append(f"FAIL: Cryptography NOT installed ({e})")

    # 2. Check Admin Keys
    if os.path.exists("admin_keys/private_key.pem"):
        result.append("PASS: keys generated")
    else:
        result.append("FAIL: keys missing")

    # 3. Check License Guard
    if os.path.exists("license_guard.py") and "PUBLIC_KEY_PEM" in open("license_guard.py").read():
        result.append("PASS: license_guard.py configured")
    else:
        result.append("FAIL: license_guard.py missing or incomplete")

    with open("verify_result.txt", "w") as f:
        f.write("\n".join(result))


if __name__ == "__main__":
    check()
