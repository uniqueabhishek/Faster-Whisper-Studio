"""Generate a test license file for development."""
import json
import base64
from datetime import datetime, timedelta
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

# Machine ID from the current system (from running license_guard.get_machine_id())
MACHINE_ID = "fbecff055511dac1f8a3d2125f67feff1853c49cb5d684f46b61ee347d6e5dd8"

# Load private key
with open("admin_keys/private_key.pem", "rb") as f:
    private_key = serialization.load_pem_private_key(
        f.read(),
        password=None,
        backend=default_backend()
    )

# Create license data
expiry_date = (datetime.now() + timedelta(days=365)).strftime("%Y-%m-%d")
license_data = {
    "machine_id": MACHINE_ID,
    "expiry": expiry_date,
    "issued": datetime.now().strftime("%Y-%m-%d"),
}

# Sign the data
data_json_str = json.dumps(license_data, sort_keys=True)
signature = private_key.sign(data_json_str.encode())
signature_b64 = base64.b64encode(signature).decode()

# Create license document
license_doc = {
    "data": license_data,
    "signature": signature_b64
}

# Save to license.dat
with open("license.dat", "w") as f:
    json.dump(license_doc, f, indent=2)

print(f"[OK] Test license created: license.dat")
print(f"  Machine ID: {MACHINE_ID}")
print(f"  Expiry: {expiry_date}")
