"""Customer license-activation screen.

Shown at startup when there's no valid saved license. Displays this machine's
Machine ID (to send to the vendor) and takes a pasted license key, which it
decodes, verifies against this machine, and — on success — saves to the per-user
store so the app won't ask again. Accepts only on a verified key; rejecting
(Quit) lets the caller exit the app.
"""

from __future__ import annotations

from PySide6.QtCore import QCoreApplication
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

import license_guard
from license_codec import decode_key, encode_key
from styles import DARK_THEME_QSS
from ui_common import app_icon, center_window


class ActivationDialog(QDialog):
    """Paste-a-key activation dialog. Self-styled because it can open before the
    main window applies the global stylesheet."""

    def __init__(self, machine_id: str, parent=None, *,
                 cancel_label: str = "Quit", initial_message: str = "") -> None:
        super().__init__(parent)
        self._machine_id = machine_id

        self.setWindowTitle("Activate Faster-Whisper")
        self.setWindowIcon(app_icon())
        self.setStyleSheet(DARK_THEME_QSS)
        self.setMinimumWidth(560)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        header = QLabel("Activate your license")
        header.setObjectName("Header")
        layout.addWidget(header)

        intro = QLabel(
            "Send your <b>Machine ID</b> to your vendor to receive a license key, "
            "then paste the key below and click <b>Activate</b>.")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        # Machine ID (read-only) + Copy.
        layout.addWidget(QLabel("Your Machine ID:"))
        id_row = QHBoxLayout()
        self._id_field = QLineEdit(machine_id)
        self._id_field.setReadOnly(True)
        self._id_field.setCursorPosition(0)
        id_row.addWidget(self._id_field)
        copy_btn = QPushButton("Copy")
        copy_btn.setObjectName("SecondaryBtn")
        copy_btn.clicked.connect(self._on_copy)
        id_row.addWidget(copy_btn)
        layout.addLayout(id_row)

        # Key paste box.
        layout.addWidget(QLabel("License key:"))
        self._key_edit = QTextEdit()
        self._key_edit.setPlaceholderText("Paste your license key here (starts with FWL-)…")
        self._key_edit.setFixedHeight(90)
        self._key_edit.setAcceptRichText(False)
        layout.addWidget(self._key_edit)

        # Inline status / error line.
        self._status = QLabel("")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        # Buttons.
        btn_row = QHBoxLayout()
        cancel_btn = QPushButton(cancel_label)
        cancel_btn.setObjectName("SecondaryBtn")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        btn_row.addStretch()
        self._activate_btn = QPushButton("Activate")
        self._activate_btn.setDefault(True)
        self._activate_btn.clicked.connect(self._on_activate)
        btn_row.addWidget(self._activate_btn)
        layout.addLayout(btn_row)

        if initial_message:
            self._set_status(initial_message, error=True)

        center_window(self)

    # --- helpers -----------------------------------------------------------

    def _set_status(self, message: str, *, error: bool = False) -> None:
        color = "#f87171" if error else "#34d399"
        self._status.setStyleSheet(f"color: {color};")
        self._status.setText(message)

    def _on_copy(self) -> None:
        clipboard = QGuiApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(self._machine_id)
            self._set_status("Machine ID copied to clipboard.")

    def _on_activate(self) -> None:
        text = self._key_edit.toPlainText()
        if not text.strip():
            self._set_status("Please paste your license key.", error=True)
            return

        try:
            doc = decode_key(text)
        except ValueError as exc:
            self._set_status(str(exc), error=True)
            return

        # verify_license_doc may briefly block on an NTP lookup; reflect that.
        self._activate_btn.setEnabled(False)
        self._set_status("Verifying license…")
        QCoreApplication.processEvents()
        try:
            ok, reason = license_guard.verify_license_doc(doc, self._machine_id)
        finally:
            self._activate_btn.setEnabled(True)

        if not ok:
            self._set_status(reason, error=True)
            return

        try:
            license_guard.save_key(encode_key(doc))
        except OSError as exc:
            self._set_status(f"Could not save the license: {exc}", error=True)
            return

        self.accept()
