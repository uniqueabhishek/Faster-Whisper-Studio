"""Offscreen smoke test: the GUI must at least construct.

Runs headless via the Qt 'offscreen' platform (works in CI). Building the real
MainWindow exercises both views, the menu bar, center_window, the QSettings
reads (settings_bool/settings_int), the drag-drop widgets, and every Signal
definition — so import/enum/signal/QSettings regressions are caught without a
display or user interaction. This is the automated half of the PySide6-migration
verification (interactive paths still need a manual smoke-test).
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

# One QApplication per process — required before constructing any QWidget.
_app = QApplication.instance() or QApplication([])


def test_main_window_constructs():
    from main_window import MainWindow
    window = MainWindow()
    assert window is not None


def test_ffmpeg_dialog_constructs():
    from ffmpeg_dialog import FfmpegDialog
    dialog = FfmpegDialog()
    assert dialog is not None
