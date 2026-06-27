"""Session state management for resumable transcription batches."""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Optional
from datetime import datetime

LOGGER = logging.getLogger(__name__)


@dataclass
class FileStatus:
    """Status of a single file in the batch."""
    path: str
    status: str  # "pending", "processing", "completed", "failed"
    error: Optional[str] = None
    output_path: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


@dataclass
class SessionState:
    """State of a transcription batch session."""
    session_id: str
    created_at: str
    model_path: str
    output_dir: Optional[str]
    beam_size: int
    vad_filter: bool
    language: Optional[str]
    initial_prompt: Optional[str]
    task: str
    patience: float
    add_timestamps: bool
    add_report: bool

    files: List[FileStatus]
    temp_files: List[str]  # Track temp WAV files for cleanup

    @property
    def pending_files(self) -> List[FileStatus]:
        """Get all pending files.

        Note: Files in 'processing' state are also treated as pending
        when resuming a session, since the previous process was interrupted.
        """
        return [f for f in self.files if f.status in ("pending", "processing")]

    @property
    def completed_files(self) -> List[FileStatus]:
        """Get all completed files."""
        return [f for f in self.files if f.status == "completed"]

    @property
    def failed_files(self) -> List[FileStatus]:
        """Get all failed files."""
        return [f for f in self.files if f.status == "failed"]

    @property
    def is_complete(self) -> bool:
        """Check if all files are processed (completed or failed)."""
        return all(f.status in ("completed", "failed") for f in self.files)

    @property
    def progress_percent(self) -> int:
        """Calculate overall progress percentage."""
        if not self.files:
            return 0
        processed = len([f for f in self.files if f.status in ("completed", "failed")])
        return int((processed / len(self.files)) * 100)


