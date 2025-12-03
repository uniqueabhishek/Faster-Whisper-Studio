"""Worker threads for Faster-Whisper GUI."""

from __future__ import annotations

import logging
import time
import threading
from pathlib import Path
from typing import List, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

from PyQt5.QtCore import QThread, pyqtSignal

from transcriber import Transcriber, TranscriptionResult

LOGGER = logging.getLogger(__name__)

# Global executor for parallel batch
EXECUTOR = ThreadPoolExecutor(max_workers=4)


class SingleFileWorker(QThread):
    finished = pyqtSignal(object)
    failed = pyqtSignal(str)
    progress = pyqtSignal(int)

    def __init__(
        self,
        transcriber: Transcriber,
        input_path: Path,
        output_path: Optional[Path],
    ) -> None:
        super().__init__()
        self._transcriber = transcriber
        self._input_path = input_path
        self._output_path = output_path
        self._cancel = False

    def request_cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        LOGGER.info("=== WORKER RUN STARTED ===")
        if self._cancel:
            LOGGER.info("Worker cancelled before start")
            self.failed.emit("Cancelled")
            return
        try:
            LOGGER.info("Starting transcription of: %s", self._input_path)
            result = self._transcriber.transcribe_file(
                self._input_path,
                output_path=self._output_path,
                progress_callback=self.progress.emit,
            )
            LOGGER.info("Transcription completed successfully")
            if self._cancel:
                LOGGER.info("Worker cancelled after transcription")
                self.failed.emit("Cancelled")
                return
            LOGGER.info("Emitting finished signal...")
            self.finished.emit(result)
            LOGGER.info("Finished signal emitted")
        except Exception as exc:  # noqa
            import traceback
            error_msg = f"{str(exc)}\n\nTraceback:\n{traceback.format_exc()}"
            LOGGER.error("Transcription failed: %s", error_msg)
            self.failed.emit(str(exc))


class BatchWorker(QThread):
    progress = pyqtSignal(int)                # overall_percent (0-100)
    speed = pyqtSignal(float, int)            # avg_time, eta_seconds
    file_status = pyqtSignal(str, str)        # filename, status
    finished = pyqtSignal(object)             # list of TranscriptionResult
    failed = pyqtSignal(str)                  # error message

    def __init__(
        self,
        transcriber: Transcriber,
        input_files: List[Path],
        output_dir: Optional[Path],
        beam_size: int = 5,
        vad_filter: bool = False,
        language: Optional[str] = None,
        initial_prompt: Optional[str] = None,
    ) -> None:
        super().__init__()
        self._transcriber = transcriber
        self._input_files = input_files
        self._output_dir = output_dir
        self._beam_size = beam_size
        self._vad_filter = vad_filter
        self._language = language
        self._initial_prompt = initial_prompt
        self._cancel = False
        self._model_lock = threading.Lock()

    def request_cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        media_files = self._input_files
        total = len(media_files)
        if total == 0:
            self.finished.emit([])
            return

        results: List[TranscriptionResult] = []
        start_time = time.time()
        processed = 0

        # Internal job with lock for thread-safety
        def _job(path: Path) -> Optional[TranscriptionResult]:
            if self._cancel:
                return None

            self.file_status.emit(path.name, "Processing")

            def _on_file_progress(file_percent: int):
                # Calculate overall progress
                # processed: number of fully completed files
                # file_percent: percentage of current file
                # total: total number of files
                if total > 0:
                    overall = int((processed * 100 + file_percent) / total)
                    self.progress.emit(overall)

            try:
                with self._model_lock:
                    out_path = (
                        self._output_dir / f"{path.stem}.txt"
                        if self._output_dir
                        else path.with_suffix(".txt")
                    )
                    result = self._transcriber.transcribe_file(
                        path,
                        output_path=out_path,
                        progress_callback=_on_file_progress,
                        beam_size=self._beam_size,
                        vad_filter=self._vad_filter,
                        language=self._language,
                        initial_prompt=self._initial_prompt,
                    )
                return result
            except Exception as e:
                LOGGER.error("Error processing %s: %s", path.name, str(e))
                import traceback
                LOGGER.error(traceback.format_exc())
                return None

        # Submit all futures to global executor
        futures = {EXECUTOR.submit(_job, p): p for p in media_files}

        try:
            for future in as_completed(futures):
                if self._cancel:
                    self.failed.emit("Cancelled")
                    return

                processed += 1
                media_path = futures[future]

                result = future.result()
                if result is not None:
                    results.append(result)
                    self.file_status.emit(media_path.name, "Done")
                else:
                    self.file_status.emit(media_path.name, "Failed")

                # Speed + ETA calculations
                elapsed = time.time() - start_time
                avg_time = elapsed / processed
                eta = int((total - processed) * avg_time)

                # Emit 100% for this file (or base for next)
                if total > 0:
                    overall = int((processed * 100) / total)
                    self.progress.emit(overall)

                self.speed.emit(avg_time, eta)

        except Exception as exc:
            self.failed.emit(str(exc))
            return

        self.finished.emit(results)
