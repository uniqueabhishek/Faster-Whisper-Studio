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
from cryptography.hazmat.primitives import serialization

from license_codec import decode_key

LOGGER = logging.getLogger(__name__)

# --- EMBEDDED PUBLIC KEY (Populated by setup_security.py) ---
PUBLIC_KEY_PEM = b"""-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEAnT7y+CZ4m+2vzVbvuU4ydAKDBzUDMnnzF7ElUQFXed4=
-----END PUBLIC KEY-----
"""

# --- Anti-rollback state (offline clock-rollback defense) ---
# Not a real secret (it ships in the binary), but binding the HMAC to it AND the
# machine HWID raises the bar above trivially editing a stored date or copying
# the state file between machines.
_ROLLBACK_SECRET = b"fwgui-anti-rollback-v1"
# Tolerance so a small, benign clock correction doesn't trip the guard.
_ROLLBACK_GRACE = timedelta(days=1)


def _restrict(path: str, mode: int) -> None:
    """Best-effort owner-only permissions; a no-op where the OS doesn't support it."""
    try:
        os.chmod(path, mode)
    except OSError:
        pass


def _appdata_dir() -> str:
    """Per-user, writable app-data directory (works for an installed exe too)."""
    base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    directory = os.path.join(base, "FasterWhisperGUI")
    os.makedirs(directory, exist_ok=True)
    _restrict(directory, 0o700)  # keep the license/state out of other users' reach
    return directory


def _state_path() -> str:
    return os.path.join(_appdata_dir(), ".state")


def license_key_path() -> str:
    """Where the activated license key is persisted between launches."""
    return os.path.join(_appdata_dir(), "license.key")


def load_saved_key() -> "str | None":
    """Return the saved license-key string, or None if absent/unreadable/empty."""
    try:
        with open(license_key_path(), "r", encoding="utf-8") as f:
            key = f.read().strip()
        return key or None
    except OSError:
        return None


