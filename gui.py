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
from workers import BatchWorker, ModelLoaderWorker
from styles import DARK_THEME_QSS, apply_dark_title_bar
from session_manager import SessionManager, SessionState
from resume_dialog import ResumeSessionDialog
from ui_common import MEDIA_FILTER, QtLogHandler, DragDropWidget, center_window

LOGGER = logging.getLogger(__name__)

DEFAULT_WIDTH = 1300
DEFAULT_HEIGHT = 800
APP_VERSION = "v2.1.3"

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


class TranscriptionView(QWidget):
    """Transcription view widget (embeddable)."""

    transcription_started = pyqtSignal()
    transcription_finished = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None, initial_files: Optional[List[Path]] = None) -> None:
        super().__init__(parent)

        self._transcriber: Optional[Transcriber] = None
        self._worker: Optional[BatchWorker] = None
        self._model_loader: Optional[ModelLoaderWorker] = None
        self._pending_batch_args: Optional[dict] = None
        self._status_bar: Optional[QStatusBar] = None
        self._resume_session: Optional[SessionState] = None

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

        # Session manager (lazy initialization)
        self._session_manager: Optional[SessionManager] = None

        self._build_ui()
        self._setup_logging()

        self._load_settings()

        # Check for incomplete sessions AFTER UI is built (lazy init session manager)
        from PyQt5.QtCore import QTimer
        QTimer.singleShot(500, self._check_for_resume_session)

        # Add initial files to queue if provided
        if initial_files:
            for file_path in initial_files:
                self._add_file_item(str(file_path))

    @property
    def session_manager(self) -> SessionManager:
        """Lazy initialization of session manager."""
        if self._session_manager is None:
            self._session_manager = SessionManager()
        return self._session_manager

    def set_status_bar(self, status_bar: QStatusBar) -> None:
        """Set the status bar for this view (called by parent window)."""
        self._status_bar = status_bar
        if status_bar:
            status_bar.showMessage("Ready")
            # Add version label to the right
            version_label = QLabel(f"AI Transcriber App - {APP_VERSION} by Abhishek's AI Labs")
            version_label.setStyleSheet("color: #9ca3af; padding-right: 10px;")
            status_bar.addPermanentWidget(version_label)

    def _setup_logging(self) -> None:
        """Redirect transcription-specific logging to the GUI text area."""
        handler = QtLogHandler(self.log_output)
        # Only show transcription-related logs (exclude preprocessing logs)
        handler.addFilter(lambda record:
            'transcrib' in record.name.lower() or
            'worker' in record.name.lower() or
            'batch' in record.name.lower() or
            (record.name == 'root' and
             'preprocessing' not in record.getMessage().lower() and
             'audio_processor' not in record.getMessage().lower())
        )
        logging.getLogger().addHandler(handler)
        logging.getLogger().setLevel(logging.INFO)

    def statusBar(self) -> Optional[QStatusBar]:
        """Return the status bar (if set by parent)."""
        return self._status_bar

    def show_error(self, message: str) -> None:
        QMessageBox.critical(self, "Error", message)

    def add_files_to_queue(self, files: List[Path]) -> None:
        """Public method to add files from external source."""
        # Prevent adding files during active transcription
        if self._worker is not None and self._worker.isRunning():
            LOGGER.warning("Cannot add files while transcription is running")
            QMessageBox.warning(
                self,
                "Transcription In Progress",
                "Cannot add files to the queue while transcription is running.\n\n"
                "Please wait for the current transcription to complete.",
                QMessageBox.Ok
            )
            return

        for file_path in files:
            self._add_file_item(str(file_path))

    def _build_ui(self) -> None:
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Splitter for Left (Controls) and Right (Logs)
        splitter = QSplitter(Qt.Horizontal)

        # --- Left Pane: Controls ---
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(20, 20, 10, 20)
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
            "Precise Analysis (float32)",
            "Deep Analysis (float32)"
        ])
        # Set tooltips for each item
        self.compute_combo.setItemData(0, "Checks 5 possibilities (full precision).", Qt.ToolTipRole)
        self.compute_combo.setItemData(1, "Checks 10 possibilities (full precision).", Qt.ToolTipRole)
        self.compute_combo.setMinimumHeight(30) # Taller combo

        # Set default to Precise Analysis
        self.compute_combo.setCurrentIndex(0)

        compute_layout.addWidget(compute_label)
        compute_layout.addWidget(self.compute_combo)
        model_layout.addLayout(compute_layout)
        model_layout.addSpacing(5)

        # Checkboxes Layout (Horizontal)
        checks_layout = QHBoxLayout()

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

        # --- Right Pane: Queue & Controls ---
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(10, 20, 20, 20)

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
        splitter.setSizes([700, 600])
        splitter.setHandleWidth(3)  # Consistent handle width
        splitter.setCollapsible(0, False)
        splitter.setCollapsible(1, False)

        main_layout.addWidget(splitter)

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

    def _check_for_resume_session(self) -> None:
        """Check for incomplete sessions and prompt user to resume."""
        try:
            latest_session = self.session_manager.get_latest_session()

            if latest_session is None:
                return

            # Show resume dialog
            LOGGER.info("Found incomplete session: %s", latest_session.session_id)
            resumed_session = ResumeSessionDialog.show_resume_dialog(latest_session, self)

            if resumed_session:
                # User chose to resume
                self._resume_session = resumed_session
                LOGGER.info("User chose to resume session")

                # Load session files into queue
                for file_status in resumed_session.pending_files + resumed_session.failed_files:
                    self._add_file_item(file_status.path)

                # Update model path from session
                if Path(resumed_session.model_path).exists():
                    self.model_edit.setText(resumed_session.model_path)

                # Update output directory
                if resumed_session.output_dir:
                    self.output_dir_edit.setText(resumed_session.output_dir)

                # Show status message
                if self.statusBar():
                    pending_count = len(resumed_session.pending_files) + len(resumed_session.failed_files)
                    self.statusBar().showMessage(
                        f"Session resumed: {pending_count} files to process"
                    )

                # Highlight the start button to draw attention
                self.start_btn.setStyleSheet("""
                    QPushButton {
                        background-color: #3b82f6;
                        color: white;
                        font-weight: bold;
                        border: 2px solid #60a5fa;
                    }
                """)
            else:
                LOGGER.info("User chose to discard session")

        except Exception as e:
            LOGGER.error("Error checking for resume session: %s", e)

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
            if self.statusBar():
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

    def _build_config(self) -> Optional[TranscriptionConfig]:
        """Build the TranscriptionConfig from the UI (no model load here).

        Device/compute-type detection is cheap and kept on the GUI thread so the
        reload check below can compare fully-resolved configs. The expensive
        model load happens off-thread in ModelLoaderWorker.
        """
        import os

        # Parse compute type
        # "Fast Analysis (int8)" -> int8
        # "Precise Analysis (float32)" / "Deep Analysis (float32)" -> float32
        ctype_text = self.compute_combo.currentText()
        if "Precise" in ctype_text or "Deep" in ctype_text:
            compute_type = "float32"
        else:
            compute_type = "int8"

        model_path = self.model_edit.text().strip()
        if not model_path:
            self.show_error("No model selected.")
            return None

        # Detect GPU via CTranslate2's own CUDA runtime — no torch dependency.
        # (CTranslate2 is what actually runs the model and ships its own CUDA
        # libs, so its device count is the authoritative signal.)
        device = "cpu"
        try:
            import ctranslate2
            if ctranslate2.get_cuda_device_count() > 0:
                device = "cuda"
                # GPU: use float16 for speed (2-3x faster than float32)
                if compute_type == "int8":
                    compute_type = "float16"  # int8 not supported on GPU
                LOGGER.info("CUDA GPU detected! Using GPU acceleration.")
            else:
                LOGGER.info("CUDA not available. Using CPU.")
        except Exception as exc:  # pylint: disable=broad-except
            LOGGER.info("GPU detection unavailable (%s). Using CPU.", exc)

        # Use all available CPU cores for maximum speed
        cpu_count = os.cpu_count() or 4

        return TranscriptionConfig(
            model_name=model_path,
            language=None,
            device=device,  # Auto-detect GPU or fallback to CPU
            compute_type=compute_type,
            cpu_threads=cpu_count,  # Use all CPU cores
            num_workers=1,  # Keep at 1 for now (can increase for batch processing)
        )

    def _needs_reload(self, config: TranscriptionConfig) -> bool:
        """True if the currently-loaded model doesn't match the requested config."""
        if self._transcriber is None:
            return True
        current = self._transcriber._config
        return not (
            current.model_name == config.model_name and
            current.compute_type == config.compute_type and
            current.device == config.device
        )

    def on_start_clicked(self) -> None:
        if self.file_list.count() == 0:
            self.show_error("No files to transcribe.")
            return

        if self._worker is not None or self._model_loader is not None:
            # Already running or loading; ignore double-clicks.
            return

        config = self._build_config()
        if config is None:
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
        self._set_busy(True)
        self.transcription_started.emit()  # Emit signal

        # Use BatchWorker for everything now
        beam_size = 5
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

        # Stash everything the BatchWorker needs. The batch is started either now
        # (model already loaded) or once the off-thread model load completes.
        self._pending_batch_args = dict(
            input_files=input_files,
            output_dir=output_dir,  # output_dir (None = same as input)
            beam_size=beam_size,
            language=language,
            initial_prompt=initial_prompt,
            task=task,
            patience=patience,
            add_timestamps=add_timestamps,
            add_report=add_report,
            resume_session=self._resume_session,  # Pass resume session if exists
        )
        # Clear resume session now to prevent reuse on a later run.
        self._resume_session = None

        if not self._needs_reload(config):
            # Fast path: model already loaded with the right config.
            if self.statusBar():
                self.statusBar().showMessage("Starting transcription...")
            self._start_pending_batch()
            return

        # Slow path: (re)load the model off the GUI thread so the UI stays
        # responsive, then start the batch from the loader's `loaded` signal.
        self._transcriber = None
        if self.statusBar():
            self.statusBar().showMessage("Loading model...")
        loader = ModelLoaderWorker(config)
        self._model_loader = loader
        loader.loaded.connect(self._on_model_loaded)
        loader.failed.connect(self._on_model_load_failed)
        loader.start()

    def _on_model_loaded(self, transcriber: Transcriber) -> None:
        self._transcriber = transcriber
        self._model_loader = None
        if self.statusBar():
            self.statusBar().showMessage("Model loaded. Starting transcription...")
        self._start_pending_batch()

    def _on_model_load_failed(self, message: str) -> None:
        self._model_loader = None
        self._pending_batch_args = None
        self._set_busy(False)
        if self.statusBar():
            self.statusBar().showMessage("Model load failed.")
        self.show_error(f"Failed to load model:\n{message}")
        self.transcription_finished.emit()

    def _start_pending_batch(self) -> None:
        """Create and start the BatchWorker from the stashed arguments."""
        args = self._pending_batch_args
        self._pending_batch_args = None

        # args is None if the start was cancelled while the model was loading;
        # transcriber is None if the load failed.
        if self._transcriber is None or args is None:
            self._set_busy(False)
            if self.statusBar():
                self.statusBar().showMessage("Cancelled.")
            self.transcription_finished.emit()
            return

        worker = BatchWorker(self._transcriber, **args)
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

    def on_finished(self, summary) -> None:
        # BatchWorker emits a summary dict; tolerate a bare list defensively.
        if isinstance(summary, dict):
            results = summary.get("results", [])
            failed = summary.get("failed", 0)
            failed_files = summary.get("failed_files", [])
        else:
            results = summary or []
            failed = 0
            failed_files = []

        LOGGER.info("Transcription completed - %d succeeded, %d failed",
                    len(results), failed)
        if self.statusBar():
            if failed:
                self.statusBar().showMessage(
                    f"Completed: {len(results)} succeeded, {failed} failed.")
            else:
                self.statusBar().showMessage(
                    f"Completed. Successfully processed {len(results)} files.")
        self._worker = None
        self._set_busy(False)
        self.progress_bar.setValue(100)

        if failed:
            # Surface failures rather than implying everything succeeded.
            listing = "\n".join(failed_files[:20])
            if len(failed_files) > 20:
                listing += f"\n... and {len(failed_files) - 20} more"
            self.show_error(
                f"{failed} file(s) failed to transcribe:\n\n{listing}\n\n"
                "See the log for details.")

        # Disable UI updates while clearing for better performance
        self.file_list.setUpdatesEnabled(False)
        self.file_list.clear()  # Auto-clear queue
        self.file_list.setUpdatesEnabled(True)
        self.transcription_finished.emit()  # Emit signal

    def on_failed(self, message: str) -> None:
        self.show_error(message)
        if self.statusBar():
            self.statusBar().showMessage("Failed.")
        self._worker = None
        self._set_busy(False)
        self.transcription_finished.emit()  # Emit signal even on failure

    def on_cancel_clicked(self) -> None:
        if self._worker:
            self._worker.request_cancel()
            if self.statusBar():
                self.statusBar().showMessage("Cancelling...")
        elif self._model_loader is not None and self._model_loader.isRunning():
            # Model is still loading (a blocking CTranslate2 call that can't be
            # interrupted cleanly): drop the queued batch so it won't auto-start
            # once the load finishes, disable the now-pointless cancel button,
            # and tell the user we're waiting the load out. The loaded model is
            # still cached for the next run.
            self._pending_batch_args = None
            self.cancel_btn.setEnabled(False)
            if self.statusBar():
                self.statusBar().showMessage(
                    "Finishing model load, then cancelling…")

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


class TranscriptionWindow(QMainWindow):
    """Standalone window wrapper for TranscriptionView (backwards compatibility)."""

    def __init__(self, initial_files: Optional[List[Path]] = None) -> None:
        super().__init__()
        self.setWindowTitle("Faster-Whisper AI Transcriber [Speech to Text]")

        # Apply Dark Theme
        app = QApplication.instance()
        if app:
            app.setStyleSheet(DARK_THEME_QSS)

        # Apply Windows Dark Title Bar
        apply_dark_title_bar(int(self.winId()))

        # Embed TranscriptionView
        self._view = TranscriptionView(parent=self, initial_files=initial_files)
        self.setCentralWidget(self._view)

        # Connect view's status bar
        self._view.set_status_bar(self.statusBar())

        self.resize(DEFAULT_WIDTH, DEFAULT_HEIGHT)
        self._center_window()

    def _center_window(self) -> None:
        """Centers the window on the screen."""
        center_window(self)


# Backward compatibility alias
MainWindow = TranscriptionWindow
