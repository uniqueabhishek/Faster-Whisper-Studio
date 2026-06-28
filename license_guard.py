import os
import json
import logging
import hashlib
import hmac
import tempfile
import wmi
import base64
import ntplib
import sys
from datetime import datetime, timedelta
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

# --- Anti-rollback state (offline clock-rollback defense) ---
# Not a real secret (it ships in the binary), but binding the HMAC to it AND the
# machine HWID raises the bar above trivially editing a stored date or copying
# the state file between machines.
_ROLLBACK_SECRET = b"fwgui-anti-rollback-v1"
# Tolerance so a small, benign clock correction doesn't trip the guard.
_ROLLBACK_GRACE = timedelta(days=1)


def _state_path() -> str:
    base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    directory = os.path.join(base, "FasterWhisperGUI")
    os.makedirs(directory, exist_ok=True)
    return os.path.join(directory, ".state")


def _state_mac(hwid: str, ts: float) -> str:
    key = hashlib.sha256(_ROLLBACK_SECRET + hwid.encode()).digest()
    return hmac.new(key, repr(ts).encode(), hashlib.sha256).hexdigest()


def _read_last_seen(hwid: str, path=None):
    """Return the stored high-water-mark time, or None if absent/tampered."""
    try:
        with open(path or _state_path(), "r", encoding="utf-8") as f:
            doc = json.load(f)
        ts = float(doc["ts"])
        if not hmac.compare_digest(doc.get("mac", ""), _state_mac(hwid, ts)):
            return None  # tampered, or copied from another machine
        return datetime.fromtimestamp(ts)
    except Exception:  # pylint: disable=broad-except
        return None


def _write_last_seen(hwid: str, dt: datetime, path=None) -> None:
    try:
        ts = dt.timestamp()
        with open(path or _state_path(), "w", encoding="utf-8") as f:
            json.dump({"ts": ts, "mac": _state_mac(hwid, ts)}, f)
    except OSError:
        pass


def _is_rollback(current: datetime, last_seen, grace: timedelta = _ROLLBACK_GRACE) -> bool:
    """True if the clock appears set backwards relative to the last-seen time."""
    return last_seen is not None and current < last_seen - grace


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

        # Validate required fields before indexing (clear error vs opaque KeyError).
        if "machine_id" not in data or "expiry" not in data:
            show_error("License Error",
                       "License file is missing required fields. Please contact support.")
            sys.exit(1)

        # Verify Machine ID
        if data["machine_id"] != current_hwid:
            show_error(
                "License Error", f"This license works on a different machine.\n\nRequired: {data['machine_id']}\nCurrent: {current_hwid}")
            sys.exit(1)

        # Verify Expiry (with offline clock-rollback defense).
        expiry_date = datetime.strptime(data["expiry"], "%Y-%m-%d")

        ntp_time = get_network_time()
        if ntp_time is not None:
            # Online: NTP is authoritative and a rolled-back local clock is moot.
            current_time = ntp_time
            _write_last_seen(current_hwid, current_time)
        else:
            # Offline: trust the local clock only if it hasn't moved backwards
            # below the last time we ran (which is how expiry gets defeated).
            current_time = datetime.now()
            last_seen = _read_last_seen(current_hwid)
            if _is_rollback(current_time, last_seen):
                show_error(
                    "License Error",
                    "Could not verify the date online, and the system clock appears to "
                    "have moved backwards.\n\nPlease connect to the internet, or set your "
                    "clock to the correct date and time, then try again.")
                sys.exit(1)
            _write_last_seen(
                current_hwid, max(current_time, last_seen) if last_seen else current_time)

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
