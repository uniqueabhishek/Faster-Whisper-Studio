"""Vendor License Manager — main window (Generate / Manage / Keys tabs).

VENDOR-ONLY tooling: signs customer license keys with the admin private key,
tracks issuances in license_registry.json, and manages the keypair embedded in
the app. This module imports licensing_core (the signing toolchain) and must
NEVER be bundled into the customer build.
"""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDateEdit,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

import licensing_core as core
from styles import apply_dark_title_bar


def _copy_to_clipboard(text: str) -> None:
    clipboard = QGuiApplication.clipboard()
    if clipboard is not None:
        clipboard.setText(text)


def _status_for(expiry: str) -> str:
    try:
        expired = datetime.strptime(expiry, "%Y-%m-%d").date() < datetime.now().date()
    except (ValueError, TypeError):
        return "Unknown"
    return "Expired" if expired else "Active"


class GenerateTab(QWidget):
    """Issue a new license key for a customer's machine."""

    def __init__(self, window: "LicenseManagerWindow") -> None:
        super().__init__()
        self._window = window

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self._customer = QLineEdit()
        self._customer.setPlaceholderText("Customer or company name")
        form.addRow("Customer:", self._customer)

        id_row = QHBoxLayout()
        self._machine_id = QLineEdit()
        self._machine_id.setPlaceholderText("64-character hardware ID from the customer")
        id_row.addWidget(self._machine_id)
        load_btn = QPushButton("Load machine_id.txt")
        load_btn.setObjectName("SecondaryBtn")
        load_btn.clicked.connect(self._on_load_machine_id)
        id_row.addWidget(load_btn)
        form.addRow("Machine ID:", id_row)

        expiry_row = QHBoxLayout()
        self._expiry = QDateEdit()
        self._expiry.setCalendarPopup(True)
        self._expiry.setDisplayFormat("yyyy-MM-dd")
        self._expiry.setDate(QDate.currentDate().addYears(1))
        expiry_row.addWidget(self._expiry)
        for label, days in (("+30d", 30), ("+90d", 90), ("+1y", 365)):
            btn = QPushButton(label)
            btn.setObjectName("SecondaryBtn")
            btn.clicked.connect(lambda _checked=False, d=days: self._expiry.setDate(
                QDate.currentDate().addDays(d)))
            expiry_row.addWidget(btn)
        form.addRow("Expiry:", expiry_row)

        layout.addLayout(form)

        self._generate_btn = QPushButton("Generate License Key")
        self._generate_btn.clicked.connect(self._on_generate)
        layout.addWidget(self._generate_btn)

        layout.addWidget(QLabel("License key (send this string to the customer):"))
        self._output = QTextEdit()
        self._output.setReadOnly(True)
        self._output.setFixedHeight(110)
        layout.addWidget(self._output)

        self._copy_btn = QPushButton("Copy Key")
        self._copy_btn.setObjectName("SecondaryBtn")
        self._copy_btn.setEnabled(False)
        self._copy_btn.clicked.connect(lambda: _copy_to_clipboard(self._output.toPlainText()))
        layout.addWidget(self._copy_btn)

        layout.addStretch()

    def _on_load_machine_id(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open machine_id.txt", "", "Text files (*.txt);;All files (*)")
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                self._machine_id.setText(f.read().strip())
        except OSError as exc:
            QMessageBox.warning(self, "Could not read file", str(exc))

    def _on_generate(self) -> None:
        customer = self._customer.text().strip()
        machine_id = self._machine_id.text().strip()
        expiry = self._expiry.date().toString("yyyy-MM-dd")

        if not customer:
            QMessageBox.warning(self, "Missing customer", "Enter a customer name.")
            return
        if not core.is_valid_machine_id(machine_id):
            QMessageBox.warning(
                self, "Invalid Machine ID",
                "The Machine ID must be 64 hexadecimal characters.")
            return
        if self._expiry.date() < QDate.currentDate():
            QMessageBox.warning(self, "Invalid expiry", "Expiry is in the past.")
            return

        private_key = self._window.require_private_key()
        if private_key is None:
            return

        data = core.build_license_data(customer, machine_id, expiry)
        key = core.make_key(private_key, data)

        reg = core.load_registry()
        core.record_issued(reg, customer, machine_id, data["issued"], expiry)
        core.save_registry(reg)

        self._output.setPlainText(key)
        self._copy_btn.setEnabled(True)
        _copy_to_clipboard(key)
        self._window.refresh_manage()
        QMessageBox.information(
            self, "License generated",
            "The license key has been generated and copied to the clipboard.")


class ManageTab(QWidget):
    """Browse issued licenses; renew or re-copy a key for any of them."""

    COLUMNS = ["Customer", "Machine ID", "Issued", "Expiry", "Status"]

    def __init__(self, window: "LicenseManagerWindow") -> None:
        super().__init__()
        self._window = window
        self._rows: list[dict] = []  # registry entries, parallel to table rows

        layout = QVBoxLayout(self)

        top = QHBoxLayout()
        self._search = QLineEdit()
        self._search.setPlaceholderText("Search by customer or machine ID…")
        self._search.textChanged.connect(self._populate)
        top.addWidget(self._search)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.setObjectName("SecondaryBtn")
        refresh_btn.clicked.connect(self.refresh)
        top.addWidget(refresh_btn)
        layout.addLayout(top)

        self._table = QTableWidget(0, len(self.COLUMNS))
        self._table.setHorizontalHeaderLabels(self.COLUMNS)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        layout.addWidget(self._table)

        actions = QHBoxLayout()
        actions.addStretch()
        copy_btn = QPushButton("Copy Key")
        copy_btn.setObjectName("SecondaryBtn")
        copy_btn.clicked.connect(self._on_copy_key)
        actions.addWidget(copy_btn)
        renew_btn = QPushButton("Renew / Re-issue")
        renew_btn.clicked.connect(self._on_renew)
        actions.addWidget(renew_btn)
        layout.addLayout(actions)

        self.refresh()

    def refresh(self) -> None:
        self._registry = core.load_registry()
        self._populate()

    def _populate(self) -> None:
        query = self._search.text().strip().lower()
        entries = self._registry.get("licenses", [])
        self._rows = [
            e for e in entries
            if query in e.get("customer", "").lower()
            or query in e.get("machine_id", "").lower()
        ]
        self._table.setRowCount(len(self._rows))
        for row, entry in enumerate(self._rows):
            values = [
                entry.get("customer", ""),
                entry.get("machine_id", ""),
                entry.get("issued", ""),
                entry.get("expiry", ""),
                _status_for(entry.get("expiry", "")),
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col == 4:  # color the status
                    item.setForeground(
                        QColor("#f87171") if value == "Expired" else QColor("#34d399"))
                self._table.setItem(row, col, item)

    def _selected_entry(self) -> dict | None:
        row = self._table.currentRow()
        if row < 0 or row >= len(self._rows):
            QMessageBox.information(self, "No selection", "Select a license row first.")
            return None
        return self._rows[row]

    def _on_copy_key(self) -> None:
        entry = self._selected_entry()
        if entry is None:
            return
        private_key = self._window.require_private_key()
        if private_key is None:
            return
        # Reproduce the exact key as originally issued (same issued + expiry).
        data = core.build_license_data(
            entry["customer"], entry["machine_id"], entry["expiry"],
            issued=entry.get("issued"))
        _copy_to_clipboard(core.make_key(private_key, data))
        QMessageBox.information(self, "Key copied", "The license key was copied to the clipboard.")

    def _on_renew(self) -> None:
        entry = self._selected_entry()
        if entry is None:
            return
        days, ok = QInputDialog.getInt(
            self, "Renew / Re-issue",
            f"Issue a new key for {entry['customer']} valid for how many days?",
            365, 1, 3650)
        if not ok:
            return
        private_key = self._window.require_private_key()
        if private_key is None:
            return

        expiry = core.expiry_from_days(days)
        data = core.build_license_data(entry["customer"], entry["machine_id"], expiry)
        key = core.make_key(private_key, data)

        reg = core.load_registry()
        core.record_issued(reg, entry["customer"], entry["machine_id"], data["issued"], expiry)
        core.save_registry(reg)

        _copy_to_clipboard(key)
        self.refresh()
        QMessageBox.information(
            self, "License re-issued",
            f"New key (valid until {expiry}) generated and copied to the clipboard.")


class KeysTab(QWidget):
    """Inspect the signing keypair and (carefully) regenerate it."""

    def __init__(self, window: "LicenseManagerWindow") -> None:
        super().__init__()
        self._window = window

        layout = QVBoxLayout(self)
        self._info = QLabel()
        self._info.setWordWrap(True)
        self._info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self._info)

        layout.addSpacing(20)
        danger = QLabel("⚠ Danger zone")
        danger.setStyleSheet("color: #f87171; font-weight: bold; font-size: 16px;")
        layout.addWidget(danger)
        warn = QLabel(
            "Regenerating the keypair embeds a NEW public key into the app and "
            "INVALIDATES every license already issued. Only do this before a fresh "
            "build that you will distribute to all customers.")
        warn.setWordWrap(True)
        layout.addWidget(warn)

        self._ack = QCheckBox("I understand this invalidates all issued licenses.")
        self._ack.toggled.connect(lambda checked: self._regen_btn.setEnabled(checked))
        layout.addWidget(self._ack)

        self._regen_btn = QPushButton("Regenerate Keypair")
        self._regen_btn.setEnabled(False)
        self._regen_btn.clicked.connect(self._on_regenerate)
        layout.addWidget(self._regen_btn)

        layout.addStretch()
        self.refresh()

    def refresh(self) -> None:
        lines = []
        if core.keys_exist():
            lines.append("Signing keys: <span style='color:#34d399;'>present</span> "
                         f"in {core.KEYS_DIR}/")
        else:
            lines.append("Signing keys: <span style='color:#f87171;'>missing</span> — "
                         "run setup_security.py or regenerate below.")

        embedded = core.embedded_public_key_pem()
        try:
            with open(core.PUBLIC_KEY_FILE, "rb") as f:
                disk_pub = f.read()
        except OSError:
            disk_pub = None

        if embedded is not None:
            lines.append(f"App-embedded public key fingerprint: "
                         f"<code>{core.public_key_fingerprint(embedded)}</code>")
        if disk_pub is not None:
            lines.append(f"admin_keys public key fingerprint: "
                         f"<code>{core.public_key_fingerprint(disk_pub)}</code>")

        if embedded is not None and disk_pub is not None:
            match = core.public_key_fingerprint(embedded) == core.public_key_fingerprint(disk_pub)
            if match:
                lines.append("<span style='color:#34d399;'>✓ The app trusts keys "
                             "signed by this admin private key.</span>")
            else:
                lines.append("<span style='color:#f87171;'>✗ Mismatch — the app will "
                             "REJECT licenses signed by the current admin key. Rebuild "
                             "the app after embedding, or regenerate.</span>")
        self._info.setText("<br>".join(lines))

    def _on_regenerate(self) -> None:
        confirm = QMessageBox.question(
            self, "Regenerate keypair?",
            "This will overwrite the admin keypair and rewrite license_guard.py.\n\n"
            "Every license already issued will stop working. Continue?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if confirm != QMessageBox.Yes:
            return
        typed, ok = QInputDialog.getText(
            self, "Type to confirm", "Type REGENERATE to proceed:")
        if not ok or typed.strip() != "REGENERATE":
            QMessageBox.information(self, "Cancelled", "Keypair was not changed.")
            return
        try:
            core.generate_keypair_and_embed()
        except (FileNotFoundError, ValueError) as exc:
            QMessageBox.critical(self, "Regeneration failed", str(exc))
            return
        self._window.invalidate_private_key()
        self._ack.setChecked(False)
        self.refresh()
        QMessageBox.information(
            self, "Keypair regenerated",
            "A new keypair was generated and embedded into license_guard.py.\n\n"
            "Rebuild and redistribute the app, then re-issue licenses.")


class LicenseManagerWindow(QMainWindow):
    """Top-level window hosting the three tabs."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Faster-Whisper License Manager")
        self.setMinimumSize(720, 520)
        self._private_key = None  # cached after the first successful load

        tabs = QTabWidget()
        self._generate_tab = GenerateTab(self)
        self._manage_tab = ManageTab(self)
        self._keys_tab = KeysTab(self)
        tabs.addTab(self._generate_tab, "Generate")
        tabs.addTab(self._manage_tab, "Manage")
        tabs.addTab(self._keys_tab, "Keys")
        tabs.currentChanged.connect(self._on_tab_changed)
        self.setCentralWidget(tabs)

        try:
            apply_dark_title_bar(int(self.winId()))
        except Exception:  # pylint: disable=broad-except
            pass

    def _on_tab_changed(self, _index: int) -> None:
        # Keep the live tabs current without a manual refresh.
        self._manage_tab.refresh()
        self._keys_tab.refresh()

    def refresh_manage(self) -> None:
        self._manage_tab.refresh()

    def require_private_key(self):
        """Return the admin private key, or None after warning if it's missing."""
        if self._private_key is not None:
            return self._private_key
        try:
            self._private_key = core.load_private_key()
        except FileNotFoundError as exc:
            QMessageBox.critical(
                self, "Private key missing",
                f"{exc}\n\nGenerate a keypair in the Keys tab or run setup_security.py.")
            return None
        return self._private_key

    def invalidate_private_key(self) -> None:
        """Drop the cached key after a regeneration so the next sign reloads it."""
        self._private_key = None
