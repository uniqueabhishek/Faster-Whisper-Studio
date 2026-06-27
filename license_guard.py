import os
import json
import logging
import hashlib
import wmi
import base64
import ntplib
import sys
from datetime import datetime
from PySide6.QtWidgets import QMessageBox
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives import serialization

LOGGER = logging.getLogger(__name__)

# --- EMBEDDED PUBLIC KEY (Populated by setup_security.py) ---
PUBLIC_KEY_PEM = b"""-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEAnT7y+CZ4m+2vzVbvuU4ydAKDBzUDMnnzF7ElUQFXed4=
-----END PUBLIC KEY-----
"""
LICENSE_FILE = "license.dat"


def _legacy_machine_id():
    """Fallback HWID from hostname + MAC. Unstable; used only if WMI fails."""
    import socket
    import uuid
    hostname = socket.gethostname()
    mac = uuid.getnode()
    raw_id = f"{hostname}-{mac}"
    return hashlib.sha256(raw_id.encode()).hexdigest()


def get_machine_id():
    """Generates a stable, unique Machine ID (HWID) from hardware serials.

    Uses the SMBIOS UUID, motherboard serial, and CPU ID via WMI. These
    survive reboots, network changes, and VPNs (unlike hostname/MAC). Falls
    back to the legacy hostname+MAC method only if WMI is unavailable.
    """
    try:
        c = wmi.WMI()
        parts = []

        try:
            uuid_val = c.Win32_ComputerSystemProduct()[0].UUID
            if uuid_val and uuid_val.strip("0-") and "FFFFFFFF" not in uuid_val.upper():
                parts.append(f"uuid:{uuid_val}")
        except Exception:  # pylint: disable=broad-except
            pass

        try:
            board_serial = c.Win32_BaseBoard()[0].SerialNumber
            if board_serial and board_serial.strip() and "O.E.M." not in board_serial.upper():
                parts.append(f"board:{board_serial.strip()}")
        except Exception:  # pylint: disable=broad-except
            pass

        try:
            cpu_id = c.Win32_Processor()[0].ProcessorId
            if cpu_id and cpu_id.strip():
                parts.append(f"cpu:{cpu_id.strip()}")
        except Exception:  # pylint: disable=broad-except
            pass

        if not parts:
            # No stable hardware identifiers available; fall back.
            return _legacy_machine_id()

        raw_id = "|".join(parts)
        return hashlib.sha256(raw_id.encode()).hexdigest()
    except Exception as e:  # pylint: disable=broad-except
        LOGGER.warning("WMI HWID failed, using legacy method: %s", e)
        try:
            return _legacy_machine_id()
        except Exception as e2:  # pylint: disable=broad-except
            LOGGER.error("Error generating HWID: %s", e2)
            return "ERROR_GENERATING_HWID"


def get_network_time():
    """Gets the current time from an NTP server."""
    try:
        client = ntplib.NTPClient()
        response = client.request('pool.ntp.org', version=3, timeout=5)
        return datetime.fromtimestamp(response.tx_time)
    except Exception as e:
        LOGGER.warning("NTP time fetch failed (using local time): %s", e)
        return None


def verify_license_gui():
    """
    Verifies the license and handles GUI alerts.
    Exits the app if invalid.
    """
    LOGGER.info("--- LICENSE CHECK ---")

    current_hwid = get_machine_id()
    LOGGER.info("Current Machine ID: %s", current_hwid)

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
        except Exception:  # pylint: disable=broad-except
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

        LOGGER.info("License Valid.")
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
    app.exec()