class SessionManager:
    """Manages session state persistence for resumable batches."""

    def __init__(self, session_dir: Optional[Path] = None):
        """Initialize session manager.

        Args:
            session_dir: Directory to store session files.
                        Defaults to user's temp directory.
        """
        if session_dir is None:
            session_dir = Path(tempfile.gettempdir()) / "faster_whisper_sessions"

        self.session_dir = Path(session_dir)
        self.session_dir.mkdir(parents=True, exist_ok=True)

        # Guards in-memory session mutation + the (atomic) write so concurrent
        # worker threads can't interleave a read-modify-write or tear the file.
        self._lock = threading.RLock()

        LOGGER.info("Session manager initialized: %s", self.session_dir)

    def create_session(
        self,
        input_files: List[Path],
        model_path: str,
        output_dir: Optional[Path] = None,
        beam_size: int = 5,
        vad_filter: bool = False,
        language: Optional[str] = None,
        initial_prompt: Optional[str] = None,
        task: str = "transcribe",
        patience: float = 1.0,
        add_timestamps: bool = True,
        add_report: bool = True,
    ) -> SessionState:
        """Create a new session state."""
        session_id = datetime.now().strftime("%Y%m%d_%H%M%S")

        files = [
            FileStatus(path=str(p), status="pending")
            for p in input_files
        ]

        state = SessionState(
            session_id=session_id,
            created_at=datetime.now().isoformat(),
            model_path=model_path,
            output_dir=str(output_dir) if output_dir else None,
            beam_size=beam_size,
            vad_filter=vad_filter,
            language=language,
            initial_prompt=initial_prompt,
            task=task,
            patience=patience,
            add_timestamps=add_timestamps,
            add_report=add_report,
            files=files,
            temp_files=[],
        )

        self.save_session(state)
        LOGGER.info("Created session: %s (%d files)", session_id, len(files))

        return state

    def save_session(self, state: SessionState) -> None:
        """Save session state to disk atomically.

        Serializes under the instance lock and writes to a temp file in the same
        directory, then ``os.replace()``s it into place. A concurrent save from
        another worker thread can therefore never observe (or leave behind) a
        half-written/truncated JSON file, which previously silently destroyed
        the session and defeated resume.
        """
        session_file = self.session_dir / f"{state.session_id}.json"

        with self._lock:
            try:
                data = asdict(state)
                fd, tmp_name = tempfile.mkstemp(
                    dir=str(self.session_dir), suffix=".tmp")
                try:
                    with os.fdopen(fd, 'w', encoding='utf-8') as f:
                        json.dump(data, f, indent=2)
                    os.replace(tmp_name, session_file)  # atomic on same filesystem
                except Exception:
                    try:
                        os.unlink(tmp_name)
                    except OSError:
                        pass
                    raise
                LOGGER.debug("Session saved: %s", session_file)
            except Exception as e:
                LOGGER.error("Failed to save session %s: %s", state.session_id, e)

    def _is_session_safe(self, state: SessionState, expected_id: str) -> bool:
        """Validate a loaded session before trusting its paths.

        Guards against a planted/tampered session.json: the id must match the
        filename, and each file's resolved output (output_dir/<stem>.txt) must
        stay inside output_dir, so a crafted entry can't create/overwrite files
        elsewhere on resume.
        """
        if state.session_id != expected_id:
            LOGGER.warning("Session id mismatch: %s != %s",
                           state.session_id, expected_id)
            return False

        out_base = None
        if state.output_dir:
            try:
                out_base = Path(state.output_dir).resolve()
            except (OSError, ValueError):
                LOGGER.warning("Session has an invalid output_dir: %r", state.output_dir)
                return False

        for file_status in state.files:
            try:
                stem = Path(file_status.path).stem
                if out_base is not None:
                    target = (out_base / f"{stem}.txt").resolve()
                    if not target.is_relative_to(out_base):
                        LOGGER.warning("Session output escapes output_dir: %s", target)
                        return False
            except (OSError, ValueError):
                return False
        return True

    def load_session(self, session_id: str) -> Optional[SessionState]:
        """Load session state from disk."""
        session_file = self.session_dir / f"{session_id}.json"

        if not session_file.exists():
            LOGGER.warning("Session file not found: %s", session_file)
            return None

        try:
            with open(session_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # Reconstruct FileStatus objects
            files = [FileStatus(**f) for f in data['files']]
            data['files'] = files

            state = SessionState(**data)

            if not self._is_session_safe(state, session_id):
                LOGGER.error(
                    "Refusing to load session %s: failed safety validation", session_id)
                return None

            LOGGER.info("Loaded session: %s (%d files, %d pending)",
                       session_id, len(state.files), len(state.pending_files))

            return state
        except Exception as e:
            LOGGER.error("Failed to load session %s: %s", session_id, e)
            return None

    def delete_session(self, session_id: str) -> None:
        """Delete session file from disk."""
        session_file = self.session_dir / f"{session_id}.json"

        try:
            if session_file.exists():
                session_file.unlink()
                LOGGER.info("Deleted session: %s", session_id)
        except Exception as e:
            LOGGER.error("Failed to delete session %s: %s", session_id, e)

    def list_sessions(self) -> List[str]:
        """List all available session IDs."""
        try:
            sessions = [
                f.stem for f in self.session_dir.glob("*.json")
            ]
            return sorted(sessions, reverse=True)  # Most recent first
        except Exception as e:
            LOGGER.error("Failed to list sessions: %s", e)
            return []

    def get_latest_session(self) -> Optional[SessionState]:
        """Get the most recent incomplete session.

        Also cleans up old completed sessions (older than 1 hour) with no pending files.
        """
        sessions = self.list_sessions()

        # Clean up old completed sessions to prevent slowdowns
        import time
        current_time = time.time()
        cleaned_count = 0

        for session_id in sessions:
            state = self.load_session(session_id)
            if state:
                # Check if session is complete and has no pending files
                if len(state.pending_files) == 0 and state.is_complete:
                    # Check if session is older than 1 hour
                    try:
                        session_file = self.session_dir / f"{session_id}.json"
                        age_seconds = current_time - session_file.stat().st_mtime
                        if age_seconds > 3600:  # 1 hour
                            self.delete_session(session_id)
                            cleaned_count += 1
                            continue
                    except Exception:
                        pass

                # Return first incomplete session
                if not state.is_complete:
                    if cleaned_count > 0:
                        LOGGER.info("Cleaned up %d old completed sessions", cleaned_count)
                    return state

        if cleaned_count > 0:
            LOGGER.info("Cleaned up %d old completed sessions", cleaned_count)

        return None

    def update_file_status(
        self,
        state: SessionState,
        file_path: str,
        status: str,
        error: Optional[str] = None,
        output_path: Optional[str] = None,
    ) -> None:
        """Update status of a file in the session."""
        with self._lock:
            for file_status in state.files:
                if file_status.path == file_path:
                    old_status = file_status.status
                    file_status.status = status
                    file_status.error = error
                    file_status.output_path = output_path

                    now = datetime.now().isoformat()
                    if status == "processing" and old_status == "pending":
                        file_status.started_at = now
                    elif status in ("completed", "failed"):
                        file_status.completed_at = now

                    self.save_session(state)
                    LOGGER.debug("Updated %s: %s -> %s",
                                 Path(file_path).name, old_status, status)
                    break

    def add_temp_file(self, state: SessionState, temp_path: Path) -> None:
        """Track a temporary file for cleanup."""
        temp_str = str(temp_path)
        with self._lock:
            if temp_str not in state.temp_files:
                state.temp_files.append(temp_str)
                self.save_session(state)
                LOGGER.debug("Tracked temp file: %s", temp_path.name)

    def cleanup_temp_files(self, state: SessionState) -> None:
        """Clean up all tracked temporary files."""
        cleaned = 0
        with self._lock:
            for temp_path_str in state.temp_files[:]:  # Copy list
                temp_path = Path(temp_path_str)
                try:
                    if temp_path.exists():
                        os.unlink(temp_path)
                        cleaned += 1
                        LOGGER.debug("Deleted temp file: %s", temp_path.name)

                    # Remove from tracking list
                    state.temp_files.remove(temp_path_str)
                except Exception as e:
                    LOGGER.warning("Failed to delete temp file %s: %s", temp_path, e)

            if cleaned > 0:
                self.save_session(state)
                LOGGER.info("Cleaned up %d temp files", cleaned)

    def cleanup_orphaned_files(self) -> int:
        """Find and delete orphaned temp files from old sessions.

        Returns:
            Number of files cleaned up.
        """
        import tempfile
        import os
        import time

        temp_dir = Path(tempfile.gettempdir())
        cleaned = 0

        # Only our own temp WAVs (mkstemp uses the fwgui_ prefix) so we never
        # delete another app's or another user's tmp*.wav.
        for temp_file in temp_dir.glob("fwgui_*.wav"):
            try:
                # Check if file is older than 1 hour
                age_seconds = time.time() - temp_file.stat().st_mtime
                if age_seconds > 3600:  # 1 hour
                    os.unlink(temp_file)
                    cleaned += 1
                    LOGGER.debug("Deleted orphaned temp file: %s", temp_file.name)
            except Exception as e:
                LOGGER.warning("Failed to delete orphaned file %s: %s", temp_file, e)

        if cleaned > 0:
            LOGGER.info("Cleaned up %d orphaned temp files", cleaned)

        return cleaned