def save_key(key_str: str) -> None:
    """Atomically persist the activated license key to the per-user store."""
    directory = _appdata_dir()
    fd, tmp = tempfile.mkstemp(prefix=".license_", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(key_str.strip())
        os.replace(tmp, license_key_path())
        _restrict(license_key_path(), 0o600)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def _state_mac(hwid: str, ts: float) -> str:
    key = hashlib.sha256(_ROLLBACK_SECRET + hwid.encode()).digest()
    return hmac.new(key, repr(ts).encode(), hashlib.sha256).hexdigest()


def _read_last_seen(hwid: str, path: str | None = None) -> "datetime | None":
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


# Returned when no stable hardware identifier can be read. Deliberately NOT a
# usable ID: node-locking fails closed rather than falling back to a spoofable
# hostname+MAC hash (which both defeats node-locking and can lock out legitimate
# users when those values change). Verification rejects this value.
HWID_UNAVAILABLE = "HWID_UNAVAILABLE"


def get_machine_id():
    """Generate a stable, unique Machine ID (HWID) from hardware serials.

    Uses the SMBIOS UUID, motherboard serial, and CPU ID via WMI — these survive
    reboots, network changes, and VPNs. If none can be read, returns
    ``HWID_UNAVAILABLE`` so the license check fails closed; we never derive an ID
    from spoofable hostname/MAC values.
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
            LOGGER.error("No stable hardware identifiers available; HWID unavailable.")
            return HWID_UNAVAILABLE

        raw_id = "|".join(parts)
        return hashlib.sha256(raw_id.encode()).hexdigest()
    except Exception as e:  # pylint: disable=broad-except
        LOGGER.error("WMI HWID generation failed: %s", e)
        return HWID_UNAVAILABLE


def get_network_time():
    """Gets the current time from an NTP server."""
    try:
        client = ntplib.NTPClient()
        response = client.request('pool.ntp.org', version=3, timeout=5)
        return datetime.fromtimestamp(response.tx_time)
    except Exception as e:
        LOGGER.warning("NTP time fetch failed (using local time): %s", e)
        return None


def _verify_static(license_doc, current_hwid):
    """Time-independent license checks: signature, required fields, machine match.

    Returns ``(ok, data, reason)`` where ``data`` is the inner payload (it may be
    returned even on failure — e.g. wrong-machine — so callers can still display
    the customer/expiry). No network, no clock: shared by the authoritative gate
    (verify_license_doc, which then checks expiry) and the lightweight UI status
    (license_status).
    """
    try:
        data = license_doc["data"]
        signature = base64.b64decode(license_doc["signature"])
    except (KeyError, TypeError, ValueError):
        return False, None, "This license key is malformed. Please contact support."

    public_key = serialization.load_pem_public_key(PUBLIC_KEY_PEM)
    payload = json.dumps(data, sort_keys=True).encode()
    try:
        public_key.verify(signature, payload)
    except Exception:  # pylint: disable=broad-except
        # Debug, not warning: license_status() calls this on every status refresh,
        # so a wrong-product key shouldn't spam the log at a higher level.
        LOGGER.debug("License signature verification failed.")
        return False, None, ("Invalid license signature.\n\nThis key was not issued "
                             "for this product, or it has been altered.")

    if not isinstance(data, dict) or "machine_id" not in data or "expiry" not in data:
        return False, data if isinstance(data, dict) else None, \
            "This license is missing required fields. Please contact support."

    # Fail closed if we couldn't read a stable hardware ID, rather than matching
    # against a spoofable fallback.
    if not current_hwid or current_hwid == HWID_UNAVAILABLE:
        return False, data, ("Could not read a stable hardware ID for this machine.\n\n"
                             "Please contact support.")

    if data["machine_id"] != current_hwid:
        return False, data, (f"This license is for a different machine.\n\n"
                             f"Required: {data['machine_id']}\nThis machine: {current_hwid}")

    return True, data, ""


def verify_license_doc(license_doc, current_hwid):
    """Verify a decoded license document against this machine.

    Returns ``(ok, reason)`` — ``reason`` is a user-facing message when ``ok`` is
    False. Runs the same checks the app relies on: Ed25519 signature over the
    canonical payload, required fields, machine-id match, and expiry with the
    offline clock-rollback defense. Writes the anti-rollback high-water mark as a
    side effect whenever it can establish a trustworthy current time.
    """
    ok, data, reason = _verify_static(license_doc, current_hwid)
    if not ok:
        return False, reason

    try:
        expiry_date = datetime.strptime(data["expiry"], "%Y-%m-%d")
    except (ValueError, TypeError):
        return False, "This license has an invalid expiry date. Please contact support."

    # Establish a trustworthy "now": NTP when online, else the local clock guarded
    # against being rolled backwards below the last-seen high-water mark.
    last_seen = None
    ntp_time = get_network_time()
    if ntp_time is not None:
        # Online: NTP is authoritative and a rolled-back local clock is moot.
        current_time = ntp_time
    else:
        # Offline: trust the local clock only if it hasn't moved backwards below
        # the last time we ran (which is how expiry gets defeated).
        current_time = datetime.now()
        last_seen = _read_last_seen(current_hwid)
        if _is_rollback(current_time, last_seen):
            return False, ("Could not verify the date online, and the system clock "
                           "appears to have moved backwards.\n\nPlease connect to the "
                           "internet, or set your clock to the correct date and time, "
                           "then try again.")

    if current_time > expiry_date:
        return False, f"Your subscription ended on {data['expiry']}.\nPlease renew."

    # Record the high-water mark only for a fully-valid license, so a rejected
    # (e.g. expired) one never advances the anti-rollback state.
    _write_last_seen(
        current_hwid,
        current_time if last_seen is None else max(current_time, last_seen))
    return True, ""


def verify_license_gui():
    """Ensure the app is licensed, prompting for activation if needed.

    Tries the previously-activated key first; if there isn't a valid one, opens
    the activation dialog (paste a key) and loops there until the user activates
    or cancels. Returns True when licensed; exits the app otherwise.
    """
    LOGGER.info("--- LICENSE CHECK ---")

    current_hwid = get_machine_id()
    LOGGER.info("Current Machine ID: %s", current_hwid)

    # 1) Try the previously-activated key from the per-user store.
    saved = load_saved_key()
    if saved:
        try:
            ok, reason = verify_license_doc(decode_key(saved), current_hwid)
            if ok:
                LOGGER.info("License Valid.")
                return True
            LOGGER.warning("Saved license rejected: %s", reason.splitlines()[0])
        except ValueError as exc:
            LOGGER.warning("Saved license key unreadable: %s", exc)

    # 2) No valid saved key — prompt the user to paste one.
    try:
        from activation_dialog import ActivationDialog  # pylint: disable=import-outside-toplevel
    except Exception as exc:  # pylint: disable=broad-except
        show_error("License Error", f"Activation screen unavailable: {exc}")
        sys.exit(1)

    dialog = ActivationDialog(current_hwid)
    if dialog.exec():  # the dialog only accepts on a verified key it has saved
        LOGGER.info("License activated.")
        return True

    LOGGER.info("Activation cancelled; exiting.")
    sys.exit(1)


def license_status():
    """Lightweight, network-free license status for UI display.

    Reads the saved key and checks signature, fields, machine match, and expiry
    against the *local* clock — no NTP — so it's cheap enough to call when drawing
    a status indicator. This is for display only; the authoritative gate is
    ``verify_license_gui`` at startup (which also runs the NTP/anti-rollback
    check). Returns a dict: ``registered`` (bool), ``customer``, ``expiry``,
    ``machine_id`` (this machine), ``days_left`` (int or None), ``reason`` (why
    not registered, for display).
    """
    info = {
        "registered": False,
        "customer": None,
        "expiry": None,
        "machine_id": None,
        "days_left": None,
        "reason": "",
    }

    current_hwid = get_machine_id()
    info["machine_id"] = current_hwid

    saved = load_saved_key()
    if not saved:
        info["reason"] = "No license installed on this machine."
        return info

    try:
        doc = decode_key(saved)
    except ValueError as exc:
        info["reason"] = str(exc)
        return info

    ok, data, reason = _verify_static(doc, current_hwid)
    if isinstance(data, dict):
        info["customer"] = data.get("customer")
        info["expiry"] = data.get("expiry")
    if not ok:
        info["reason"] = reason
        return info

    try:
        expiry_date = datetime.strptime(data["expiry"], "%Y-%m-%d")
    except (ValueError, TypeError):
        info["reason"] = "This license has an invalid expiry date."
        return info

    now = datetime.now()
    info["days_left"] = (expiry_date.date() - now.date()).days
    if now > expiry_date:
        info["reason"] = f"Subscription expired on {data['expiry']}."
        return info

    info["registered"] = True
    return info


def show_error(title: str, message: str) -> None:
    """Show a blocking critical-error message box with an OK button."""
    app = QMessageBox()
    app.setIcon(QMessageBox.Critical)
    app.setWindowTitle(title)
    app.setText(message)
    app.setStandardButtons(QMessageBox.Ok)
    app.exec()
