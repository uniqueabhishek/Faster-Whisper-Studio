import hashlib
import wmi
import sys
import ntplib
from datetime import datetime
from PyQt5.QtWidgets import QMessageBox

# --- HARD CODED ID (Injected by build_for_customer.py) ---
TARGET_HWID = "{{TARGET_HWID}}"

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
            disk = c.Win32_DiskDrive(MediaType="Fixed hard disk media")[0].SerialNumber.strip()
        except:
            disk = "UnknownDisk"

        raw_id = f"{board}-{cpu}-{disk}"
        return hashlib.sha256(raw_id.encode()).hexdigest()
    except Exception as e:
        print(f"Error generating HWID: {e}")
        return "ERROR_GENERATING_HWID"

def verify_license_gui():
    """
    Verifies that the current machine matches the HARD CODED target.
    """
    print("--- HARD CODED LICENSE CHECK ---")

    current_hwid = get_machine_id()
    print(f"Current Machine ID: {current_hwid}")
    print(f"Target Machine ID : {TARGET_HWID}")

    if current_hwid == TARGET_HWID:
        print("License Valid (ID Matches).")
        return True
    else:
        show_error(
            "Access Denied",
            f"This software is not licensed for this machine.\n\n"
            f"Authorized ID: ...{TARGET_HWID[-6:]}\n"
            f"Current ID: ...{current_hwid[-6:]}\n\n"
            f"Please contact support."
        )
        return False

def show_error(title, message):
    app = QMessageBox()
    app.setIcon(QMessageBox.Critical)
    app.setWindowTitle(title)
    app.setText(message)
    app.setStandardButtons(QMessageBox.Ok)
    app.exec_()
