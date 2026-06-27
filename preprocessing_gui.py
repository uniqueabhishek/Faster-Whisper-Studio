"""Preprocessing window for Faster-Whisper GUI."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import Qt, QSettings, Signal, QObject
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QGroupBox,
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
    QSlider,
    QAbstractItemView,
    QListWidgetItem,
    QSplitter,
)

from styles import DARK_THEME_QSS, apply_dark_title_bar
from audio_processor import PreprocessingConfig
from preprocessing_worker import PreprocessingWorker
from preprocessing_config_dialogs import (
    NoiseReductionConfigDialog,
    MusicRemovalConfigDialog,
    NormalizationConfigDialog,
    VADConfigDialog,
    WAVConfigDialog
)

from ui_common import (
    MEDIA_FILTER, QtLogHandler, DragDropWidget, center_window,
    settings_bool, settings_int,
)

LOGGER = logging.getLogger(__name__)

DEFAULT_WIDTH = 900
DEFAULT_HEIGHT = 700


class PreprocessingBase(QWidget):
    """Base class for preprocessing functionality (embeddable)."""

    # Signals
    transcription_requested = Signal(list)  # List[Path]
    open_separate_window_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        self._worker: Optional[PreprocessingWorker] = None

        # UI Components
        self.file_list: QListWidget
        self.convert_check: QCheckBox
        self.trim_check: QCheckBox
        self.normalize_check: QCheckBox
        self.noise_check: QCheckBox
        self.music_check: QCheckBox
        self.db_slider: QSlider
        self.db_label: QLabel
        self.output_edit: QLineEdit
        self.progress_bar: QProgressBar
        self.log_output: QTextEdit
        self.start_btn: QPushButton
        self.skip_btn: QPushButton
        self.cancel_btn: QPushButton

        # Settings
        self.settings = QSettings("FasterWhisperGUI", "Preprocessing")

        # Configuration storage for each feature
        self.noise_config = {
            'noise_reduction_nr': 12.0,
            'noise_reduction_nf': -25.0,
            'noise_reduction_gs': 3,
        }
        self.music_config = {
            'music_highpass_freq': 200,
            'music_lowpass_freq': 3500,
        }
        self.normalize_config = {
            'normalize_target_db': -20.0,
            'normalize_true_peak': -1.5,
            'normalize_loudness_range': 11,
        }
        self.vad_config = {
            'vad_min_silence_ms': 3000,
            'vad_speech_pad_ms': 1000,
            'vad_threshold': 0.1,
        }
        self.wav_config = {
            'wav_sample_rate': 16000,
            'wav_channels': 1,
            'wav_bit_depth': 16,
        }

        self._build_ui()
        self._setup_logging()
        self._load_settings()

    def _setup_logging(self) -> None:
        """Redirect preprocessing-specific logging to the GUI text area."""
        handler = QtLogHandler(self.log_output)
        # Only show preprocessing-related logs
        handler.addFilter(lambda record:
            'preprocessing' in record.name.lower() or
            'audio_processor' in record.name.lower() or
            record.name == 'root'
        )
        logging.getLogger().addHandler(handler)

    def _build_ui(self) -> None:
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Splitter for Left (Options/Logs) and Right (File Queue)
        splitter = QSplitter(Qt.Horizontal)  # type: ignore[attr-defined]

        # --- LEFT PANE: Preprocessing Options, Output Folder, Live Logs ---
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(20, 20, 10, 20)
        left_layout.setSpacing(15)

        # Header (in left pane)
        header = QLabel("Audio Preprocessing")
        header.setObjectName("Header")
        header.setStyleSheet("font-size: 24px; font-weight: bold; color: #3b82f6;")
        left_layout.addWidget(header)

        # Preprocessing Options Group
        options_group = QGroupBox("Preprocessing Options")
        options_layout = QVBoxLayout(options_group)
        options_layout.setSpacing(10)
        options_layout.setContentsMargins(15, 20, 15, 15)

        # Convert to WAV checkbox (with settings button)
        convert_row = QHBoxLayout()

        self.convert_check = QCheckBox("1. Convert to WAV (Always Active)")
        self.convert_check.setToolTip("Convert audio to WAV format - required for Whisper AI\nThis option is always enabled and cannot be disabled.\nClick ⚙ to configure sample rate, channels, and bit depth.")
        self.convert_check.setChecked(True)
        self.convert_check.setEnabled(False)
        self.convert_check.setStyleSheet("""
            QCheckBox:disabled {
                color: #ffffff;
            }
            QCheckBox::indicator:disabled:checked {
                background-color: #3b82f6;
                border: 2px solid #2563eb;
            }
        """)
        convert_row.addWidget(self.convert_check)
        convert_row.addStretch()

        convert_settings_btn = QPushButton("⚙")
        convert_settings_btn.setObjectName("SettingsBtn")
        convert_settings_btn.setFixedSize(30, 30)
        convert_settings_btn.setToolTip("Configure WAV conversion parameters")
        convert_settings_btn.clicked.connect(self._on_wav_settings_clicked)
        convert_row.addWidget(convert_settings_btn)

        options_layout.addLayout(convert_row)

        # Remove noise checkbox (with settings button)
        noise_row = QHBoxLayout()

        self.noise_check = QCheckBox("2. Remove Background Noise")
        self.noise_check.setToolTip("Apply FFT-based noise reduction filter\nWorks best on full spectrum before frequency filtering\nClick ⚙ to configure noise reduction strength, noise floor, and artifact reduction.")
        noise_row.addWidget(self.noise_check)
        noise_row.addStretch()

        noise_settings_btn = QPushButton("⚙")
        noise_settings_btn.setObjectName("SettingsBtn")
        noise_settings_btn.setFixedSize(30, 30)
        noise_settings_btn.setToolTip("Configure noise reduction parameters")
        noise_settings_btn.clicked.connect(self._on_noise_settings_clicked)
        noise_row.addWidget(noise_settings_btn)

        options_layout.addLayout(noise_row)

        # Remove music checkbox (with settings button)
        music_row = QHBoxLayout()

        self.music_check = QCheckBox("3. Remove Background Music")
        self.music_check.setToolTip(
            "Isolate speech frequencies using bandpass filter (200Hz-3500Hz)\n"
            "Removes bass/music <200Hz and high frequencies >3500Hz\n"
            "Applied before normalization for accurate speech-only loudness measurement\n"
            "Click ⚙ to configure high-pass and low-pass filter frequencies."
        )
        music_row.addWidget(self.music_check)
        music_row.addStretch()

        music_settings_btn = QPushButton("⚙")
        music_settings_btn.setObjectName("SettingsBtn")
        music_settings_btn.setFixedSize(30, 30)
        music_settings_btn.setToolTip("Configure music removal filter frequencies")
        music_settings_btn.clicked.connect(self._on_music_settings_clicked)
        music_row.addWidget(music_settings_btn)

        options_layout.addLayout(music_row)

        # Normalize audio checkbox with settings button and slider
        normalize_layout = QHBoxLayout()

        self.normalize_check = QCheckBox("4. Normalize Audio Volume")
        self.normalize_check.setToolTip(
            "Normalize volume to consistent level using EBU R128 standard\n"
            "Applied after filtering to measure speech-band loudness accurately\n"
            "Target: -20 LUFS (broadcast speech standard)\n"
            "Click ⚙ to configure target loudness, true peak, and loudness range."
        )
        self.normalize_check.stateChanged.connect(self._on_normalize_toggled)
        normalize_layout.addWidget(self.normalize_check)

        normalize_layout.addWidget(QLabel("Target:"))
        self.db_label = QLabel("-20 dB")
        self.db_label.setStyleSheet("color: #3b82f6; font-weight: bold;")
        normalize_layout.addWidget(self.db_label)

        self.db_slider = QSlider(Qt.Horizontal)  # type: ignore[attr-defined]
        self.db_slider.setRange(-30, 0)
        self.db_slider.setValue(-20)
        self.db_slider.setEnabled(False)
        self.db_slider.valueChanged.connect(self._on_db_changed)
        normalize_layout.addWidget(self.db_slider)
        normalize_layout.setStretch(3, 1)  # Make slider expand

        normalize_settings_btn = QPushButton("⚙")
        normalize_settings_btn.setObjectName("SettingsBtn")
        normalize_settings_btn.setFixedSize(30, 30)
        normalize_settings_btn.setToolTip("Configure normalization parameters (target loudness, true peak, loudness range)")
        normalize_settings_btn.clicked.connect(self._on_normalize_settings_clicked)
        normalize_layout.addWidget(normalize_settings_btn)

        options_layout.addLayout(normalize_layout)

        # Trim silence checkbox (with settings button)
        trim_row = QHBoxLayout()

        self.trim_check = QCheckBox("5. Trim Silence (VAD)")
        self.trim_check.setToolTip(
            "Use Voice Activity Detection to remove ALL silence segments\n"
            "Concatenates detected speech segments, removing silence from anywhere in audio\n"
            "Applied LAST - works best on normalized, clean speech\n"
            "Click ⚙ to configure min silence duration, speech padding, and detection threshold."
        )
        trim_row.addWidget(self.trim_check)
        trim_row.addStretch()

        trim_settings_btn = QPushButton("⚙")
        trim_settings_btn.setObjectName("SettingsBtn")
        trim_settings_btn.setFixedSize(30, 30)
        trim_settings_btn.setToolTip("Configure VAD silence trimming parameters")
        trim_settings_btn.clicked.connect(self._on_vad_settings_clicked)
        trim_row.addWidget(trim_settings_btn)

        options_layout.addLayout(trim_row)

        left_layout.addWidget(options_group)

        # Output Folder
        output_layout = QHBoxLayout()
        output_layout.addWidget(QLabel("Output Folder:"))

        self.output_edit = QLineEdit()
        self.output_edit.setPlaceholderText("Temp Directory (Auto)")
        self.output_edit.setReadOnly(True)
        output_layout.addWidget(self.output_edit)

        output_btn = QPushButton("Browse...")
        output_btn.setObjectName("SecondaryBtn")
        output_btn.clicked.connect(self.on_select_output_clicked)
        output_layout.addWidget(output_btn)

        left_layout.addLayout(output_layout)

        # Live Logs
        log_label = QLabel("Live Logs:")
        log_label.setStyleSheet("font-weight: bold; color: #9ca3af;")
        left_layout.addWidget(log_label)

        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        left_layout.addWidget(self.log_output)

        # --- RIGHT PANE: Drag & Drop and File Queue ---
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(10, 20, 20, 20)
        right_layout.setSpacing(15)

        # File Queue Group
        queue_group = QGroupBox("Files to Preprocess")
        queue_layout = QVBoxLayout(queue_group)

        # Drag & Drop Area
        self.drag_drop = DragDropWidget("Drag & Drop Audio Files Here")
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

        right_layout.addWidget(queue_group)

        # Progress Bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        right_layout.addWidget(self.progress_bar)

        # Action Buttons
        action_layout = QHBoxLayout()

        self.start_btn = QPushButton("Start Audio Cleaning")
        self.start_btn.setMinimumHeight(45)
        self.start_btn.setStyleSheet("font-size: 14px; font-weight: bold;")
        self.start_btn.clicked.connect(self.on_start_transcription_clicked)
        action_layout.addWidget(self.start_btn)

        self.skip_btn = QPushButton("Skip Preprocessing")
        self.skip_btn.setObjectName("SecondaryBtn")
        self.skip_btn.setMinimumHeight(45)
        self.skip_btn.clicked.connect(self.on_skip_preprocessing_clicked)
        action_layout.addWidget(self.skip_btn)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.setMinimumHeight(45)
        self.cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #ef4444;
                color: white;
                font-weight: bold;
                border-radius: 4px;
            }
            QPushButton:disabled {
                background-color: #d1d5db;
                color: #9ca3af;
            }
        """)
        self.cancel_btn.clicked.connect(self.on_cancel_clicked)
        action_layout.addWidget(self.cancel_btn)

        right_layout.addLayout(action_layout)

        # Add widgets to splitter
        splitter.addWidget(left_widget)
        splitter.addWidget(right_widget)
        splitter.setSizes([700, 600])  # Left pane slightly larger
        splitter.setHandleWidth(3)  # Consistent handle width
        splitter.setCollapsible(0, False)
        splitter.setCollapsible(1, False)

        main_layout.addWidget(splitter)

    def _load_settings(self) -> None:
        """Load preprocessing settings."""
        self.convert_check.setChecked(settings_bool(self.settings, "convert_wav", True))
        self.trim_check.setChecked(settings_bool(self.settings, "trim_silence", False))
        self.normalize_check.setChecked(settings_bool(self.settings, "normalize", False))
        self.noise_check.setChecked(settings_bool(self.settings, "reduce_noise", False))
        self.music_check.setChecked(settings_bool(self.settings, "remove_music", False))

        target_db = settings_int(self.settings, "target_db", -20)
        self.db_slider.setValue(target_db)

        output_dir = self.settings.value("output_dir", "")
        if output_dir and Path(output_dir).exists():
            self.output_edit.setText(output_dir)

        # Load configuration dictionaries
        saved_noise = self.settings.value("noise_config")
        if saved_noise and isinstance(saved_noise, dict):
            self.noise_config.update(saved_noise)

        saved_music = self.settings.value("music_config")
        if saved_music and isinstance(saved_music, dict):
            self.music_config.update(saved_music)

        saved_normalize = self.settings.value("normalize_config")
        if saved_normalize and isinstance(saved_normalize, dict):
            self.normalize_config.update(saved_normalize)
            # Update slider to reflect loaded config
            self.db_slider.setValue(int(saved_normalize.get('normalize_target_db', -20)))

        saved_vad = self.settings.value("vad_config")
        if saved_vad and isinstance(saved_vad, dict):
            self.vad_config.update(saved_vad)

        saved_wav = self.settings.value("wav_config")
        if saved_wav and isinstance(saved_wav, dict):
            self.wav_config.update(saved_wav)

        self._on_normalize_toggled()

    def _save_settings(self) -> None:
        """Save preprocessing settings."""
        self.settings.setValue("convert_wav", self.convert_check.isChecked())
        self.settings.setValue("trim_silence", self.trim_check.isChecked())
        self.settings.setValue("normalize", self.normalize_check.isChecked())
        self.settings.setValue("reduce_noise", self.noise_check.isChecked())
        self.settings.setValue("remove_music", self.music_check.isChecked())
        self.settings.setValue("target_db", self.db_slider.value())
        self.settings.setValue("output_dir", self.output_edit.text())

        # Save configuration dictionaries
        self.settings.setValue("noise_config", self.noise_config)
        self.settings.setValue("music_config", self.music_config)
        self.settings.setValue("normalize_config", self.normalize_config)
        self.settings.setValue("vad_config", self.vad_config)
        self.settings.setValue("wav_config", self.wav_config)

    def _on_normalize_toggled(self) -> None:
        """Enable/disable dB slider based on normalize checkbox."""
        self.db_slider.setEnabled(self.normalize_check.isChecked())

    def _on_db_changed(self, value: int) -> None:
        """Update dB label when slider changes."""
        self.db_label.setText(f"{value} dB")
        # Also update the config
        self.normalize_config['normalize_target_db'] = float(value)

    # Settings button click handlers
    def _on_wav_settings_clicked(self) -> None:
        """Open WAV conversion configuration dialog."""
        dialog = WAVConfigDialog(
            self,
            current_sample_rate=self.wav_config['wav_sample_rate'],
            current_channels=self.wav_config['wav_channels'],
            current_bit_depth=self.wav_config['wav_bit_depth']
        )
        if dialog.exec() == 2:  # QDialog.Accepted
            self.wav_config.update(dialog.get_values())
            LOGGER.info("WAV conversion config updated: %s", self.wav_config)

    def _on_noise_settings_clicked(self) -> None:
        """Open noise reduction configuration dialog."""
        dialog = NoiseReductionConfigDialog(
            self,
            current_nr=self.noise_config['noise_reduction_nr'],
            current_nf=self.noise_config['noise_reduction_nf'],
            current_gs=self.noise_config['noise_reduction_gs']
        )
        if dialog.exec() == 2:  # QDialog.Accepted
            self.noise_config.update(dialog.get_values())
            LOGGER.info("Noise reduction config updated: %s", self.noise_config)

    def _on_music_settings_clicked(self) -> None:
        """Open music removal configuration dialog."""
        dialog = MusicRemovalConfigDialog(
            self,
            current_highpass=self.music_config['music_highpass_freq'],
            current_lowpass=self.music_config['music_lowpass_freq']
        )
        if dialog.exec() == 2:  # QDialog.Accepted
            self.music_config.update(dialog.get_values())
            LOGGER.info("Music removal config updated: %s", self.music_config)

    def _on_normalize_settings_clicked(self) -> None:
        """Open normalization configuration dialog."""
        dialog = NormalizationConfigDialog(
            self,
            current_target=self.normalize_config['normalize_target_db'],
            current_tp=self.normalize_config['normalize_true_peak'],
            current_lra=self.normalize_config['normalize_loudness_range']
        )
        if dialog.exec() == 2:  # QDialog.Accepted
            self.normalize_config.update(dialog.get_values())
            # Update the slider and label to reflect the new target_db
            self.db_slider.setValue(int(self.normalize_config['normalize_target_db']))
            LOGGER.info("Normalization config updated: %s", self.normalize_config)

    def _on_vad_settings_clicked(self) -> None:
        """Open VAD configuration dialog."""
        dialog = VADConfigDialog(
            self,
            current_min_silence=self.vad_config['vad_min_silence_ms'],
            current_speech_pad=self.vad_config['vad_speech_pad_ms'],
            current_threshold=self.vad_config['vad_threshold']
        )
        if dialog.exec() == 2:  # QDialog.Accepted
            self.vad_config.update(dialog.get_values())
            LOGGER.info("VAD config updated: %s", self.vad_config)

    def _add_file_item(self, path: str) -> None:
        """Helper to add a file item with numbering."""
        row = self.file_list.count()
        filename = Path(path).name
        item_text = f"{row + 1}. {filename}"

        item = QListWidgetItem(item_text)
        item.setData(Qt.UserRole, str(path))  # type: ignore[attr-defined]
        self.file_list.addItem(item)

    def on_files_dropped(self, paths: List[str]) -> None:
        """Handle files dropped onto the drag-drop area."""
        for p in paths:
            self._add_file_item(p)

    def on_add_files_clicked(self) -> None:
        """Handle Add Files button click."""
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Select media files", "", MEDIA_FILTER
        )
        if paths:
            for p in paths:
                self._add_file_item(p)

    def on_select_output_clicked(self) -> None:
        """Handle output folder selection."""
        path = QFileDialog.getExistingDirectory(
            self, "Select Output Folder", self.output_edit.text()
        )
        if path:
            self.output_edit.setText(path)

    def on_start_transcription_clicked(self) -> None:
        """Handle Start Transcription button click."""
        self._save_settings()

        # Check if any preprocessing is selected
        any_preprocessing = (
            self.convert_check.isChecked() or
            self.trim_check.isChecked() or
            self.normalize_check.isChecked() or
            self.noise_check.isChecked() or
            self.music_check.isChecked()
        )

        # Get file list
        input_files = []
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            path_str = item.data(Qt.UserRole)  # type: ignore[union-attr, attr-defined]
            if path_str:
                path = Path(path_str)
                if path.is_file():
                    input_files.append(path)

        # If no preprocessing and no files, just open transcription window
        if not any_preprocessing or not input_files:
            self._open_transcription_window([])
            return

        # Start preprocessing
        LOGGER.info("Starting preprocessing for %d files...", len(input_files))

        # Create preprocessing config
        output_dir_str = self.output_edit.text().strip()
        output_dir = Path(output_dir_str) if output_dir_str else None

        config = PreprocessingConfig(
            convert_to_wav=self.convert_check.isChecked(),
            trim_silence=self.trim_check.isChecked(),
            normalize_audio=self.normalize_check.isChecked(),
            reduce_noise=self.noise_check.isChecked(),
            remove_music=self.music_check.isChecked(),

            # Noise reduction parameters
            **self.noise_config,

            # Music removal parameters
            **self.music_config,

            # Normalization parameters
            **self.normalize_config,

            # VAD parameters
            **self.vad_config,

            # WAV conversion parameters
            **self.wav_config,

            output_dir=output_dir
        )

        # Create and start worker
        self._worker = PreprocessingWorker(input_files, config)
        self._worker.progress.connect(self.on_progress)
        self._worker.step_progress.connect(self.on_step_progress)
        self._worker.file_status.connect(self.on_file_status)
        self._worker.finished.connect(self.on_preprocessing_finished)
        self._worker.failed.connect(self.on_preprocessing_failed)

        self._set_busy(True)
        self._worker.start()

    def shutdown(self) -> None:
        """Cancel running work and join the thread before the app closes."""
        if self._worker is not None and self._worker.isRunning():
            self._worker.request_cancel()
            self._worker.wait(5000)

    def on_skip_preprocessing_clicked(self) -> None:
        """Handle Skip Preprocessing button click."""
        self.transcription_requested.emit([])

    def on_cancel_clicked(self) -> None:
        """Handle Cancel button click."""
        if self._worker:
            self._worker.request_cancel()
        LOGGER.info("Cancelling preprocessing...")

    def on_progress(self, percent: int) -> None:
        """Update progress bar."""
        self.progress_bar.setValue(percent)
        LOGGER.debug(f"Overall progress: {percent}%")

    def on_step_progress(self, filename: str, step_name: str, step_percent: int) -> None:
        """Handle step-level progress updates."""
        # Log step information for user visibility
        msg = f"[{filename}] {step_name}... ({step_percent}%)"
        LOGGER.info(msg)

    def on_file_status(self, filename: str, status: str) -> None:
        """Update file status in list."""
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            path_str = item.data(Qt.UserRole)  # type: ignore[union-attr, attr-defined]
            if path_str and Path(path_str).name == filename:
                item.setText(f"{i+1}. {filename} [{status}]")  # type: ignore[union-attr]
                self.file_list.scrollToItem(item)
                break

    def on_preprocessing_finished(self, preprocessed_files: List[Path]) -> None:
        """Handle preprocessing completion."""
        LOGGER.info("Preprocessing completed. %d files ready.", len(preprocessed_files))
        self._set_busy(False)
        self._worker = None

        # Emit signal with processed files (subclasses will handle)
        self.transcription_requested.emit(preprocessed_files)

    def on_preprocessing_failed(self, message: str) -> None:
        """Handle preprocessing failure."""
        LOGGER.error("Preprocessing failed: %s", message)
        self._set_busy(False)
        self._worker = None

        if message != "Cancelled":
            QMessageBox.critical(self, "Error", f"Preprocessing failed:\n{message}")

    def _set_busy(self, busy: bool) -> None:
        """Set UI to busy/idle state."""
        self.start_btn.setEnabled(not busy)
        self.skip_btn.setEnabled(not busy)
        self.cancel_btn.setEnabled(busy)
        self.file_list.setEnabled(not busy)
        self.drag_drop.setVisible(not busy)
        # convert_check is always disabled, so we don't change its state
        self.trim_check.setEnabled(not busy)
        self.normalize_check.setEnabled(not busy)
        self.noise_check.setEnabled(not busy)
        self.music_check.setEnabled(not busy)
        self.db_slider.setEnabled(not busy and self.normalize_check.isChecked())

    def set_read_only(self, read_only: bool) -> None:
        """Set preprocessing view to read-only mode."""
        # Disable file selection
        self.drag_drop.setVisible(not read_only)
        self.file_list.setEnabled(not read_only)

        # Disable preprocessing options
        self.start_btn.setEnabled(not read_only)
        self.skip_btn.setEnabled(not read_only)
        self.convert_check.setEnabled(not read_only)
        self.trim_check.setEnabled(not read_only)
        self.normalize_check.setEnabled(not read_only)
        self.noise_check.setEnabled(not read_only)
        self.music_check.setEnabled(not read_only)
        self.db_slider.setEnabled(not read_only)


