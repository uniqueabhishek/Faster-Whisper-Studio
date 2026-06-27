"""Worker thread for audio preprocessing in Faster-Whisper GUI."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import QThread, Signal

from audio_processor import PreprocessingConfig, preprocess_audio

LOGGER = logging.getLogger(__name__)


class PreprocessingWorker(QThread):
    """Worker thread for preprocessing multiple audio files sequentially."""

    # Signals
    progress = Signal(int)                    # Overall progress 0-100
    step_progress = Signal(str, str, int)     # filename, step_name, step_percent
    file_status = Signal(str, str)            # filename, status
    finished = Signal(list)                   # List of Path (preprocessed files)
    failed = Signal(str)                      # Error message

    def __init__(
        self,
        input_files: List[Path],
        config: PreprocessingConfig
    ) -> None:
        super().__init__()
        self._input_files = input_files
        self._config = config
        self._cancel = False

    def request_cancel(self) -> None:
        """Request cancellation of preprocessing."""
        self._cancel = True
        LOGGER.info("Preprocessing cancellation requested")

    def run(self) -> None:
        """Run preprocessing on all input files sequentially."""
        total = len(self._input_files)
        if total == 0:
            self.finished.emit([])
            return

        preprocessed_files: List[Path] = []
        completed_files = 0

        # Internal job function with progress tracking
        def _job(input_path: Path, file_index: int) -> Optional[Path]:
            if self._cancel:
                self.file_status.emit(input_path.name, "Cancelled")
                return None

            self.file_status.emit(input_path.name, "Processing")

            # Progress callback to handle step-level updates
            def on_step_progress(step_name: str, step_percent: int):
                if self._cancel:
                    return

                # Emit step information for logging
                self.step_progress.emit(input_path.name, step_name, step_percent)

                # Calculate overall progress:
                # (completed files / total) * 100 + (current step % / total)
                base_progress = (completed_files / total) * 100
                file_contribution = (step_percent / total)
                overall = int(base_progress + file_contribution)

                # Emit overall progress
                self.progress.emit(overall)

            try:
                # Preprocess with progress callback
                output_path = preprocess_audio(
                    input_path,
                    self._config,
                    cancel_check=lambda: self._cancel,
                    progress_callback=on_step_progress
                )

                if output_path and output_path.exists():
                    self.file_status.emit(input_path.name, "Done")
                    return output_path
                else:
                    self.file_status.emit(input_path.name, "Failed")
                    return None

            except Exception as e:
                LOGGER.error("Error preprocessing %s: %s", input_path.name, str(e))
                self.file_status.emit(input_path.name, "Failed")
                return None

        # Process files sequentially for accurate progress tracking
        for i, input_path in enumerate(self._input_files):
            if self._cancel:
                self.failed.emit("Cancelled")
                return

            result = _job(input_path, i)

            if result is not None:
                preprocessed_files.append(result)
                LOGGER.info("Successfully preprocessed: %s", input_path.name)

            completed_files += 1

            # Emit progress after file completion
            overall = int((completed_files / total) * 100)
            self.progress.emit(overall)

        # Emit finished with all successfully preprocessed files
        LOGGER.info("Preprocessing completed. %d/%d files successful", len(preprocessed_files), total)
        self.finished.emit(preprocessed_files)
