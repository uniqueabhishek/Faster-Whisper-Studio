import os
import json
import hashlib
import wmi
import base64
import ntplib
import sys
from datetime import datetime
from PyQt5.QtWidgets import QMessageBox
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives import serialization

# --- EMBEDDED PUBLIC KEY (Populated by setup_security.py) ---
PUBLIC_KEY_PEM = b"""{{PUBLIC_KEY_PEM}}"""
LICENSE_FILE = "license.dat"


def get_machine_id():
    """Generates a unique Machine ID (HWID) based on hardware serials."""
    try:
        c = wmi.WMI()
        try:
            board = c.Win32_BaseBoard()[0].SerialNumber.strip()
        except:
            board = "UnknownBoard"

        try:
            cpu = c.Win32_Processor()[0].ProcessorId.strip()
        except:
            cpu = "UnknownCPU"

        try:
            disk = c.Win32_DiskDrive(MediaType="Fixed hard disk media")[
                0].SerialNumber.strip()
        except:
            # Fallback if no fixed disk found
            disk = "UnknownDisk"

        raw_id = f"{board}-{cpu}-{disk}"
        return hashlib.sha256(raw_id.encode()).hexdigest()
    except Exception as e:
        print(f"Error generating HWID: {e}")
        return "ERROR_GENERATING_HWID"


def get_network_time():
    """Gets the current time from an NTP server."""
    try:
        client = ntplib.NTPClient()
        response = client.request('pool.ntp.org', version=3)
        return datetime.fromtimestamp(response.tx_time)
    except:
        return None


def verify_license_gui():
    """
    Verifies the license and handles GUI alerts.
    Exits the app if invalid.
    """
    print("--- LICENSE CHECK ---")

    current_hwid = get_machine_id()
    print(f"Current Machine ID: {current_hwid}")

    if not os.path.exists(LICENSE_FILE):
        show_error("License Missing",
                   f"No license.dat found.\n\nYour Machine ID: {current_hwid}\n\nPlease contact support.")
        sys.exit(1)

    try:
        public_key = serialization.load_pem_public_key(PUBLIC_KEY_PEM)

        with open(LICENSE_FILE, "r") as f:
            license_doc = json.load(f)

        data = license_doc["data"]
        signature_b64 = license_doc["signature"]
        signature = base64.b64decode(signature_b64)

        # Verify Signature
        data_json_str = json.dumps(data, sort_keys=True)
        try:
            public_key.verify(signature, data_json_str.encode())
        except:
            show_error(
                "License Error", "Invalid License Signature.\n\nThe license file has been tampered with.")
            sys.exit(1)

        # Verify Machine ID
        if data["machine_id"] != current_hwid:
            show_error(
                "License Error", f"This license works on a different machine.\n\nRequired: {data['machine_id']}\nCurrent: {current_hwid}")
            sys.exit(1)

        # Verify Expiry
        expiry_date = datetime.strptime(data["expiry"], "%Y-%m-%d")
        current_time = get_network_time() or datetime.now()

        if current_time > expiry_date:
            show_error("Subscription Expired",
                       f"Your subscription ended on {data['expiry']}.\nPlease renew.")
            sys.exit(1)

        print("License Valid.")
        return True

    except Exception as e:
        show_error("License Error", f"Failed to verify license: {e}")
        sys.exit(1)


def show_error(title, message):
    app = QMessageBox()
    app.setIcon(QMessageBox.Critical)
    app.setWindowTitle(title)
    app.setText(message)
    app.setStandardButtons(QMessageBox.Ok)
    app.exec_()
