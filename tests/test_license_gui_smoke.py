"""Offscreen smoke test for the licensing GUIs.

Constructs the customer activation dialog and the vendor license-manager window
headlessly (Qt 'offscreen' platform) so import/enum/signal/layout regressions are
caught without a display. Mirrors tests/test_gui_smoke.py.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

# One QApplication per process — required before constructing any QWidget.
_app = QApplication.instance() or QApplication([])


def test_activation_dialog_constructs():
    from activation_dialog import ActivationDialog
    machine_id = "a" * 64
    dialog = ActivationDialog(machine_id)
    assert dialog is not None
    # The Machine ID must be shown so the customer can send it to the vendor.
    assert dialog._id_field.text() == machine_id


def test_license_manager_window_constructs():
    from license_manager_window import LicenseManagerWindow
    window = LicenseManagerWindow()
    assert window is not None


def test_license_status_dialog_constructs():
    from license_status_dialog import LicenseStatusDialog
    status = {"registered": True, "customer": "Acme Co", "expiry": "2099-01-01",
              "machine_id": "a" * 64, "days_left": 100, "reason": ""}
    dialog = LicenseStatusDialog(status)
    assert dialog.wants_change is False


def test_license_status_dialog_unregistered_shows_reason():
    from license_status_dialog import LicenseStatusDialog
    status = {"registered": False, "customer": None, "expiry": None,
              "machine_id": "a" * 64, "days_left": None,
              "reason": "No license installed on this machine."}
    dialog = LicenseStatusDialog(status)
    assert dialog is not None
