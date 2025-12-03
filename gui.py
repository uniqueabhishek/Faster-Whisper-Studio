"""PyQt5 GUI for Faster-Whisper transcription app."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import List, Optional

from PyQt5.QtCore import Qt, pyqtSignal, QObject, QUrl, QSettings
from PyQt5.QtGui import QCursor, QDragEnterEvent, QDropEvent, QDesktopServices
from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QProgressBar,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QMessageBox,
    QListWidget,
    QStatusBar,
    QSplitter,
    QGroupBox,
    QFrame,
    QAbstractItemView
)

from transcriber import (
    TranscriptionConfig,
    Transcriber,
    TranscriptionResult,
)
from workers import BatchWorker
from styles import DARK_THEME_QSS, apply_dark_title_bar

LOGGER = logging.getLogger(__name__)

MEDIA_FILTER = (
    "Media Files (*.mp3 *.wav *.m4a *.flac *.ogg *.mp4 *.mkv *.webm);;"
    "All Files (*)"
)
DEFAULT_WIDTH = 1200
DEFAULT_HEIGHT = 800

LANGUAGE_MAP = {
    "Auto Detect": "Auto",
    "English": "en",
    "Hindi": "hi",
    "Japanese": "ja",
    "Chinese": "zh",
    "German": "de",
    "Spanish": "es",
    "French": "fr",
    "Korean": "ko",
    "Portuguese": "pt",
    "Russian": "ru",
}


class LogSignal(QObject):
    """Signal emitter for logging."""
    log_signal = pyqtSignal(str)


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
        self.text_widget.verticalScrollBar().setValue(
            self.text_widget.verticalScrollBar().maximum()
        )


class DragDropWidget(QFrame):
    """A styled frame that accepts file drops."""

    filesDropped = pyqtSignal(list)

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
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setStyleSheet("color: #9ca3af; font-weight: bold;")
        layout.addWidget(self.label)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
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
        urls = event.mimeData().urls()
        if urls:
            paths = [u.toLocalFile() for u in urls]
            self.filesDropped.emit(paths)


class MainWindow(QMainWindow):
    """Main Faster-Whisper GUI window."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Faster-Whisper GUI (Unified)")

        # Apply Dark Theme
        app = QApplication.instance()
        if app:
            app.setStyleSheet(DARK_THEME_QSS)

        # Apply Windows Dark Title Bar
        apply_dark_title_bar(int(self.winId()))

        self._transcriber: Optional[Transcriber] = None
        self._worker: Optional[BatchWorker] = None

        # UI Components
        self.model_edit: QLineEdit
        self.model_btn: QPushButton
        self.file_list: QListWidget
        self.start_btn: QPushButton
        self.cancel_btn: QPushButton
        self.progress_bar: QProgressBar
        self.log_output: QTextEdit
        self.file_status_list: QListWidget
        self.lang_combo: QComboBox
        self.prompt_edit: QLineEdit

        self._build_ui()
        self._create_status_bar()
        self._setup_logging()

        # Settings
        self.settings = QSettings("FasterWhisperGUI", "App")
        self._load_settings()

        self.resize(DEFAULT_WIDTH, DEFAULT_HEIGHT)

    def _setup_logging(self) -> None:
        """Redirect logging to the GUI text area."""
        handler = QtLogHandler(self.log_output)
        logging.getLogger().addHandler(handler)
        logging.getLogger().setLevel(logging.INFO)

    def show_error(self, message: str) -> None:
        QMessageBox.critical(self, "Error", message)

    def _build_ui(self) -> None:
        central = QWidget(self)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Splitter for Left (Controls) and Right (Logs)
        splitter = QSplitter(Qt.Horizontal)

        # --- Left Pane: Controls ---
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(20, 20, 20, 20)
        left_layout.setSpacing(15)

        # Header
        header = QLabel("Faster Whisper GUI")
        header.setObjectName("Header")
        left_layout.addWidget(header)

        # 1. Model Selection
        model_group = QGroupBox("1. Model Selection")
        model_layout = QVBoxLayout(model_group)

        row_model = QHBoxLayout()
        self.model_edit = QLineEdit()
        self.model_edit.setPlaceholderText("Path to Faster-Whisper model folder...")
        self.model_edit.setReadOnly(True)
        row_model.addWidget(self.model_edit)

        self.model_btn = QPushButton("Select Model")
        self.model_btn.setObjectName("SecondaryBtn")
        self.model_btn.clicked.connect(self.on_select_model_clicked)
        row_model.addWidget(self.model_btn)

        model_layout.addLayout(row_model)

        # Fast Mode Checkbox
        self.fast_mode_check = QCheckBox("Fast Mode (2x Speed, slightly less accurate)")
        self.fast_mode_check.setToolTip("Sets beam_size=1 for faster transcription.")
        model_layout.addWidget(self.fast_mode_check)

        # VAD Checkbox
        self.vad_check = QCheckBox("Enable VAD (Skip Silence)")
        self.vad_check.setToolTip("Uses offline VAD to skip silent parts.\nTurn this OFF if your audio has very low volume speech.")

        # Check if onnxruntime is working
        try:
            import onnxruntime
            self.vad_check.setChecked(True)
            model_layout.addWidget(self.vad_check)
        except Exception as e:
            LOGGER.exception("Failed to import onnxruntime")
            self.vad_check.setChecked(False)
            self.vad_check.setEnabled(False)
            self.vad_check.setText("Enable VAD (Error loading library)")
            self.vad_check.setToolTip(f"VAD requires 'onnxruntime' which failed to load.\nError: {str(e)}\n\nPlease ensure Visual C++ Redistributable is installed.")
            model_layout.addWidget(self.vad_check)

            # Add Fix Button
            self.fix_vad_btn = QPushButton("Fix VAD (Install VC++)")
            self.fix_vad_btn.setToolTip("Click to install the required Visual C++ Redistributable.")

            def _install_vc():
                vc_path = Path(__file__).parent / "assets" / "vc_redist.x64.exe"
                if vc_path.exists():
                    QDesktopServices.openUrl(QUrl.fromLocalFile(str(vc_path)))
                else:
                    QDesktopServices.openUrl(QUrl("https://aka.ms/vs/17/release/vc_redist.x64.exe"))

            self.fix_vad_btn.clicked.connect(_install_vc)
            model_layout.addWidget(self.fix_vad_btn)

            self.fix_vad_btn.clicked.connect(_install_vc)
            model_layout.addWidget(self.fix_vad_btn)

        # Language Selection
        lang_layout = QHBoxLayout()
        lang_label = QLabel("Language:")
        self.lang_combo = QComboBox()
        self.lang_combo.addItems(list(LANGUAGE_MAP.keys()))
        self.lang_combo.setToolTip("Select audio language (Auto = detect automatically)")
        lang_layout.addWidget(lang_label)
        lang_layout.addWidget(self.lang_combo)
        model_layout.addLayout(lang_layout)

        # Initial Prompt
        prompt_layout = QHBoxLayout()
        prompt_label = QLabel("Initial Prompt:")
        self.prompt_edit = QLineEdit()
        self.prompt_edit.setPlaceholderText("Optional: Context or style hint (e.g. 'Hindi conversation')")
        self.prompt_edit.setToolTip("Provide context to guide the model (improves accuracy).")
        prompt_layout.addWidget(prompt_label)
        prompt_layout.addWidget(self.prompt_edit)
        model_layout.addLayout(prompt_layout)

        left_layout.addWidget(model_group)

        # 2. Files Queue
        queue_group = QGroupBox("2. Files to Transcribe")
        queue_layout = QVBoxLayout(queue_group)

        # Drag & Drop Area
        self.drag_drop = DragDropWidget()
        self.drag_drop.filesDropped.connect(self.on_files_dropped)
        queue_layout.addWidget(self.drag_drop)

        # File List
        self.file_list = QListWidget()
        self.file_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        # self.file_list.setPlaceholderText("No files added...") # Not supported in PyQt5
        queue_layout.addWidget(self.file_list)

        # Buttons Row
        btn_row = QHBoxLayout()
        add_btn = QPushButton("Add Files")
        add_btn.setObjectName("SecondaryBtn")
        add_btn.clicked.connect(self.on_add_files_clicked)
        btn_row.addWidget(add_btn)

        clear_btn = QPushButton("Clear List")
        clear_btn.setObjectName("SecondaryBtn")
        clear_btn.clicked.connect(self.file_list.clear)
        btn_row.addWidget(clear_btn)

        queue_layout.addLayout(btn_row)
        left_layout.addWidget(queue_group)

        # Spacer
        left_layout.addStretch()

        # Action Buttons
        self.start_btn = QPushButton("Start Transcription")
        self.start_btn.setEnabled(False)
        self.start_btn.setMinimumHeight(50)
        self.start_btn.setStyleSheet("font-size: 16px;")
        self.start_btn.clicked.connect(self.on_start_clicked)
        left_layout.addWidget(self.start_btn)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.setStyleSheet("background-color: #ef4444;")
        self.cancel_btn.clicked.connect(self.on_cancel_clicked)
        left_layout.addWidget(self.cancel_btn)

        # Progress Bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("%p%")
        left_layout.addWidget(self.progress_bar)


        # --- Right Pane: Logs ---
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(20, 20, 20, 20)

        log_label = QLabel("Live Logs & Output")
        log_label.setStyleSheet("font-weight: bold; color: #9ca3af;")
        right_layout.addWidget(log_label)

        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        right_layout.addWidget(self.log_output)

        status_label = QLabel("File Status")
        status_label.setStyleSheet("font-weight: bold; color: #9ca3af; margin-top: 10px;")
        right_layout.addWidget(status_label)

        self.file_status_list = QListWidget()
        self.file_status_list.setMaximumHeight(200)
        right_layout.addWidget(self.file_status_list)

        # Add widgets to splitter
        splitter.addWidget(left_widget)
        splitter.addWidget(right_widget)
        splitter.setSizes([500, 700])
        splitter.setCollapsible(0, False)
        splitter.setCollapsible(1, False)

        main_layout.addWidget(splitter)
        self.setCentralWidget(central)

    def _create_status_bar(self) -> None:
        bar = self.statusBar()
        if bar:
            bar.showMessage("Ready")

    def _load_settings(self) -> None:
        """Load last used paths from settings."""
        last_model = self.settings.value("model_path", "")
        if last_model and Path(last_model).exists():
            self.model_edit.setText(last_model)
            self.start_btn.setEnabled(True)
            LOGGER.info("Restored model path: %s", last_model)

        # Load Language
        last_lang = self.settings.value("language", "Auto Detect")
        idx = self.lang_combo.findText(last_lang)
        if idx >= 0:
            self.lang_combo.setCurrentIndex(idx)

        # Load Prompt
        last_prompt = self.settings.value("initial_prompt", "")
        self.prompt_edit.setText(last_prompt)

    # ---------------------------------------------------------
    # EVENTS
    # ---------------------------------------------------------

    def on_files_dropped(self, paths: List[str]) -> None:
        for p in paths:
            self.file_list.addItem(p)

    def on_add_files_clicked(self) -> None:
        last_dir = self.settings.value("last_input_dir", "")
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Select media files", last_dir, MEDIA_FILTER
        )
        if paths:
            self.file_list.addItems(paths)
            # Save the directory of the first file
            if paths:
                first_file = Path(paths[0])
                self.settings.setValue("last_input_dir", str(first_file.parent))

    def on_select_model_clicked(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Whisper model (*.bin)",
            self.settings.value("last_model_dir", ""),
            "Whisper Model (*.bin);;All Files (*)",
        )
        if not path:
            return

        p = Path(path).resolve()
        folder = p if p.is_dir() else p.parent

        if (folder / "model").is_dir():
            folder = folder / "model"

        model_dir = folder

        if not (model_dir / "config.json").exists():
            self.show_error(
                "Wrong model selected.\nFolder must contain:\n"
                "config.json and either model.bin or model.int8.bin"
            )
            return

        self.model_edit.setText(str(model_dir))
        self.start_btn.setEnabled(True)

        # Save settings
        self.settings.setValue("model_path", str(model_dir))
        self.settings.setValue("last_model_dir", str(model_dir.parent))

        LOGGER.info("Model directory selected: %s", model_dir)

    def _lazy_load_model(self) -> bool:
        if self._transcriber is not None:
            return True

        self.statusBar().showMessage("Loading model...")
        try:
            config = TranscriptionConfig(
                model_name=self.model_edit.text().strip(),
                language=None,
            )
            self._transcriber = Transcriber(config)
        except Exception as exc:
            error_msg = str(exc)
            LOGGER.exception("Model loading failed")
            self.show_error(f"Failed to load model:\n{error_msg}")
            self.statusBar().showMessage("Model load failed.")
            return False

        self.start_btn.setEnabled(True)
        self.statusBar().showMessage("Model loaded.")
        return True

    def on_start_clicked(self) -> None:
        if self.file_list.count() == 0:
            self.show_error("No files to transcribe.")
            return

        if not self._lazy_load_model():
            return

        if self._transcriber is None:
            return

        # Collect files
        input_files = []
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            path = Path(item.text())
            if path.is_file():
                input_files.append(path)

        if not input_files:
            self.show_error("No valid files found in list.")
            return

        self.file_status_list.clear()
        self.progress_bar.setValue(0)
        self.statusBar().showMessage("Starting transcription...")
        self._set_busy(True)

        # Use BatchWorker for everything now
        beam_size = 1 if self.fast_mode_check.isChecked() else 5
        vad_filter = self.vad_check.isChecked()

        # Get Language and Prompt
        lang_name = self.lang_combo.currentText()
        lang_code = LANGUAGE_MAP.get(lang_name, "Auto")
        language = None if lang_code == "Auto" else lang_code

        initial_prompt = self.prompt_edit.text().strip() or None

        # Save settings
        self.settings.setValue("language", lang_name)
        self.settings.setValue("initial_prompt", self.prompt_edit.text())

        worker = BatchWorker(
            self._transcriber,
            input_files=input_files,
            output_dir=None, # Default to same folder
            beam_size=beam_size,
            vad_filter=vad_filter,
            language=language,
            initial_prompt=initial_prompt,
        )
        self._worker = worker

        worker.progress.connect(self.on_progress)
        worker.speed.connect(self.on_speed_update)
        worker.file_status.connect(self.on_file_status_update)
        worker.finished.connect(self.on_finished)
        worker.failed.connect(self.on_failed)
        worker.start()

    def on_file_status_update(self, filename: str, status: str) -> None:
        self.file_status_list.addItem(f"{filename} → {status}")
        self.file_status_list.scrollToBottom()

    def on_progress(self, percent: int) -> None:
        self.progress_bar.setValue(percent)

    def on_speed_update(self, avg_time: float, eta_seconds: int) -> None:
        minutes, seconds = divmod(eta_seconds, 60)
        eta_txt = (
            f"{minutes}m {seconds}s" if minutes else f"{seconds}s"
        )
        self.progress_bar.setFormat(
            f"%p%   •   {avg_time:.2f}s/file   •   ETA {eta_txt}"
        )

    def on_finished(self, results: List[TranscriptionResult]) -> None:
        self.statusBar().showMessage(f"Completed. Files: {len(results)}")
        self._worker = None
        self._set_busy(False)
        self.progress_bar.setValue(100)
        QMessageBox.information(self, "Done", f"Successfully processed {len(results)} files.")

    def on_failed(self, message: str) -> None:
        self.show_error(message)
        self.statusBar().showMessage("Failed.")
        self._worker = None
        self._set_busy(False)

    def on_cancel_clicked(self) -> None:
        if self._worker:
            self._worker.request_cancel()
        self.statusBar().showMessage("Cancelling...")

    def _set_busy(self, busy: bool) -> None:
        if busy:
            self.setCursor(QCursor(Qt.WaitCursor))
        else:
            self.unsetCursor()

        self.model_btn.setEnabled(not busy)
        self.start_btn.setEnabled(not busy)
        self.cancel_btn.setEnabled(busy)

        # Disable list modification while running
        self.file_list.setEnabled(not busy)
        self.drag_drop.setVisible(not busy)
