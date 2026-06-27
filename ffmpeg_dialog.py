"""Dialog (Tools -> Update FFmpeg): shows the active FFmpeg and lets the user update it."""

from __future__ import annotations

import logging
from typing import Optional

from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from ffmpeg_utils import (
    get_ffmpeg_path,
    get_ffmpeg_version,
    get_ffmpeg_updated_time,
    ffmpeg_source,
    user_ffmpeg_dir,
)

LOGGER = logging.getLogger(__name__)

_SOURCE_LABELS = {
    "updated": "user-updated",
    "bundled": "bundled with app",
    "path": "system PATH",
}


class FfmpegUpdateWorker(QThread):
    """Downloads a fresh ffmpeg into the per-user override dir off the GUI thread."""

    succeeded = pyqtSignal(str)   # new version line
    failed = pyqtSignal(str)
    status = pyqtSignal(str)

    def run(self) -> None:
        try:
            # Imported lazily so a missing/edited build helper can't break startup.
            from download_ffmpeg import fetch_ffmpeg  # pylint: disable=import-outside-toplevel
            ok = fetch_ffmpeg(user_ffmpeg_dir(), status=self.status.emit)
            if not ok:
                self.failed.emit("Update failed. See the log for details.")
                return
            self.succeeded.emit(get_ffmpeg_version() or "updated")
        except Exception as exc:  # pylint: disable=broad-except
            LOGGER.exception("FFmpeg update failed")
            self.failed.emit(str(exc))


class FfmpegDialog(QDialog):
    """Shows the active FFmpeg version/source and downloads an update on demand."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Update FFmpeg")
        self.setMinimumWidth(480)
        self._worker: Optional[FfmpegUpdateWorker] = None

        layout = QVBoxLayout(self)

        self._version_label = QLabel()
        self._version_label.setWordWrap(True)
        self._version_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self._version_label)

        self._status_label = QLabel("")
        self._status_label.setWordWrap(True)
        layout.addWidget(self._status_label)

        btn_row = QHBoxLayout()
        self._update_btn = QPushButton("Update FFmpeg")
        self._update_btn.clicked.connect(self._on_update)
        btn_row.addWidget(self._update_btn)
        btn_row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        self._refresh_version()

    def _refresh_version(self) -> None:
        if not get_ffmpeg_path():
            self._version_label.setText(
                "FFmpeg: <span style='color:#f87171;'>not found</span>. "
                "Click <b>Update FFmpeg</b> to download it.")
            return
        source = _SOURCE_LABELS.get(ffmpeg_source(), "")
        version = get_ffmpeg_version() or "(version unknown)"
        updated = get_ffmpeg_updated_time()
        updated_line = f"<br><i>Last updated: {updated}</i>" if updated else ""
        self._version_label.setText(
            f"{version}<br><i>Source: {source}</i>{updated_line}")

    def _on_update(self) -> None:
        if self._worker is not None:
            return
        self._update_btn.setEnabled(False)
        self._status_label.setText("Downloading the latest FFmpeg…")

        worker = FfmpegUpdateWorker()
        self._worker = worker
        worker.status.connect(self._status_label.setText)
        worker.succeeded.connect(self._on_done)
        worker.failed.connect(self._on_failed)
        worker.start()

    def _on_done(self, _version: str) -> None:
        self._worker = None
        self._update_btn.setEnabled(True)
        self._status_label.setText("FFmpeg updated successfully.")
        self._refresh_version()

    def _on_failed(self, message: str) -> None:
        self._worker = None
        self._update_btn.setEnabled(True)
        self._status_label.setText(f"Update failed: {message}")
