"""Worker threads for Faster-Whisper GUI."""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import List, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

from PyQt5.QtCore import QThread, pyqtSignal

from transcriber import Transcriber, TranscriptionResult
from session_manager import SessionManager, SessionState
from memory_manager import MemoryManager, MemoryMonitor

LOGGER = logging.getLogger(__name__)

# Global executor for parallel batch
EXECUTOR = ThreadPoolExecutor(max_workers=2)


class ModelLoaderWorker(QThread):
    """Loads the Whisper model off the GUI thread.

    Building a ``Transcriber`` instantiates ``WhisperModel`` (a multi-hundred-MB
    blocking load), which previously ran on the Qt main loop and froze the UI
    ("Not Responding") on every model / compute-type change. This worker moves
    that load to a background thread and signals the result.
    """

    loaded = pyqtSignal(object)   # Transcriber
    failed = pyqtSignal(str)      # error message

    def __init__(self, config) -> None:
        super().__init__()
        self._config = config

    def run(self) -> None:
        try:
            LOGGER.info("Loading model on background thread...")
            transcriber = Transcriber(self._config)
            LOGGER.info("Model loaded successfully.")
            self.loaded.emit(transcriber)
        except Exception as exc:  # noqa: BLE001  pylint: disable=broad-except
            import traceback
            LOGGER.error("Model loading failed: %s\n%s",
                         exc, traceback.format_exc())
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
        task: str = "transcribe",
        patience: float = 1.0,
        add_timestamps: bool = True,
        add_report: bool = True,
        resume_session: Optional[SessionState] = None,
    ) -> None:
        super().__init__()
        self._transcriber = transcriber
        self._input_files = input_files
        self._output_dir = output_dir
        self._beam_size = beam_size
        self._vad_filter = vad_filter
        self._language = language
        self._initial_prompt = initial_prompt
        self._task = task
        self._patience = patience
        self._add_timestamps = add_timestamps
        self.add_report = add_report
        self._cancel = False
        self._model_lock = threading.Lock()
        self._prep_lock = threading.Lock() # Lock for audio preparation (ffmpeg)
        self._pipeline_semaphore = threading.Semaphore(1)  # Only 1 file can be "in-flight" (preprocessing+transcribing) at a time

        # Session management
        self._session_manager = SessionManager()
        self._session: Optional[SessionState] = resume_session
    def request_cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        # Clean up orphaned temp files from previous crashes
        self._session_manager.cleanup_orphaned_files()

        # Create or resume session
        if self._session is None:
            self._session = self._session_manager.create_session(
                input_files=self._input_files,
                model_path=self._transcriber._config.model_name,
                output_dir=self._output_dir,
                beam_size=self._beam_size,
                vad_filter=self._vad_filter,
                language=self._language,
                initial_prompt=self._initial_prompt,
                task=self._task,
                patience=self._patience,
                add_timestamps=self._add_timestamps,
                add_report=self.add_report,
            )
            media_files = self._input_files
        else:
            # Resume from saved session
            LOGGER.info("Resuming session: %s", self._session.session_id)
            pending = self._session.pending_files
            media_files = [Path(f.path) for f in pending]
            LOGGER.info("Resuming %d pending files", len(media_files))

        # Ensure session is initialized
        assert self._session is not None, "Session must be initialized"

        total = len(self._session.files)
        if total == 0:
            self.finished.emit([])
            return

        results: List[TranscriptionResult] = []

        # Calculate already processed count for progress
        already_processed = len(self._session.completed_files) + len(self._session.failed_files)
        processed = already_processed

        # Log initial memory usage
        MemoryManager.log_memory_usage("Batch start:")

        # Internal job with lock for thread-safety
        def _job(path: Path) -> Optional[TranscriptionResult]:
            # Type guard: session is guaranteed to be non-None at this point
            assert self._session is not None

            if self._cancel:
                self.file_status.emit(path.name, "Cancelled")
                self._session_manager.update_file_status(
                    self._session, str(path), "failed", error="Cancelled"
                )
                return None

            def _on_file_progress(file_percent: int):
                if self._cancel:
                    raise Exception("Cancelled")
                # Calculate overall progress
                if total > 0:
                    overall = int((processed * 100 + file_percent) / total)
                    self.progress.emit(overall)

            # Acquire semaphore to control pipeline - only 1 file can be preprocessing+transcribing at once
            # This prevents both workers from preprocessing files in parallel at startup
            self._pipeline_semaphore.acquire()

            # Mark "processing" only after we hold the pipeline slot, so a queued
            # file stays pending (and two pool threads don't both write status
            # before the work actually starts).
            self._session_manager.update_file_status(
                self._session, str(path), "processing"
            )
            self.file_status.emit(path.name, "Processing")

            temp_wav = None
            try:
                # Monitor memory during this file
                with MemoryMonitor(f"File: {path.name}"):
                    # 1. Prepare Audio (Pipeline Step - Parallel but Limited)
                    # Use lock to ensure only ONE file is being prepared at a time
                    with self._prep_lock:
                        self.file_status.emit(path.name, "Pre-processing")
                        # Pass cancel check to allow killing ffmpeg
                        temp_wav = self._transcriber.prepare_audio(path, cancel_check=lambda: self._cancel)

                        # Track temp file in session
                        if temp_wav:
                            self._session_manager.add_temp_file(self._session, temp_wav)

                    # Check for cancellation immediately after preparation
                    if self._cancel:
                        if temp_wav and temp_wav.exists():
                            try:
                                import os
                                os.unlink(temp_wav)
                            except OSError:
                                pass
                        self._session_manager.update_file_status(
                            self._session, str(path), "failed", error="Cancelled"
                        )
                        return None

                    # Notify waiting for lock
                    self.file_status.emit(path.name, "Pre-processing Done")

                    # 2. Transcribe (Model Step - Sequential)
                    with self._model_lock:
                        if self._cancel:
                            self.file_status.emit(path.name, "Cancelled")
                            self._session_manager.update_file_status(
                                self._session, str(path), "failed", error="Cancelled"
                            )
                            return None

                        self.file_status.emit(path.name, "Processing by AI")
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
                            task=self._task,
                            patience=self._patience,
                            add_timestamps=self._add_timestamps,
                            add_report=self.add_report,
                            pre_converted_path=temp_wav, # Pass the pre-converted file
                            cancel_check=lambda: self._cancel,
                        )

                    # Update session: file completed
                    self._session_manager.update_file_status(
                        self._session, str(path), "completed",
                        output_path=str(result.output_path) if result.output_path else None
                    )

                    return result

            except MemoryError as e:
                # Special handling for memory errors
                error_msg = "Out of memory. Try using a smaller model or processing fewer files at once."
                import traceback
                LOGGER.error("MemoryError processing %s: %s", path.name, str(e))
                LOGGER.error("MemoryError traceback:\n%s", traceback.format_exc())
                self.file_status.emit(path.name, "Failed (Memory Error)")
                self._session_manager.update_file_status(
                    self._session, str(path), "failed", error=error_msg
                )

                # Aggressive memory cleanup after error
                MemoryManager.cleanup_memory(aggressive=True)
                return None

            except Exception as e:
                if str(e) == "Cancelled":
                    LOGGER.info("Processing cancelled for %s", path.name)
                    self.file_status.emit(path.name, "Cancelled")
                    self._session_manager.update_file_status(
                        self._session, str(path), "failed", error="Cancelled"
                    )
                    return None

                error_msg = str(e)
                LOGGER.error("Error processing %s: %s", path.name, error_msg)
                import traceback
                LOGGER.error(traceback.format_exc())

                # Update session with error
                self._session_manager.update_file_status(
                    self._session, str(path), "failed", error=error_msg
                )
                return None

            finally:
                # Release semaphore after transcription completes (or fails)
                # This allows the next file to start preprocessing
                self._pipeline_semaphore.release()

                # 3. Cleanup (Always run, even on error)
                if temp_wav and temp_wav.exists():
                    try:
                        import os
                        os.unlink(temp_wav)
                        # Remove from session temp file tracking
                        if str(temp_wav) in self._session.temp_files:
                            self._session.temp_files.remove(str(temp_wav))
                    except OSError:
                        pass

                # Lightweight memory cleanup between files
                MemoryManager.cleanup_between_files()

        # Submit all futures to global executor
        futures = {EXECUTOR.submit(_job, p): p for p in media_files}

        try:
            for future in as_completed(futures):
                if self._cancel:
                    # Clean up temp files before exiting
                    self._session_manager.cleanup_temp_files(self._session)
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

                # Emit 100% for this file (or base for next)
                if total > 0:
                    overall = int((processed * 100) / total)
                    self.progress.emit(overall)

        except Exception as exc:
            # Clean up temp files on error
            self._session_manager.cleanup_temp_files(self._session)
            LOGGER.error("Batch processing failed: %s", str(exc))
            self.failed.emit(str(exc))
            return

        # Final cleanup
        LOGGER.info("Batch processing completed")

        # Clean up all temp files
        self._session_manager.cleanup_temp_files(self._session)

        # Aggressive memory cleanup after batch
        MemoryManager.cleanup_between_batches()

        # Delete session file if all files completed successfully
        if self._session.is_complete and len(self._session.failed_files) == 0:
            LOGGER.info("All files completed successfully. Cleaning up session.")
            self._session_manager.delete_session(self._session.session_id)
        else:
            # Keep session for potential resume
            failed_count = len(self._session.failed_files)
            if failed_count > 0:
                LOGGER.warning("%d files failed. Session saved for resume.", failed_count)

        self.finished.emit(results)
