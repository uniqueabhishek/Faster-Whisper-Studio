"""Vendor License Manager — entry point.

Run with ``uv run python license_manager_app.py``. VENDOR-ONLY: this and the
modules it pulls in (license_manager_window, licensing_core) sign licenses with
the admin private key and must NEVER be bundled into the customer build.
"""

import sys

from PySide6.QtWidgets import QApplication

from license_manager_window import LicenseManagerWindow
from styles import DARK_THEME_QSS
from ui_common import app_icon


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("Faster-Whisper License Manager")
    app.setWindowIcon(app_icon())
    app.setStyleSheet(DARK_THEME_QSS)

    window = LicenseManagerWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
