"""Resume session dialog for Faster-Whisper GUI."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QGroupBox,
)

from session_manager import SessionState


class ResumeSessionDialog(QDialog):
    """Dialog to prompt user to resume incomplete session."""

    def __init__(self, session: SessionState, parent=None):
        super().__init__(parent)
        self.session = session
        self.resume_requested = False

        self.setWindowTitle("Resume Previous Session")
        self.setModal(True)
        self.setMinimumWidth(600)
        self.setMinimumHeight(400)

        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # Header
        header = QLabel("Previous transcription session found!")
        header.setStyleSheet("font-size: 16px; font-weight: bold; color: #3b82f6;")
        layout.addWidget(header)

        # Session Info
        info_group = QGroupBox("Session Information")
        info_layout = QVBoxLayout(info_group)

        # Format session details
        total_files = len(self.session.files)
        completed = len(self.session.completed_files)
        failed = len(self.session.failed_files)
        pending = len(self.session.pending_files)

        info_text = f"""
<b>Session ID:</b> {self.session.session_id}<br>
<b>Created:</b> {self.session.created_at}<br>
<b>Model:</b> {Path(self.session.model_path).name}<br>
<b>Total Files:</b> {total_files}<br>
<b>Completed:</b> {completed}<br>
<b>Failed:</b> {failed}<br>
<b>Pending:</b> {pending}<br>
<b>Progress:</b> {self.session.progress_percent}%
        """

        info_label = QLabel(info_text)
        info_label.setTextFormat(Qt.RichText)  # type: ignore[attr-defined]
        info_layout.addWidget(info_label)

        layout.addWidget(info_group)

        # File List
        files_group = QGroupBox("Pending Files")
        files_layout = QVBoxLayout(files_group)

        self.file_list = QTextEdit()
        self.file_list.setReadOnly(True)
        self.file_list.setMaximumHeight(150)

        # Show pending and failed files
        file_text_lines = []

        if self.session.pending_files:
            file_text_lines.append("<b>Pending Files:</b>")
            for f in self.session.pending_files[:10]:  # Show first 10
                file_text_lines.append(f"  • {Path(f.path).name}")
            if len(self.session.pending_files) > 10:
                remaining = len(self.session.pending_files) - 10
                file_text_lines.append(f"  ... and {remaining} more")

        if self.session.failed_files:
            file_text_lines.append("")
            file_text_lines.append("<b>Failed Files (will retry):</b>")
            for f in self.session.failed_files[:5]:  # Show first 5
                error = f.error if f.error else "Unknown error"
                file_text_lines.append(f"  • {Path(f.path).name} - {error}")
            if len(self.session.failed_files) > 5:
                remaining = len(self.session.failed_files) - 5
                file_text_lines.append(f"  ... and {remaining} more")

        self.file_list.setHtml("<br>".join(file_text_lines))
        files_layout.addWidget(self.file_list)

        layout.addWidget(files_group)

        # Warning message
        warning = QLabel(
            "⚠️ Resuming will continue processing only the pending and failed files."
        )
        warning.setStyleSheet("color: #f59e0b; font-style: italic;")
        warning.setWordWrap(True)
        layout.addWidget(warning)

        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        discard_btn = QPushButton("Discard & Start Fresh")
        discard_btn.setObjectName("SecondaryBtn")
        discard_btn.clicked.connect(self.on_discard)
        button_layout.addWidget(discard_btn)

        resume_btn = QPushButton("Resume Session")
        resume_btn.setStyleSheet("""
            QPushButton {
                background-color: #3b82f6;
                color: white;
                font-weight: bold;
                padding: 8px 16px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #2563eb;
            }
        """)
        resume_btn.clicked.connect(self.on_resume)
        button_layout.addWidget(resume_btn)

        layout.addLayout(button_layout)

    def on_resume(self):
        """User chose to resume the session."""
        self.resume_requested = True
        self.accept()

    def on_discard(self):
        """User chose to discard the session."""
        self.resume_requested = False
        self.accept()

    @staticmethod
    def show_resume_dialog(session: SessionState, parent=None) -> Optional[SessionState]:
        """Show dialog and return session if user wants to resume, None otherwise.

        Args:
            session: The session to potentially resume.
            parent: Parent widget.

        Returns:
            The session if user chose to resume, None if they chose to discard.
        """
        dialog = ResumeSessionDialog(session, parent)
        dialog.exec()

        if dialog.resume_requested:
            return session
        else:
            # User discarded - delete the session file
            from session_manager import SessionManager
            manager = SessionManager()
            manager.delete_session(session.session_id)
            return None
