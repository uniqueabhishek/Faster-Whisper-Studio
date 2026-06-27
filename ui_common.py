"""Shared PySide6 UI widgets and helpers used across the GUI views.

Extracted from gui.py and preprocessing_gui.py, which each previously carried
byte-identical copies of these widgets (DragDropWidget, QtLogHandler, LogSignal),
the MEDIA_FILTER constant, and a window-centering helper. Keeping one copy here
prevents the silent drift the duplicates had already started to accumulate.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QObject, QSize
from PySide6.QtGui import QCursor, QDragEnterEvent, QDropEvent, QGuiApplication, QIcon
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

MEDIA_FILTER = (
    "Media Files (*.mp3 *.wav *.m4a *.flac *.ogg *.mp4 *.mkv *.webm);;"
    "All Files (*)"
)

# Icon sizes shipped under Resource/Icon as faster-whisper-icon-<n>.png.
_ICON_PNG_SIZES = (16, 32, 48, 64, 128, 256, 512)


def resource_path(*parts: str) -> Path:
    """Resolve a bundled resource path for both source runs and PyInstaller builds.

    When frozen, PyInstaller extracts ``--add-data`` payloads under ``sys._MEIPASS``;
    otherwise resources sit next to the source files. Mirrors the pattern in
    transcriber.py for the VAD model.
    """
    if getattr(sys, "frozen", False):
        base = Path(sys._MEIPASS)  # type: ignore[attr-defined]  # pylint: disable=protected-access
    else:
        base = Path(__file__).parent
    return base.joinpath(*parts)


def make_settings_button(tooltip: str = "") -> QPushButton:
    """Create a circular ⚙ settings button with a crisp, centered gear icon.

    Uses a real SVG icon rather than the ⚙ text glyph: font glyphs for the gear
    character render off-center on most platforms, whereas an icon is centered by
    Qt regardless of font metrics. Styled by the ``#SettingsBtn`` rule in the theme.
    """
    btn = QPushButton()
    btn.setObjectName("SettingsBtn")
    btn.setFixedSize(30, 30)
    btn.setIcon(QIcon(str(resource_path("assets", "gear.svg"))))
    btn.setIconSize(QSize(16, 16))
    btn.setCursor(QCursor(Qt.PointingHandCursor))  # type: ignore[attr-defined]
    if tooltip:
        btn.setToolTip(tooltip)
    return btn


def app_icon() -> QIcon:
    """Build the application icon from the shipped multi-resolution assets.

    Loads the Windows ``.ico`` plus each PNG size so Qt can pick the crispest
    image for the title bar, taskbar, and Alt-Tab at any DPI.
    """
    icon = QIcon()
    icon_dir = resource_path("Resource", "Icon")

    ico = icon_dir / "faster-whisper-icon.ico"
    if ico.exists():
        icon.addFile(str(ico))

    for size in _ICON_PNG_SIZES:
        png = icon_dir / f"faster-whisper-icon-{size}.png"
        if png.exists():
            icon.addFile(str(png))

    return icon


class LogSignal(QObject):
    """Signal emitter for logging."""
    log_signal = Signal(str)


class QtLogHandler(logging.Handler):
    """Custom logging handler that emits signals to a QTextEdit."""

    def __init__(self, text_widget: QTextEdit):
        super().__init__()
        self.text_widget = text_widget
        self.emitter = LogSignal()
        self.emitter.log_signal.connect(self._append_text)
        self.setFormatter(logging.Formatter("[%(asctime)s] %(message)s", "%H:%M:%S"))

    def emit(self, record):
        msg = self.format(record)
        self.emitter.log_signal.emit(msg)

    def _append_text(self, msg: str):
        self.text_widget.append(msg)
        self.text_widget.verticalScrollBar().setValue(  # type: ignore[union-attr]
            self.text_widget.verticalScrollBar().maximum()  # type: ignore[union-attr]
        )


class DragDropWidget(QFrame):
    """A styled frame that accepts file drops."""

    filesDropped = Signal(list)

    def __init__(self, title: str = "Drag & Drop Files Here"):
        super().__init__()
        self.setAcceptDrops(True)
        self.setFrameStyle(QFrame.StyledPanel | QFrame.Sunken)
        self.setStyleSheet("""
            QFrame {
                border: 2px dashed #4b5563;
                border-radius: 8px;
                background-color: #262626;
            }
            QFrame:hover {
                border-color: #3b82f6;
                background-color: #2d2d2d;
            }
        """)

        layout = QVBoxLayout(self)
        self.label = QLabel(title)
        self.label.setAlignment(Qt.AlignCenter)  # type: ignore[attr-defined]
        self.label.setStyleSheet("color: #9ca3af; font-weight: bold;")
        layout.addWidget(self.label)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():  # type: ignore[union-attr]
            event.accept()
            self.setStyleSheet("""
                QFrame {
                    border: 2px dashed #3b82f6;
                    background-color: #333333;
                }
            """)
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self.setStyleSheet("""
            QFrame {
                border: 2px dashed #4b5563;
                border-radius: 8px;
                background-color: #262626;
            }
        """)

    def dropEvent(self, event: QDropEvent):
        self.setStyleSheet("""
            QFrame {
                border: 2px dashed #4b5563;
                border-radius: 8px;
                background-color: #262626;
            }
        """)
        urls = event.mimeData().urls()  # type: ignore[union-attr]
        if urls:
            paths = [u.toLocalFile() for u in urls]
            self.filesDropped.emit(paths)


def settings_bool(settings, key: str, default: bool) -> bool:
    """Read a bool from QSettings.

    PySide6's QSettings.value() has no ``type=`` kwarg (unlike PyQt5) and may
    return the string ``'true'``/``'false'`` depending on the backend, so coerce
    explicitly.
    """
    value = settings.value(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes", "on")
    return bool(value)


def settings_int(settings, key: str, default: int) -> int:
    """Read an int from QSettings (PySide6 has no value(type=...))."""
    value = settings.value(key, default)
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def center_window(window: QWidget) -> None:
    """Center a top-level window on the screen under the cursor."""
    frame_gm = window.frameGeometry()
    # Qt6 removed QApplication.desktop(); pick the screen under the cursor.
    screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
    if screen is not None:
        frame_gm.moveCenter(screen.availableGeometry().center())
        window.move(frame_gm.topLeft())
