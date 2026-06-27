"""Main window with sidebar navigation for Faster-Whisper GUI."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QPushButton,
    QStackedWidget,
    QButtonGroup,
    QMessageBox,
)

from preprocessing_gui import PreprocessingView, PreprocessingWindow
from gui import TranscriptionView
from styles import DARK_THEME_QSS, apply_dark_title_bar
from ui_common import center_window, settings_int
from ffmpeg_dialog import FfmpegDialog

LOGGER = logging.getLogger(__name__)

DEFAULT_WIDTH = 1396  # 1300 + 96 (1 inch at 96 DPI)
DEFAULT_HEIGHT = 800

SIDEBAR_STYLE = """
    QWidget#sidebar {
        background-color: #1e1e1e;
        border-right: 1px solid #3e3e3e;
    }

    QPushButton#nav_button {
        text-align: left;
        padding: 12px 15px;
        border: none;
        background-color: transparent;
        color: #cccccc;
        font-size: 14px;
        font-weight: bold;
    }

    QPushButton#nav_button:hover {
        background-color: #2d2d2d;
    }

    QPushButton#nav_button:checked {
        background-color: #0e639c;
        color: #ffffff;
        border-left: 3px solid #1e88e5;
    }
"""

_MENU_STYLE = """
    QMenuBar { background-color: #1e1e1e; color: #cccccc; }
    QMenuBar::item { padding: 4px 10px; background: transparent; }
    QMenuBar::item:selected { background-color: #0e639c; color: #ffffff; }
    QMenu { background-color: #252526; color: #cccccc; border: 1px solid #3e3e3e; }
    QMenu::item { padding: 5px 24px; }
    QMenu::item:selected { background-color: #0e639c; color: #ffffff; }
"""


class MainWindow(QMainWindow):
    """Main window with sidebar navigation."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Faster-Whisper AI Transcriber")

        # Apply Dark Theme
        app = QApplication.instance()
        if app:
            app.setStyleSheet(DARK_THEME_QSS + SIDEBAR_STYLE)  # type: ignore[attr-defined]

        # Apply Windows Dark Title Bar
        apply_dark_title_bar(int(self.winId()))

        # Settings
        self.settings = QSettings("FasterWhisperGUI", "MainWindow")

        # Create views (initialized in _build_ui)
        self.preprocessing_view: PreprocessingView
        self.transcription_view: TranscriptionView
        self.stacked_widget: QStackedWidget

        # Track separate preprocessing windows
        self._separate_preprocessing_windows: List[PreprocessingWindow] = []

        self._build_ui()
        self._build_menu()

        # Restore last view
        last_view = settings_int(self.settings, "last_view", 0)
        self.stacked_widget.setCurrentIndex(last_view)
        self._update_nav_buttons(last_view)

        self.resize(DEFAULT_WIDTH, DEFAULT_HEIGHT)
        self._center_window()

    def _center_window(self) -> None:
        """Centers the window on the screen."""
        center_window(self)

    def _build_menu(self) -> None:
        """Add a top menu bar (Tools)."""
        menubar = self.menuBar()
        menubar.setStyleSheet(_MENU_STYLE)
        tools_menu = menubar.addMenu("&Tools")

        update_action = tools_menu.addAction("Update FFmpeg…")
        update_action.triggered.connect(self._open_ffmpeg)

        tools_menu.addSeparator()

        app_update_action = tools_menu.addAction("Check for App Updates…")
        app_update_action.triggered.connect(self._check_app_updates)

    def _open_ffmpeg(self) -> None:
        """Open the FFmpeg dialog (shows version/source + update)."""
        FfmpegDialog(self).exec()

    def _check_app_updates(self) -> None:
        """Placeholder for app self-update (to be wired up later)."""
        QMessageBox.information(
            self, "Check for App Updates",
            "Update checking is not available yet.\n\n"
            "This will be enabled in a future release.")

    def _build_ui(self) -> None:
        """Build the main UI with sidebar and stacked widget."""
        central = QWidget(self)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Sidebar
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(130)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(0)

        # Navigation buttons
        self.preprocessing_btn = QPushButton("Preprocessing")
        self.preprocessing_btn.setObjectName("nav_button")
        self.preprocessing_btn.setCheckable(True)
        self.preprocessing_btn.setChecked(True)
        self.preprocessing_btn.clicked.connect(self._switch_to_preprocessing)

        self.transcription_btn = QPushButton("Transcription")
        self.transcription_btn.setObjectName("nav_button")
        self.transcription_btn.setCheckable(True)
        self.transcription_btn.clicked.connect(self._switch_to_transcription)

        # Button group for exclusive selection
        self.nav_button_group = QButtonGroup(self)
        self.nav_button_group.addButton(self.preprocessing_btn, 0)
        self.nav_button_group.addButton(self.transcription_btn, 1)

        sidebar_layout.addWidget(self.preprocessing_btn)
        sidebar_layout.addWidget(self.transcription_btn)
        sidebar_layout.addStretch()

        # Stacked widget for views
        self.stacked_widget = QStackedWidget()

        # Page 0: Preprocessing View
        self.preprocessing_view = PreprocessingView(parent=self)
        self.preprocessing_view.transcription_requested.connect(self._on_transcription_requested)
        self.preprocessing_view.open_separate_window_requested.connect(self._open_separate_preprocessing_window)
        self.stacked_widget.addWidget(self.preprocessing_view)

        # Page 1: Transcription View
        self.transcription_view = TranscriptionView(parent=self)
        self.transcription_view.transcription_started.connect(self._on_transcription_started)
        self.transcription_view.transcription_finished.connect(self._on_transcription_finished)
        # Set status bar for transcription view
        self.transcription_view.set_status_bar(self.statusBar())
        self.stacked_widget.addWidget(self.transcription_view)

        # Add to main layout
        main_layout.addWidget(sidebar)
        main_layout.addWidget(self.stacked_widget)

        self.setCentralWidget(central)

    def _switch_to_preprocessing(self) -> None:
        """Switch to preprocessing view."""
        self.stacked_widget.setCurrentIndex(0)
        self._update_nav_buttons(0)
        self.settings.setValue("last_view", 0)

    def _switch_to_transcription(self) -> None:
        """Switch to transcription view."""
        self.stacked_widget.setCurrentIndex(1)
        self._update_nav_buttons(1)
        self.settings.setValue("last_view", 1)

    def _update_nav_buttons(self, index: int) -> None:
        """Update navigation button checked state."""
        self.preprocessing_btn.setChecked(index == 0)
        self.transcription_btn.setChecked(index == 1)

    def _on_transcription_requested(self, files: List[Path]) -> None:
        """Handle transition from preprocessing to transcription."""
        self._switch_to_transcription()
        if files:
            self.transcription_view.add_files_to_queue(files)

    def _open_separate_preprocessing_window(self) -> None:
        """Open independent preprocessing window."""
        window = PreprocessingWindow(parent=self)
        window.preprocessing_completed.connect(self._on_external_files_preprocessed)
        window.show()

        # Track window
        self._separate_preprocessing_windows.append(window)

    def _on_external_files_preprocessed(self, files: List[Path]) -> None:
        """Handle files from separate preprocessing window."""
        self._switch_to_transcription()
        self.transcription_view.add_files_to_queue(files)

    def _on_transcription_started(self) -> None:
        """Lock preprocessing view when transcription is active."""
        LOGGER.info("Transcription started - locking preprocessing view")
        self.preprocessing_view.set_read_only(True)

    def _on_transcription_finished(self) -> None:
        """Unlock preprocessing view when transcription completes."""
        LOGGER.info("Transcription finished - unlocking preprocessing view")
        self.preprocessing_view.set_read_only(False)
