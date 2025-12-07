"""PyQt5 GUI for Faster-Whisper transcription app."""
# pyright: reportOptionalMemberAccess=false, reportAttributeAccessIssue=false

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
    QAbstractItemView,
    QListWidgetItem
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
DEFAULT_WIDTH = 1300
DEFAULT_HEIGHT = 800
APP_VERSION = "v1.1.3"

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
        self.setWindowTitle("Faster-Whisper AI Transcriber [Speech to Text]")

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

        # Settings
        self.settings = QSettings("FasterWhisperGUI", "App")

        self._build_ui()
        self._create_status_bar()
        self._setup_logging()

        self._load_settings()

        self.resize(DEFAULT_WIDTH, DEFAULT_HEIGHT)
        self._center_window()

    def _center_window(self) -> None:
        """Centers the window on the screen."""
        frame_gm = self.frameGeometry()
        screen = QApplication.desktop().screenNumber(QApplication.desktop().cursor().pos())
        center_point = QApplication.desktop().screenGeometry(screen).center()
        frame_gm.moveCenter(center_point)
        self.move(frame_gm.topLeft())

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
        header = QLabel("Faster-Whisper AI GUI")
        header.setObjectName("Header")
        left_layout.addWidget(header)

        # 1. Model Selection
        model_group = QGroupBox("1. Model Selection")
        model_layout = QVBoxLayout(model_group)
        model_layout.setSpacing(15)  # Increase global spacing
        model_layout.setContentsMargins(15, 25, 15, 15) # Add internal padding

        row_model = QHBoxLayout()
        self.model_edit = QLineEdit()
        self.model_edit.setPlaceholderText("Path to Faster-Whisper model folder...")
        self.model_edit.setReadOnly(True)
        self.model_edit.setMinimumHeight(30) # Taller input
        row_model.addWidget(self.model_edit)

        self.model_btn = QPushButton("Select Model")
        self.model_btn.setToolTip("Select the folder containing your Faster-Whisper model.\n\n"
                                  "IMPORTANT: Must be a CTranslate2 converted model\n"
                                  "(folder must contain 'model.bin' and 'config.json').\n\n"
                                  "Standard OpenAI .pt files will NOT work.\n"
                                  "Compatible: tiny, base, small, medium, large-v1/v2/v3, distil-large-v2/v3.")
        self.model_btn.setObjectName("SecondaryBtn")
        self.model_btn.clicked.connect(self.on_select_model_clicked)
        self.model_btn.setMinimumHeight(30) # Taller button
        row_model.addWidget(self.model_btn)

        model_layout.addLayout(row_model)
        model_layout.addSpacing(5) # Extra space

        # Compute Type (Precision)
        compute_layout = QHBoxLayout()
        compute_label = QLabel("Word Analysis Depth:")
        self.compute_combo = QComboBox()
        self.compute_combo.addItems([
            "Fast Analysis (int8)",
            "Precise Analysis (float32)",
            "Deep Analysis (float32)"
        ])
        # Set tooltips for each item
        self.compute_combo.setItemData(0, "Checks 5 possibilities (low precision).", Qt.ToolTipRole)
        self.compute_combo.setItemData(1, "Checks 5 possibilities (full precision).", Qt.ToolTipRole)
        self.compute_combo.setItemData(2, "Checks 10 possibilities (full precision).", Qt.ToolTipRole)
        self.compute_combo.setMinimumHeight(30) # Taller combo

        # Set default to High Quality
        self.compute_combo.setCurrentIndex(1)

        compute_layout.addWidget(compute_label)
        compute_layout.addWidget(self.compute_combo)
        model_layout.addLayout(compute_layout)
        model_layout.addSpacing(5)

        # Checkboxes Layout (Horizontal)
        checks_layout = QHBoxLayout()

        # VAD Checkbox
        self.vad_check = QCheckBox("Smart Silence Removal")
        self.vad_check.setToolTip("Automatically detects and skips silent parts to speed up processing.\nTurn it off if your audio has very low volume speech.")

        # Check if onnxruntime is working
        try:
            import onnxruntime
            self.vad_check.setChecked(False)
        except Exception as e:
            LOGGER.exception("Failed to import onnxruntime")
            self.vad_check.setChecked(False)
            self.vad_check.setEnabled(False)
            self.vad_check.setText("Smart Silence Removal (Error loading library)")
            self.vad_check.setToolTip(f"VAD requires 'onnxruntime' which failed to load.\nError: {str(e)}\n\nPlease ensure Visual C++ Redistributable is installed.")

        checks_layout.addWidget(self.vad_check)

        # Timestamp Checkbox
        self.timestamp_check = QCheckBox("Add Timestamp")
        self.timestamp_check.setToolTip("Checked: Output includes timestamps [MM:SS -> MM:SS].\nUnchecked: Output contains text only.")
        self.timestamp_check.setChecked(self.settings.value("add_timestamps", False, type=bool))
        checks_layout.addWidget(self.timestamp_check)

        # Report Checkbox
        self.report_check = QCheckBox("Add Report Details")
        self.report_check.setToolTip("Append model/time stats to the output file.")
        self.report_check.setChecked(False)
        checks_layout.addWidget(self.report_check)

        checks_layout.addStretch() # Push to left
        model_layout.addLayout(checks_layout)
        model_layout.addSpacing(5)

        # Language Selection
        lang_layout = QHBoxLayout()
        lang_label = QLabel("Language:")
        self.lang_combo = QComboBox()
        self.lang_combo.addItems(list(LANGUAGE_MAP.keys()))
        self.lang_combo.setToolTip("Select audio language (Auto = detect automatically)")
        self.lang_combo.setMinimumHeight(30)
        lang_layout.addWidget(lang_label)
        lang_layout.addWidget(self.lang_combo)

        # Task Selection (Transcribe / Translate)
        task_label = QLabel("Task:")
        self.task_combo = QComboBox()
        self.task_combo.addItems(["Transcribe", "Translate"])
        self.task_combo.setToolTip("Transcribe: Keep original language.\nTranslate: Translate everything to English.")
        self.task_combo.setMinimumHeight(30)
        lang_layout.addWidget(task_label)
        lang_layout.addWidget(self.task_combo)

        model_layout.addLayout(lang_layout)
        model_layout.addSpacing(5)

        # Initial Prompt
        prompt_layout = QHBoxLayout()
        prompt_label = QLabel("Initial Prompt:")
        self.prompt_edit = QLineEdit()
        self.prompt_edit.setPlaceholderText("Optional: Context or style hint (e.g. 'Hindi conversation')")
        self.prompt_edit.setToolTip("Provide context to guide the model (improves accuracy).")
        self.prompt_edit.setMinimumHeight(30)
        prompt_layout.addWidget(prompt_label)
        prompt_layout.addWidget(self.prompt_edit)
        model_layout.addLayout(prompt_layout)



        left_layout.addWidget(model_group)

        # --- Live Logs (Moved to Left) ---
        log_label = QLabel("Live Logs & Reports")
        log_label.setStyleSheet("font-weight: bold; color: #9ca3af;")
        left_layout.addWidget(log_label)

        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        left_layout.addWidget(self.log_output)

        # Spacer
        left_layout.addStretch()

        # --- Right Pane: Queue & Controls ---
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(20, 20, 20, 20)

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

        # Output Folder Selection
        output_layout = QHBoxLayout()

        self.output_dir_edit = QLineEdit()
        self.output_dir_edit.setPlaceholderText("Default: Same as Input")
        self.output_dir_edit.setReadOnly(True)

        self.output_btn = QPushButton("Destination")
        self.output_btn.setToolTip("Select custom output folder")
        self.output_btn.setObjectName("SecondaryBtn")
        self.output_btn.clicked.connect(self.on_select_output_clicked)

        self.open_btn = QPushButton("Open")
        self.open_btn.setToolTip("Open output folder")
        self.open_btn.setObjectName("SecondaryBtn")
        self.open_btn.clicked.connect(self.on_open_output_clicked)

        output_layout.addWidget(self.output_dir_edit)
        output_layout.addWidget(self.output_btn)
        output_layout.addWidget(self.open_btn)

        queue_layout.addLayout(output_layout)
        right_layout.addWidget(queue_group)

        # Action Buttons
        self.start_btn = QPushButton("Start Transcription")
        self.start_btn.setEnabled(False)
        self.start_btn.setMinimumHeight(50)
        self.start_btn.setStyleSheet("font-size: 16px;")
        self.start_btn.clicked.connect(self.on_start_clicked)
        right_layout.addWidget(self.start_btn)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #ef4444;
                color: white;
                font-weight: bold;
                border-radius: 4px;
                padding: 8px;
            }
            QPushButton:disabled {
                background-color: #d1d5db;
                color: #9ca3af;
            }
        """)
        self.cancel_btn.clicked.connect(self.on_cancel_clicked)
        right_layout.addWidget(self.cancel_btn)

        # Progress Bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("%p%")
        right_layout.addWidget(self.progress_bar)

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
            # Add version label to the right
            version_label = QLabel(f"AI Transcriber App - {APP_VERSION} by Abhishek's AI Labs")
            version_label.setStyleSheet("color: #9ca3af; padding-right: 10px;")
            bar.addPermanentWidget(version_label)

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

        # Load Output Dir
        last_output = self.settings.value("last_output_dir", "")
        if last_output and Path(last_output).exists():
            self.output_dir_edit.setText(last_output)

    # ---------------------------------------------------------
    # EVENTS
    # ---------------------------------------------------------

    def _add_file_item(self, path: str) -> None:
        """Helper to add a file item with numbering and UserRole data."""
        row = self.file_list.count()
        filename = Path(path).name
        item_text = f"{row + 1}. {filename} [In Queue]"

        item = QListWidgetItem(item_text)
        item.setData(Qt.UserRole, str(path))  # Store full path
        self.file_list.addItem(item)

    def on_files_dropped(self, paths: List[str]) -> None:
        for p in paths:
            self._add_file_item(p)

    def on_add_files_clicked(self) -> None:
        last_dir = self.settings.value("last_input_dir", "")
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Select media files", last_dir, MEDIA_FILTER
        )
        if paths:
            for p in paths:
                self._add_file_item(p)

            # Save the directory of the first file
            first_file = Path(paths[0])
            self.settings.setValue("last_input_dir", str(first_file.parent))

    def on_select_output_clicked(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Select Output Folder", self.settings.value("last_output_dir", "")
        )
        if path:
            self.output_dir_edit.setText(path)
            self.settings.setValue("last_output_dir", path)

    def on_open_output_clicked(self) -> None:
        path = self.output_dir_edit.text().strip()
        if not path:
            # If empty, try to open the input directory (default)
            path = self.settings.value("last_input_dir", "")

        if path and Path(path).exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        else:
            self.statusBar().showMessage("Output folder not found.")














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
        # Parse compute type
        ctype_text = self.compute_combo.currentText()
        # "Fast Analysis (int8)" -> int8
        # "Precise Analysis (float32)" -> float32
        # "Deep Analysis (float32)" -> float32
        if "Precise" in ctype_text or "Deep" in ctype_text:
            compute_type = "float32"
        else:
            compute_type = "int8"

        model_path = self.model_edit.text().strip()

        # Check if we need to reload
        if self._transcriber is not None:
            current_config = self._transcriber._config
            if (current_config.model_name == model_path and
                current_config.compute_type == compute_type):
                return True

            LOGGER.info("Configuration changed. Reloading model...")
            self._transcriber = None

        self.statusBar().showMessage("Loading model...")
        try:
            import os

            # Try to detect GPU (optional - fallback to CPU if torch not available)
            device = "cpu"
            try:
                import torch
                if torch.cuda.is_available():
                    device = "cuda"
                    # GPU: use float16 for speed (2-3x faster than float32)
                    if compute_type == "int8":
                        compute_type = "float16"  # int8 not supported on GPU
                    LOGGER.info("CUDA GPU detected! Using GPU acceleration.")
                else:
                    LOGGER.info("CUDA not available. Using CPU.")
            except ImportError:
                LOGGER.info("PyTorch not installed. Using CPU mode only.")

            # Use all available CPU cores for maximum speed
            cpu_count = os.cpu_count() or 4

            config = TranscriptionConfig(
                model_name=model_path,
                language=None,
                device=device,  # Auto-detect GPU or fallback to CPU
                compute_type=compute_type,
                cpu_threads=cpu_count,  # Use all CPU cores
                num_workers=1,  # Keep at 1 for now (can increase for batch processing)
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
        # Collect files
        input_files = []
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            # Retrieve full path from UserRole
            path_str = item.data(Qt.UserRole)
            if path_str:
                path = Path(path_str)
                if path.is_file():
                    input_files.append(path)
                    # Reset text to ensure clean state: "1. filename.mp3 [In Queue]"
                    item.setText(f"{i+1}. {path.name} [In Queue]")

        if not input_files:
            self.show_error("No valid files found in list.")
            return

        # self.file_status_list.clear() # Removed
        self.progress_bar.setValue(0)
        self.statusBar().showMessage("Starting transcription...")
        self._set_busy(True)

        # Use BatchWorker for everything now
        beam_size = 5
        vad_filter = self.vad_check.isChecked()
        patience = 1.0

        # Best Quality Mode
        if "Deep Analysis" in self.compute_combo.currentText():
            beam_size = 10
            patience = 2.0
            LOGGER.info("Deep Analysis Mode enabled: beam_size=10, patience=2.0")

        # Get Language and Prompt
        lang_name = self.lang_combo.currentText()
        lang_code = LANGUAGE_MAP.get(lang_name, "Auto")
        language = None if lang_code == "Auto" else lang_code

        initial_prompt = self.prompt_edit.text().strip() or None

        # Get Task
        task = self.task_combo.currentText().lower()  # "transcribe" or "translate"

        # Get Output Dir
        output_dir_str = self.output_dir_edit.text().strip()
        output_dir = Path(output_dir_str) if output_dir_str else None

        # Get Timestamp Setting
        add_timestamps = self.timestamp_check.isChecked()
        self.settings.setValue("add_timestamps", add_timestamps)

        # Get Report Setting
        add_report = self.report_check.isChecked()

        # Save settings
        self.settings.setValue("language", lang_name)
        self.settings.setValue("initial_prompt", self.prompt_edit.text())
        self.settings.setValue("task", self.task_combo.currentText())

        worker = BatchWorker(
            self._transcriber,
            input_files,
            output_dir,  # output_dir (None = same as input)
            beam_size=beam_size,
            vad_filter=vad_filter,
            language=language,
            initial_prompt=initial_prompt,
            task=task,
            patience=patience,
            add_timestamps=add_timestamps,
            add_report=add_report,
        )
        self._worker = worker

        worker.progress.connect(self.on_progress)
        # worker.speed.connect(self.on_speed_update) # Removed
        worker.file_status.connect(self.on_file_status_update)
        worker.finished.connect(self.on_finished)
        worker.failed.connect(self.on_failed)
        worker.start()

    def on_file_status_update(self, filename: str, status: str) -> None:
        # Find the item in the list and update it
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            # We stored the original full path in UserRole
            full_path_str = item.data(Qt.UserRole)
            if full_path_str:
                # Worker emits only the filename (path.name), so we compare names
                if Path(full_path_str).name == filename:
                    # Update text: "1. filename.mp3 [Processing]"
                    item.setText(f"{i+1}. {filename} [{status}]")
                    # Optional: Scroll to item
                    self.file_list.scrollToItem(item)
                    break

    def on_progress(self, percent: int) -> None:
        self.progress_bar.setValue(percent)

    def on_finished(self, results: List[TranscriptionResult]) -> None:
        LOGGER.info("on_finished() called with %d results", len(results))
        self.statusBar().showMessage(f"Completed. Files: {len(results)}")
        self._worker = None
        self._set_busy(False)
        self.progress_bar.setValue(100)
        LOGGER.info("Clearing file list...")
        # Disable UI updates while clearing for better performance
        self.file_list.setUpdatesEnabled(False)
        self.file_list.clear()  # Auto-clear queue
        self.file_list.setUpdatesEnabled(True)
        LOGGER.info("File list cleared")
        QMessageBox.information(self, "Done", f"Successfully processed {len(results)} files.")
        LOGGER.info("on_finished() complete")

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
