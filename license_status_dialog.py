"""License details dialog — shown when the top-bar status button is clicked while
the app is registered. Displays who the license is registered to and when it
expires, and offers a 'Change License Key…' action that hands off to the
activation dialog.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from ui_common import center_window


def _expiry_line(status: dict) -> str:
    expiry = status.get("expiry") or "unknown"
    days = status.get("days_left")
    if days is None:
        return expiry
    if days < 0:
        return f"{expiry} (expired)"
    if days == 0:
        return f"{expiry} (expires today)"
    return f"{expiry} ({days} day{'s' if days != 1 else ''} left)"


class LicenseStatusDialog(QDialog):
    """Read-only license details with a re-key action.

    ``wants_change`` is True after the user clicks 'Change License Key…' so the
    caller can open the activation dialog next.
    """

    def __init__(self, status: dict, parent=None) -> None:
        super().__init__(parent)
        self.wants_change = False

        self.setWindowTitle("License")
        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        header = QLabel("License")
        header.setObjectName("Header")
        layout.addWidget(header)

        registered = status.get("registered")
        badge = QLabel("● Registered" if registered else "● Unregistered")
        badge.setStyleSheet(
            f"color: {'#34d399' if registered else '#f87171'}; font-weight: bold;")
        layout.addWidget(badge)

        form = QFormLayout()
        form.addRow("Registered to:", QLabel(status.get("customer") or "—"))
        form.addRow("Valid until:", QLabel(_expiry_line(status)))

        machine_field = QLineEdit(status.get("machine_id") or "")
        machine_field.setReadOnly(True)
        machine_field.setCursorPosition(0)
        form.addRow("Machine ID:", machine_field)
        layout.addLayout(form)

        if not registered and status.get("reason"):
            reason = QLabel(status["reason"])
            reason.setWordWrap(True)
            reason.setStyleSheet("color: #f87171;")
            layout.addWidget(reason)

        layout.addStretch()

        btn_row = QHBoxLayout()
        change_btn = QPushButton("Change License Key…")
        change_btn.setObjectName("SecondaryBtn")
        change_btn.clicked.connect(self._on_change)
        btn_row.addWidget(change_btn)
        btn_row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.setDefault(True)
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        center_window(self)

    def _on_change(self) -> None:
        self.wants_change = True
        self.accept()