class PreprocessingView(PreprocessingBase):
    """Embedded preprocessing view (for use in MainWindow)."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        # Add "Open in New Window" button to header
        self._add_open_in_new_window_button()

    def _add_open_in_new_window_button(self) -> None:
        """Add 'Open in New Window' button to the right pane header."""
        # The main layout is now QHBoxLayout containing a splitter
        # We need to find the splitter, then the right widget, then its layout, then the header
        main_layout = self.layout()
        if not main_layout or main_layout.count() == 0:
            return

        # Get the splitter (first item in main layout)
        splitter_item = main_layout.itemAt(0)
        if not splitter_item:
            return

        splitter = splitter_item.widget()
        if not splitter or not isinstance(splitter, QSplitter):
            return

        # Get the right widget (second widget in splitter)
        if splitter.count() < 2:
            return

        right_widget = splitter.widget(1)
        if not right_widget:
            return

        right_layout = right_widget.layout()
        if not right_layout or right_layout.count() == 0:
            return

        # Get the header (first item in right layout)
        header_item = right_layout.itemAt(0)
        if not header_item:
            return

        header_widget = header_item.widget()
        if not header_widget or not isinstance(header_widget, QLabel):
            return

        # Create a horizontal layout to hold header and button
        header_container = QWidget()
        header_layout = QHBoxLayout(header_container)
        header_layout.setContentsMargins(0, 0, 0, 0)

        # Move header to container
        header_widget.setParent(None)
        header_layout.addWidget(header_widget)
        header_layout.addStretch()

        # Add "Open in New Window" button
        self.open_new_window_btn = QPushButton("Open in New Window")
        self.open_new_window_btn.setObjectName("SecondaryBtn")
        self.open_new_window_btn.setToolTip("Open a separate preprocessing window for additional files")
        self.open_new_window_btn.clicked.connect(self._on_open_new_window_clicked)
        header_layout.addWidget(self.open_new_window_btn)

        # Replace header widget with container in right layout
        right_layout.removeWidget(header_widget)
        right_layout.insertWidget(0, header_container)

    def _on_open_new_window_clicked(self) -> None:
        """Handle 'Open in New Window' button click."""
        self.open_separate_window_requested.emit()


class PreprocessingWindow(QMainWindow):
    """Standalone preprocessing window."""

    preprocessing_completed = Signal(list)  # List[Path]

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Audio Preprocessing - New Window")
        self.setWindowFlags(Qt.Window)  # type: ignore[attr-defined] # Make it a proper window

        # Apply Dark Theme
        app = QApplication.instance()
        if app:
            settings_btn_style = """
                QPushButton#SettingsBtn {
                    background-color: #3b82f6;
                    color: white;
                    border: none;
                    border-radius: 15px;
                    font-size: 16px;
                    font-weight: bold;
                }
                QPushButton#SettingsBtn:hover {
                    background-color: #2563eb;
                }
                QPushButton#SettingsBtn:pressed {
                    background-color: #1d4ed8;
                }
            """
            app.setStyleSheet(DARK_THEME_QSS + settings_btn_style)  # type: ignore[attr-defined]

        # Apply Windows Dark Title Bar
        apply_dark_title_bar(int(self.winId()))

        # Embed PreprocessingBase
        self._view = PreprocessingBase(parent=self)
        self.setCentralWidget(self._view)

        # Connect signal
        self._view.transcription_requested.connect(self._on_transcription_requested)

        self.resize(DEFAULT_WIDTH, DEFAULT_HEIGHT)
        self._center_window()

    def _center_window(self) -> None:
        """Centers the window on the screen."""
        center_window(self)

    def _on_transcription_requested(self, files: List[Path]) -> None:
        """Handle transcription request from embedded view."""
        if files:
            # Show dialog: "Add to transcription queue?"
            reply = QMessageBox.question(
                self,
                'Add to Queue',
                f'Add {len(files)} processed files to transcription queue?',
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes
            )

            if reply == QMessageBox.Yes:
                self.preprocessing_completed.emit(files)

        # Close window regardless of choice
        self.close()
